"use client";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { Activity, Lock } from "lucide-react";
import { API_URL, SAME_ORIGIN } from "@/lib/api";

type AuthState = { required: boolean; logout: () => Promise<void> };
const Ctx = createContext<AuthState>({ required: false, logout: async () => {} });
export const useAuth = () => useContext(Ctx);

export default function AuthGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<"checking" | "ok" | "login">("checking");
  const [required, setRequired] = useState(false);
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const creds: RequestCredentials = SAME_ORIGIN ? "same-origin" : "omit";

  useEffect(() => {
    fetch(`${API_URL}/api/auth/status`, { credentials: creds, cache: "no-store" })
      .then((r) => r.json())
      .then((d) => { setRequired(!!d.required); setState(d.authenticated ? "ok" : "login"); })
      .catch(() => setState("ok")); // backend unreachable: let pages show their own connection errors
    const onRequired = () => setState("login");
    window.addEventListener("mp-auth-required", onRequired);
    return () => window.removeEventListener("mp-auth-required", onRequired);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const r = await fetch(`${API_URL}/api/auth/login`, {
        method: "POST", credentials: creds, headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: pw }),
      });
      if (r.ok) { window.location.reload(); return; }
      const d = await r.json().catch(() => ({}));
      setErr(d.detail || "Sign-in failed");
    } catch {
      setErr("Cannot reach the server");
    } finally {
      setBusy(false);
    }
  };

  const logout = async () => {
    await fetch(`${API_URL}/api/auth/logout`, { method: "POST", credentials: creds });
    window.location.reload();
  };

  if (state === "checking") return <div className="h-screen flex items-center justify-center text-mute">Loading…</div>;
  if (state === "login") {
    return (
      <div className="h-screen flex items-center justify-center p-4">
        <form onSubmit={submit} className="w-full max-w-sm bg-panel border border-line rounded-lg p-6 flex flex-col gap-3">
          <div className="flex items-center gap-2 mb-1"><Activity className="w-5 h-5 text-accent" /><span className="font-semibold text-lg">MarketPilot</span></div>
          <p className="text-mute text-[13px] flex items-center gap-1.5"><Lock className="w-3.5 h-3.5" />This instance is password-protected.</p>
          <input type="password" autoFocus autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} placeholder="Password" className="py-2" />
          {err && <p className="text-down text-[13px]">{err}</p>}
          <button disabled={busy || !pw} className="px-3 py-2 rounded-md bg-accent text-white font-medium disabled:opacity-40">{busy ? "Signing in…" : "Sign in"}</button>
          <p className="text-[11px] text-mute">Paper trading only. Not financial advice.</p>
        </form>
      </div>
    );
  }
  return <Ctx.Provider value={{ required, logout }}>{children}</Ctx.Provider>;
}
