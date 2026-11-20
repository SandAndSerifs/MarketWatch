"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { CheckCheck } from "lucide-react";
import { Badge, Button, Card, Empty, ErrorBox, Field, Loading, PageHeader, SeverityBadge } from "@/components/ui";
import { post, put } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useLive } from "@/lib/live";
import { fmtTime } from "@/lib/format";

const KINDS = ["", "signal", "trade", "risk", "summary", "market", "event", "system"];
const SEV = ["info", "notice", "warning", "critical"];

export default function Alerts() {
  const [kind, setKind] = useState("");
  const [unread, setUnread] = useState(false);
  const al = useApi<any>(`/api/alerts?limit=300${kind ? `&kind=${kind}` : ""}${unread ? "&unread=true" : ""}`, 30000);
  const prefs = useApi<any>("/api/alerts/prefs");
  const { lastAlert, desktopEnabled, setDesktopEnabled } = useLive();
  const [open, setOpen] = useState<number | null>(null);
  useEffect(() => { if (lastAlert) al.reload(); }, [lastAlert]); // eslint-disable-line react-hooks/exhaustive-deps
  const save = async (patch: any) => prefs.setData(await put("/api/alerts/prefs", patch));
  const perm = typeof Notification !== "undefined" ? Notification.permission : "unsupported";

  return (
    <div>
      <PageHeader title="Trading Alerts" subtitle="Signals, trigger hits, invalidations, unusual moves, paper trades, risk events and session summaries. Duplicates are suppressed by a per-alert cooldown and an hourly cap."
        right={<Button onClick={async () => { await post("/api/alerts/read-all"); al.reload(); }}><CheckCheck className="w-4 h-4" />Mark all read</Button>} />
      <div className="grid grid-cols-1 xl:grid-cols-4 gap-3">
        <Card title="Alerts" className="xl:col-span-3" right={
          <div className="flex gap-2 items-center">
            <select value={kind} onChange={(e) => setKind(e.target.value)}>{KINDS.map((k) => <option key={k} value={k}>{k || "All kinds"}</option>)}</select>
            <label className="flex items-center gap-1 text-[12px]"><input type="checkbox" checked={unread} onChange={(e) => setUnread(e.target.checked)} />Unread</label>
          </div>
        } pad={false}>
          {al.error ? <div className="p-3"><ErrorBox error={al.error} /></div> : !al.data ? <Loading /> : al.data.alerts.length === 0 ? <Empty>No alerts.</Empty> : (
            <ul className="divide-y divide-line">{al.data.alerts.map((a: any) => (
              <li key={a.id} className={`px-3 py-2 cursor-pointer ${a.read ? "" : "bg-accent/5"}`} onClick={async () => { setOpen(open === a.id ? null : a.id); if (!a.read) { await post(`/api/alerts/${a.id}/read`); al.reload(); } }}>
                <div className="flex items-center gap-2">
                  <SeverityBadge s={a.severity} /><Badge>{a.kind}</Badge>
                  {a.symbol && <Link onClick={(e) => e.stopPropagation()} href={`/analysis/${a.symbol}`} className="text-accent">{a.symbol}</Link>}
                  <span className="font-medium truncate flex-1">{a.title}</span>
                  <span className="text-[11px] text-mute whitespace-nowrap">{fmtTime(a.ts)}</span>
                </div>
                {open === a.id && <div className="mt-2 whitespace-pre-line text-[13px]">{a.body}{a.signal_id && <div className="mt-1"><Link className="text-accent" href="/scanner">View signal checklist in the Scanner</Link></div>}</div>}
              </li>
            ))}</ul>
          )}
        </Card>
        <Card title="Notification settings">
          {!prefs.data ? <Loading /> : (
            <div className="flex flex-col gap-3">
              <label className="flex items-center gap-2"><input type="checkbox" checked={desktopEnabled} onChange={(e) => setDesktopEnabled(e.target.checked)} />Desktop notifications <span className="text-[11px] text-mute">({perm})</span></label>
              <Field label="Kinds enabled">
                <div className="flex flex-wrap gap-1">{KINDS.filter(Boolean).map((k) => (
                  <button key={k} onClick={() => save({ enabled_kinds: prefs.data.enabled_kinds.includes(k) ? prefs.data.enabled_kinds.filter((x: string) => x !== k) : [...prefs.data.enabled_kinds, k] })}
                    className={`px-2 py-0.5 rounded text-[12px] border ${prefs.data.enabled_kinds.includes(k) ? "bg-accent/20 border-accent/40" : "border-line text-mute"}`}>{k}</button>
                ))}</div>
              </Field>
              {(["min_severity_desktop", "min_severity_email", "min_severity_webhook"] as const).map((k) => (
                <Field key={k} label={k.replace("min_severity_", "Min severity: ")}>
                  <select value={prefs.data[k]} onChange={(e) => save({ [k]: e.target.value })}>{SEV.map((s) => <option key={s}>{s}</option>)}</select>
                </Field>
              ))}
              <Field label="Max alerts per hour"><input type="number" min={1} max={500} value={prefs.data.max_per_hour} onChange={(e) => save({ max_per_hour: Number(e.target.value) })} /></Field>
              <Field label="Default cooldown (minutes)" hint="Same alert key is suppressed within this window"><input type="number" min={0} value={prefs.data.default_cooldown_minutes} onChange={(e) => save({ default_cooldown_minutes: Number(e.target.value) })} /></Field>
              <p className="text-[11px] text-mute">Email (SMTP) and webhook/phone push (e.g. ntfy.sh) are configured in backend/.env.</p>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
