import { useState } from "react";

const DEFAULT_API = "http://localhost:8088";

export default function App() {
  const [api, setApi] = useState(DEFAULT_API);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState("");
  const [status, setStatus] = useState("Connect to your Downtify SaaS API.");
  const [quota, setQuota] = useState(null);

  async function request(path, options = {}) {
    const response = await fetch(api.replace(/\/$/, "") + path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(options.headers || {})
      }
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
    return data;
  }

  async function auth(path) {
    try {
      const data = await request(path, { method: "POST", body: JSON.stringify({ email, password }) });
      setToken(data.access_token);
      setStatus("Signed in successfully.");
    } catch (error) {
      setStatus(error.message);
    }
  }

  async function loadQuota() {
    try {
      const data = await request("/quota");
      setQuota(data.quota_remaining);
      setStatus("Quota refreshed.");
    } catch (error) {
      setStatus(error.message);
    }
  }

  return (
    <main className="shell">
      <header><div className="mark">D</div><div><p className="eyebrow">DOWNTIFY SAAS</p><h1>Your music workflow, connected.</h1></div></header>
      <section className="panel">
        <label>API base URL<input value={api} onChange={e => setApi(e.target.value)} placeholder="http://192.168.9.7:8088" /></label>
        <label>Email<input type="email" value={email} onChange={e => setEmail(e.target.value)} autoComplete="username" /></label>
        <label>Password<input type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="current-password" /></label>
        <div className="actions"><button onClick={() => auth("/auth/login")}>Sign in</button><button className="secondary" onClick={() => auth("/auth/register")}>Create account</button></div>
        <div className="quota"><span>Available credits</span><strong>{quota === null ? "—" : quota}</strong><button className="secondary" onClick={loadQuota} disabled={!token}>Refresh quota</button></div>
        <p className="status">{status}</p>
      </section>
      <p className="footnote">Starter client · Payment and download workflows are not yet wired into this interface.</p>
    </main>
  );
}
