from datetime import datetime, timedelta, timezone
import base64
import secrets
from typing import Generator

import httpx
import jwt
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from pwdlib import PasswordHash
from sqlalchemy import DateTime, Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_env: str = "development"
    jwt_secret: str = "development-only-change-me"
    jwt_expire_minutes: int = 1440
    database_url: str = "sqlite:///./dev.db"
    mpesa_env: str = "sandbox"
    mpesa_consumer_key: str = ""
    mpesa_consumer_secret: str = ""
    mpesa_shortcode: str = ""
    mpesa_passkey: str = ""
    mpesa_callback_url: str = ""


settings = Settings()
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    quota_remaining: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    checkout_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    merchant_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amount: Mapped[int] = mapped_column(Integer)
    phone: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(32), default="initiated")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


Base.metadata.create_all(bind=engine)
app = FastAPI(title="Downtify SaaS API", version="0.1.0")
bearer = HTTPBearer(auto_error=False)
password_hasher = PasswordHash.recommended()


class RegisterBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class StkPushBody(BaseModel):
    phone: str = Field(description="Safaricom number, e.g. 2547XXXXXXXX")
    amount: int = Field(ge=1, le=150000)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def make_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": str(user.id), "iat": now, "exp": now + timedelta(minutes=settings.jwt_expire_minutes)},
        settings.jwt_secret,
        algorithm="HS256",
    )


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Bearer token required")
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=["HS256"])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Account not found")
    return user


@app.get("/health")
def health():
    return {"status": "ok", "service": "downtify-saas-api"}


@app.post("/auth/register", status_code=201)
def register(body: RegisterBody, db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="Email already registered")
    user = User(email=email, password_hash=password_hasher.hash(body.password), quota_remaining=0)
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"access_token": make_token(user), "token_type": "bearer", "user_id": user.id}


@app.post("/auth/login")
def login(body: LoginBody, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not password_hasher.verify(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return {"access_token": make_token(user), "token_type": "bearer", "user_id": user.id}


@app.get("/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "email": user.email, "created_at": user.created_at}


@app.get("/quota")
def quota(user: User = Depends(current_user)):
    return {"quota_remaining": user.quota_remaining, "unit": "credits"}


def daraja_base_url() -> str:
    return "https://sandbox.safaricom.co.ke" if settings.mpesa_env.lower() == "sandbox" else "https://api.safaricom.co.ke"


async def daraja_access_token(client: httpx.AsyncClient) -> str:
    if not settings.mpesa_consumer_key or not settings.mpesa_consumer_secret:
        raise HTTPException(status_code=503, detail="Daraja credentials are not configured")
    raw = f"{settings.mpesa_consumer_key}:{settings.mpesa_consumer_secret}".encode()
    auth = base64.b64encode(raw).decode()
    response = await client.get(
        f"{daraja_base_url()}/oauth/v1/generate?grant_type=client_credentials",
        headers={"Authorization": f"Basic {auth}"},
    )
    response.raise_for_status()
    return response.json()["access_token"]


@app.post("/payments/mpesa/stk-push")
async def mpesa_stk_push(
    body: StkPushBody,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if not all([settings.mpesa_shortcode, settings.mpesa_passkey, settings.mpesa_callback_url]):
        raise HTTPException(status_code=503, detail="Daraja shortcode, passkey and public callback URL are required")
    if not (body.phone.startswith("254") and len(body.phone) == 12 and body.phone.isdigit()):
        raise HTTPException(status_code=422, detail="Use phone format 2547XXXXXXXX")
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    password = base64.b64encode(f"{settings.mpesa_shortcode}{settings.mpesa_passkey}{timestamp}".encode()).decode()
    async with httpx.AsyncClient(timeout=20) as client:
        token = await daraja_access_token(client)
        response = await client.post(
            f"{daraja_base_url()}/mpesa/stkpush/v1/processrequest",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "BusinessShortCode": settings.mpesa_shortcode,
                "Password": password,
                "Timestamp": timestamp,
                "TransactionType": "CustomerPayBillOnline",
                "Amount": body.amount,
                "PartyA": body.phone,
                "PartyB": settings.mpesa_shortcode,
                "PhoneNumber": body.phone,
                "CallBackURL": settings.mpesa_callback_url,
                "AccountReference": f"DOWNTIFY{user.id}",
                "TransactionDesc": "Downtify credits",
            },
        )
        if response.is_error:
            raise HTTPException(status_code=502, detail=f"Daraja request failed: {response.text[:300]}")
        result = response.json()
    payment = Payment(
        user_id=user.id,
        checkout_request_id=result.get("CheckoutRequestID"),
        merchant_request_id=result.get("MerchantRequestID"),
        amount=body.amount,
        phone=body.phone,
        status="pending",
    )
    db.add(payment)
    db.commit()
    return {
        "message": "STK Push request submitted; confirm payment status before granting credits.",
        "checkout_request_id": payment.checkout_request_id,
        "merchant_request_id": payment.merchant_request_id,
        "response_code": result.get("ResponseCode"),
        "customer_message": result.get("CustomerMessage"),
    }


@app.post("/payments/mpesa/callback")
async def mpesa_callback(payload: dict, db: Session = Depends(get_db)):
    # TODO production: verify callback origin/transaction, handle duplicate callbacks idempotently,
    # and reconcile CheckoutRequestID in case the callback arrives before the STK request is stored.
    data = payload.get("Body", {}).get("stkCallback", {})
    checkout_id = data.get("CheckoutRequestID")
    result_code = data.get("ResultCode")
    if not checkout_id:
        return {"ResultCode": 0, "ResultDesc": "Callback received"}
    payment = db.scalar(select(Payment).where(Payment.checkout_request_id == checkout_id))
    if payment is not None:
        payment.status = "paid" if result_code == 0 else "failed"
        if result_code == 0:
            user = db.get(User, payment.user_id)
            if user:
                # Illustrative conversion only: KES 1 buys 1 credit. Configure real pricing before launch.
                user.quota_remaining += payment.amount
        db.commit()
    return {"ResultCode": 0, "ResultDesc": "Callback received"}
