# Downtify SaaS Backend

A separate SaaS foundation for account management, usage quotas, M-Pesa Daraja payments, and an Electron + React desktop client. This project is independent of any existing Downtify installation.

## Components
- **API:** FastAPI + SQLAlchemy, JWT bearer tokens, PostgreSQL.
- **Cache:** Redis service included for future rate limiting and background jobs.
- **Payments:** Daraja STK Push integration scaffold; credentials are supplied only through environment variables.
- **Desktop:** Electron + React + Vite starter client.

## Quick start
1. Copy `.env.example` to `.env` and set strong local values.
2. Start the API and data services:
   ```bash
   docker compose up --build -d
   ```
3. Open API docs at http://localhost:8088/docs.
4. For the desktop client:
   ```bash
   cd desktop
   npm install
   npm run dev
   ```

For a server at `192.168.9.7`, the API will be available at `http://192.168.9.7:8088` on your LAN if firewall rules permit it.

## Environment and security
- Never commit `.env`, Daraja keys, access tokens, passwords, or production secrets.
- Change `JWT_SECRET` and database passwords before use.
- Configure the Daraja callback URL to a publicly reachable HTTPS endpoint before live payment testing.
- This is a starter scaffold, not a production-audited payment system. Add migrations, HTTPS/reverse proxy, rate limits, monitoring, callback signature/transaction validation, idempotent payment processing, and concurrency-safe quota reservations before launch.
- Do not point this compose project at the existing Downtify database, volumes, or port 8000. It uses its own named volumes and API port 8088.

## Initial API routes
- `GET /health`
- `POST /auth/register`
- `POST /auth/login`
- `GET /me`
- `GET /quota`
- `POST /payments/mpesa/stk-push`
- `POST /payments/mpesa/callback`

Quota units and subscription plans are illustrative and must be aligned with your actual licensing and download provider before commercial use.
