"use client";
import Link from "next/link";
import type { ReactNode } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";
import { ApiError } from "@/lib/api";
import { fmtPct, tone } from "@/lib/format";

export function Card({ title, right, children, className = "", pad = true }: {
  title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string; pad?: boolean;
}) {
  return (
    <section className={`bg-panel border border-line rounded-lg min-w-0 ${className}`}>
      {(title || right) && (
        <header className="flex items-center justify-between gap-2 px-3 py-2 border-b border-line">
          <h2 className="text-[12px] font-semibold uppercase tracking-wide text-mute">{title}</h2>
          <div className="flex items-center gap-2">{right}</div>
        </header>
      )}
      <div className={pad ? "p-3" : ""}>{children}</div>
    </section>
  );
}

export function PageHeader({ title, subtitle, right }: { title: string; subtitle?: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 mb-4">
      <div>
        <h1 className="text-xl font-semibold">{title}</h1>
        {subtitle && <p className="text-mute mt-0.5 max-w-3xl">{subtitle}</p>}
      </div>
      {right && <div className="flex flex-wrap items-center gap-2">{right}</div>}
    </div>
  );
}

export function Stat({ label, value, sub, valueClass = "" }: { label: string; value: ReactNode; sub?: ReactNode; valueClass?: string }) {
  return (
    <div className="bg-panel2 border border-line rounded-md px-3 py-2 min-w-0">
      <div className="text-[11px] uppercase tracking-wide text-mute truncate">{label}</div>
      <div className={`num text-[16px] 2xl:text-lg font-semibold whitespace-nowrap overflow-hidden text-ellipsis ${valueClass}`} title={typeof value === "string" ? value : undefined}>{value}</div>
      {sub && <div className="text-[11px] text-mute truncate">{sub}</div>}
    </div>
  );
}

const btnStyles = {
  primary: "bg-accent hover:bg-blue-500 text-white",
  ghost: "bg-panel2 hover:bg-[#1b2531] text-ink border border-line",
  danger: "bg-down hover:bg-red-500 text-white",
  success: "bg-up/90 hover:bg-up text-black",
} as const;

export function Button({ children, onClick, variant = "ghost", disabled, type = "button", className = "", title }: {
  children: ReactNode; onClick?: () => void; variant?: keyof typeof btnStyles; disabled?: boolean;
  type?: "button" | "submit"; className?: string; title?: string;
}) {
  return (
    <button type={type} title={title} onClick={onClick} disabled={disabled}
      className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[13px] font-medium transition disabled:opacity-40 disabled:cursor-not-allowed ${btnStyles[variant]} ${className}`}>
      {children}
    </button>
  );
}

export function Badge({ children, color = "gray", title }: { children: ReactNode; color?: string; title?: string }) {
  const map: Record<string, string> = {
    gray: "bg-[#1c2632] text-mute", green: "bg-up/15 text-up", red: "bg-down/15 text-down",
    amber: "bg-warn/15 text-warn", blue: "bg-accent/15 text-accent", sky: "bg-info/15 text-info",
  };
  return <span title={title} className={`inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-medium whitespace-nowrap ${map[color] || map.gray}`}>{children}</span>;
}

export function CategoryBadge({ c }: { c: string }) {
  const color = { BUY_CANDIDATE: "green", SELL_EXIT_CANDIDATE: "red", WATCH: "amber", HOLD_MANAGE: "blue", NO_TRADE: "gray" }[c] || "gray";
  return <Badge color={color}>{c.replace(/_/g, " ").replace("SELL EXIT", "SELL / EXIT").replace("HOLD MANAGE", "HOLD / MANAGE")}</Badge>;
}

export function SeverityBadge({ s }: { s: string }) {
  const color = { blocking: "red", serious: "red", critical: "red", warning: "amber", caution: "amber", notice: "blue", info: "gray" }[s] || "gray";
  return <Badge color={color}>{s}</Badge>;
}

export function StatusBadge({ s }: { s: string }) {
  const color = { running: "green", paused: "amber", halted: "red", stopped: "gray", complete: "green", failed: "red" }[s] || "blue";
  return <Badge color={color}>{s}</Badge>;
}

export function Pct({ v, d = 2 }: { v: number | null | undefined; d?: number }) {
  return <span className={`num ${tone(v)}`}>{fmtPct(v, d)}</span>;
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return <div className="flex items-center gap-2 text-mute py-6 justify-center"><Loader2 className="w-4 h-4 animate-spin" />{label}…</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="text-mute text-center py-6 px-3">{children}</div>;
}

export function ErrorBox({ error, compact }: { error: ApiError | Error | string | null; compact?: boolean }) {
  if (!error) return null;
  const msg = typeof error === "string" ? error : error.message;
  const status = typeof error === "object" && "status" in error ? (error as ApiError).status : undefined;
  const notConfigured = status === 503;
  return (
    <div className={`rounded-md border ${notConfigured ? "border-warn/40 bg-warn/5" : "border-down/40 bg-down/5"} ${compact ? "p-2" : "p-3"} text-[13px]`}>
      <div className="flex items-start gap-2">
        <AlertTriangle className={`w-4 h-4 mt-0.5 shrink-0 ${notConfigured ? "text-warn" : "text-down"}`} />
        <div className="min-w-0">
          <div className="break-words">{msg}</div>
          {notConfigured && (
            <div className="text-mute mt-1">
              MarketPilot never shows invented data. Add the required key to <code className="num">backend/.env</code> and restart the backend. See <Link className="text-accent underline" href="/settings">Settings</Link>.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="flex flex-col gap-1 min-w-0">
      <span className="text-[11px] uppercase tracking-wide text-mute">{label}</span>
      {children}
      {hint && <span className="text-[11px] text-mute">{hint}</span>}
    </label>
  );
}

export function Tabs({ tabs, value, onChange }: { tabs: { key: string; label: ReactNode }[]; value: string; onChange: (k: string) => void }) {
  return (
    <div className="flex gap-1 border-b border-line mb-3 overflow-x-auto">
      {tabs.map((t) => (
        <button key={t.key} onClick={() => onChange(t.key)}
          className={`px-3 py-1.5 text-[13px] border-b-2 -mb-px whitespace-nowrap ${value === t.key ? "border-accent text-ink" : "border-transparent text-mute hover:text-ink"}`}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function KV({ rows }: { rows: [ReactNode, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
      {rows.map(([k, v], i) => (
        <div key={i} className="contents">
          <dt className="text-mute whitespace-nowrap">{k}</dt>
          <dd className="num text-right min-w-0 break-words">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function PaperBadge() {
  return <Badge color="amber" title="All trades are simulated with hypothetical money">PAPER · HYPOTHETICAL</Badge>;
}
