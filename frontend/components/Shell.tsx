"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import {
  Activity, Bell, Bot, BookOpen, ClipboardCheck, FlaskConical, Gauge, History, LayoutDashboard, LineChart, List,
  Menu, OctagonX, Radar, Settings, Swords, X,
} from "lucide-react";
import { post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useLive } from "@/lib/live";
import { ago } from "@/lib/format";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/scanner", label: "Market Scanner", icon: Radar },
  { href: "/watchlists", label: "Watchlists", icon: List },
  { href: "/analysis", label: "Stock Analysis", icon: LineChart },
  { href: "/alerts", label: "Trading Alerts", icon: Bell },
  { href: "/analyst", label: "AI Market Analyst", icon: Bot },
  { href: "/paper", label: "Autonomous Paper Trader", icon: Activity },
  { href: "/competition", label: "Strategy Competition", icon: Swords },
  { href: "/lab", label: "Strategy Lab", icon: FlaskConical },
  { href: "/trades", label: "Trade History", icon: History },
  { href: "/review", label: "Trade Review", icon: ClipboardCheck },
  { href: "/knowledge", label: "Knowledge Library", icon: BookOpen },
  { href: "/performance", label: "Performance Analytics", icon: Gauge },
  { href: "/settings", label: "Settings", icon: Settings },
];

function EmergencyStop() {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const go = async (flatten: boolean) => {
    setBusy(true);
    try {
      const r = await post("/api/emergency-stop", { flatten });
      setMsg(`Halted ${r.halted_experiments} experiment(s)${flatten ? "; flattening positions" : ""}.`);
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <button onClick={() => { setOpen(true); setMsg(null); }}
        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-down text-white font-semibold text-[12px] hover:bg-red-500">
        <OctagonX className="w-4 h-4" /> STOP
      </button>
      {open && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4" onClick={() => setOpen(false)}>
          <div className="bg-panel border border-line rounded-lg p-4 max-w-md w-full" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-lg font-semibold text-down flex items-center gap-2"><OctagonX className="w-5 h-5" />Emergency STOP</h3>
            <p className="text-mute mt-2">Halts every autonomous paper-trading experiment immediately, cancels armed setups and working entry orders. No real orders exist in MarketPilot.</p>
            <div className="flex flex-col gap-2 mt-4">
              <button disabled={busy} onClick={() => go(false)} className="px-3 py-2 rounded-md bg-down text-white font-semibold">Halt all trading (keep stops on open positions)</button>
              <button disabled={busy} onClick={() => go(true)} className="px-3 py-2 rounded-md border border-down text-down font-semibold">Halt and flatten all paper positions</button>
              <button onClick={() => setOpen(false)} className="px-3 py-2 rounded-md bg-panel2 border border-line">Cancel</button>
            </div>
            {msg && <p className="mt-3 text-[13px]">{msg}</p>}
          </div>
        </div>
      )}
    </>
  );
}

function TopBar({ onMenu }: { onMenu: () => void }) {
  const { connected, lastAlert } = useLive();
  const { data: status } = useApi<any>("/api/status", 15000);
  const { data: alerts, reload } = useApi<any>("/api/alerts?unread=true&limit=1", 30000);
  const [q, setQ] = useState("");
  const router = useRouter();
  useEffect(() => { if (lastAlert) reload(); }, [lastAlert, reload]);
  const m = status?.market;
  const d = status?.data;
  const phaseColor = m?.is_open ? "bg-up" : m?.phase === "premarket" || m?.phase === "afterhours" ? "bg-warn" : "bg-mute";
  return (
    <header className="h-12 shrink-0 border-b border-line bg-panel flex items-center gap-3 px-3">
      <button className="lg:hidden text-mute" onClick={onMenu} aria-label="menu"><Menu className="w-5 h-5" /></button>
      <form onSubmit={(e) => { e.preventDefault(); if (q.trim()) router.push(`/analysis/${q.trim().toUpperCase()}`); setQ(""); }} className="hidden sm:block">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Symbol (e.g. NVDA)" className="w-40" />
      </form>
      <div className="flex items-center gap-2 text-[12px] min-w-0">
        <span className={`w-2 h-2 rounded-full ${phaseColor}`} />
        <span className="uppercase tracking-wide truncate">{m ? m.phase.replace("_", " ") : "…"}</span>
        {m?.holiday && <span className="text-warn truncate">{m.holiday}</span>}
        {m?.early_close && <span className="text-warn">early close</span>}
      </div>
      <div className="hidden md:flex items-center gap-2 text-[12px] min-w-0">
        <span className="text-mute">Data:</span>
        {d ? (
          d.configured ? (
            <span title={(d.quality?.caveats || []).join("\n")} className={d.healthy ? "text-up" : "text-warn"}>
              {d.quality?.provider} · {d.quality?.label} {d.healthy ? "" : "· stale"}
            </span>
          ) : <Link href="/settings" className="text-warn underline">not configured</Link>
        ) : "…"}
        <span className={`w-1.5 h-1.5 rounded-full ${connected ? "bg-up" : "bg-down"}`} title={connected ? "Live link to backend" : "Backend link down"} />
      </div>
      <div className="ml-auto flex items-center gap-3">
        <span className="hidden sm:inline text-[11px] px-1.5 py-0.5 rounded bg-warn/15 text-warn font-semibold">PAPER TRADING ONLY</span>
        <Link href="/alerts" className="relative text-mute hover:text-ink" aria-label="alerts">
          <Bell className="w-5 h-5" />
          {alerts?.unread > 0 && <span className="absolute -top-1.5 -right-2 bg-down text-white rounded-full text-[10px] px-1 num">{alerts.unread}</span>}
        </Link>
        <EmergencyStop />
      </div>
    </header>
  );
}

export default function Shell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const [open, setOpen] = useState(false);
  const { lastAlert } = useLive();
  const [toast, setToast] = useState<any>(null);
  useEffect(() => {
    if (!lastAlert) return;
    setToast(lastAlert);
    const id = setTimeout(() => setToast(null), 8000);
    return () => clearTimeout(id);
  }, [lastAlert]);
  useEffect(() => setOpen(false), [path]);
  const nav = (
    <nav className="flex flex-col gap-0.5 p-2">
      {NAV.map(({ href, label, icon: Icon }) => {
        const active = href === "/" ? path === "/" : path.startsWith(href);
        return (
          <Link key={href} href={href}
            className={`flex items-center gap-2.5 px-2.5 py-1.5 rounded-md text-[13px] ${active ? "bg-accent/15 text-ink" : "text-mute hover:text-ink hover:bg-panel2"}`}>
            <Icon className={`w-4 h-4 ${active ? "text-accent" : ""}`} />{label}
          </Link>
        );
      })}
    </nav>
  );
  return (
    <div className="h-screen flex overflow-hidden">
      <aside className="hidden lg:flex w-56 shrink-0 flex-col border-r border-line bg-panel">
        <div className="h-12 flex items-center gap-2 px-4 border-b border-line">
          <Activity className="w-5 h-5 text-accent" /><span className="font-semibold tracking-wide">MarketPilot</span>
        </div>
        <div className="overflow-y-auto flex-1">{nav}</div>
        <div className="p-3 text-[11px] text-mute border-t border-line">Analysis & simulation only. Not financial advice. Past performance does not predict future results.</div>
      </aside>
      {open && (
        <div className="lg:hidden fixed inset-0 z-40 bg-black/60" onClick={() => setOpen(false)}>
          <aside className="w-64 h-full bg-panel border-r border-line" onClick={(e) => e.stopPropagation()}>
            <div className="h-12 flex items-center justify-between px-4 border-b border-line">
              <span className="font-semibold">MarketPilot</span>
              <button onClick={() => setOpen(false)}><X className="w-5 h-5" /></button>
            </div>
            {nav}
          </aside>
        </div>
      )}
      <div className="flex-1 flex flex-col min-w-0">
        <TopBar onMenu={() => setOpen(true)} />
        <main className="flex-1 overflow-y-auto p-3 sm:p-4">{children}</main>
      </div>
      {toast && (
        <Link href="/alerts" className="fixed bottom-4 right-4 z-50 max-w-sm bg-panel2 border border-line rounded-lg p-3 shadow-xl">
          <div className="text-[11px] uppercase text-mute">{toast.kind} · {ago(toast.ts)}</div>
          <div className="font-semibold mt-0.5">{toast.title}</div>
          <div className="text-mute text-[12px] mt-1 line-clamp-3 whitespace-pre-line">{toast.body}</div>
        </Link>
      )}
    </div>
  );
}
