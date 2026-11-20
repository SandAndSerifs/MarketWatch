"use client";
import { useState } from "react";
import { Trash2 } from "lucide-react";
import { Badge, Button, Card, ErrorBox, Field, KV, Loading, PageHeader } from "@/components/ui";
import { del, post } from "@/lib/api";
import { useAction, useApi } from "@/lib/hooks";
import { fmtTime } from "@/lib/format";

const ok = (v: boolean) => <Badge color={v ? "green" : "amber"}>{v ? "configured" : "not configured"}</Badge>;

export default function Settings() {
  const st = useApi<any>("/api/settings");
  const status = useApi<any>("/api/status", 20000);
  const events = useApi<any[]>("/api/events?days=120");
  const mkt = useApi<any>("/api/market/status");
  const act = useAction();
  const [ev, setEv] = useState({ kind: "macro", name: "", date: "", time_et: "08:30", symbol: "", importance: "high", source: "", source_url: "" });
  const s = st.data;

  return (
    <div>
      <PageHeader title="Settings" subtitle="Credentials live only in backend/.env (never in the browser or the database). This page shows what is configured and lets you manage events, alerts and safety controls." />
      <ErrorBox error={st.error || act.error} />
      {!s ? <Loading /> : (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
          <Card title="Data sources & integrations">
            <KV rows={[
              ["Market data provider", s.market_data.provider],
              ["Alpaca keys", ok(s.market_data.alpaca_keys_configured)], ["Alpaca feed", s.market_data.alpaca_feed],
              ["Massive key", ok(s.market_data.massive_key_configured)],
              ["Live data quality", <span key="q" title={(s.market_data.quality.caveats || []).join("\n")}>{s.market_data.quality.label}</span>],
              ["Stale-data threshold", `${s.market_data.stale_quote_seconds}s`],
              ["Earnings calendar (Finnhub)", ok(s.earnings.finnhub_key_configured)],
              ["AI analyst", <span key="ai">{ok(s.ai.configured)} {s.ai.model} · effort {s.ai.effort}</span>],
              ["Email alerts", ok(s.notifications.email_configured)], ["Webhook / phone push", ok(s.notifications.webhook_configured)],
              ["Database", s.database],
            ]} />
            <p className="text-[12px] text-mute mt-3">{s.how_to_configure}</p>
          </Card>
          <Card title="Engine & safety">
            {status.data && (
              <KV rows={[
                ["Mode", <Badge key="m" color="amber">PAPER TRADING ONLY</Badge>],
                ["Scheduler", status.data.engine.scheduler_running ? "running" : status.data.engine.run_engine ? "starting/idle (no data provider)" : "disabled (RUN_ENGINE=false)"],
                ["Last engine tick", fmtTime(status.data.engine.last_tick)],
                ["Feed health", status.data.data.healthy ? "healthy" : status.data.data.reason],
                ["Stream", status.data.data.health.stream_connected ? "connected" : "not connected"],
                ["Emergency STOP", status.data.engine.kill_switch?.active ? <Badge key="k" color="red">ACTIVE</Badge> : "inactive"],
              ]} />
            )}
            {status.data?.engine.kill_switch?.active && <Button className="mt-3" onClick={async () => { await act.run(() => post("/api/emergency-stop/clear")); status.reload(); }}>Clear emergency STOP</Button>}
            {status.data && Object.keys(status.data.job_errors || {}).length > 0 && (
              <div className="mt-3"><div className="text-[11px] uppercase text-mute">Recent job errors</div>
                <ul className="text-[12px] text-warn list-disc pl-5">{Object.entries(status.data.job_errors).map(([k, v]: any) => <li key={k}>{k}: {v}</li>)}</ul></div>
            )}
          </Card>
          <Card title="Default risk limits (per experiment)">
            <KV rows={Object.entries(s.risk_defaults).filter(([k]) => k !== "hard_rules").map(([k, v]) => [k, String(v)] as [string, string])} />
            <div className="mt-2 text-[12px]">Hard rules (not configurable): {Object.entries(s.risk_defaults.hard_rules).map(([k, v]) => `${k.replace("_", " ")}: ${v ? "yes" : "no"}`).join(" · ")}</div>
            <div className="text-[12px] text-mute">Hard ceilings: {Object.entries(s.risk_hard_ceilings).map(([k, v]) => `${k} ≤ ${v}`).join(" · ")}</div>
          </Card>
          <Card title="Execution model (simulation)">
            <KV rows={Object.entries(s.execution_defaults).map(([k, v]) => [k, String(v)] as [string, string])} />
            <p className="text-[12px] text-mute mt-2">Fees: SEC Section 31 ($20.60/$1M, from 2026-04-04) and FINRA TAF ($0.000195/share, max $9.79) on sells.</p>
          </Card>
          <Card title="Exchange calendar">
            {mkt.data && (
              <>
                <KV rows={[["Now (ET)", fmtTime(mkt.data.now_utc)], ["Phase", mkt.data.phase], ["Next open", fmtTime(mkt.data.next_open)]]} />
                <div className="text-[12px] mt-2"><b>Upcoming holidays:</b> {mkt.data.upcoming_holidays.map((h: any) => `${h.date} ${h.name}`).join(" · ")}</div>
                <div className="text-[12px] mt-1"><b>Early closes (1 p.m. ET):</b> {mkt.data.upcoming_early_closes.map((h: any) => `${h.date} ${h.name}`).join(" · ")}</div>
              </>
            )}
          </Card>
          <Card title="Optional brokerage (read-only)">
            <KV rows={[["Robinhood Trading MCP", s.brokerage.enabled ? "enabled" : "disabled"], ["Mode", s.brokerage.mode], ["Endpoint", s.brokerage.endpoint],
              ["Token", ok(s.brokerage.token_configured)], ["Independent of paper trading", String(s.brokerage.independent_of_paper_trading)], ["Verified against live endpoint", String(s.brokerage.verified_live)]]} />
            <p className="text-[12px] text-mute mt-2">Only read tools are permitted ({s.brokerage.allowed_tools.length}). Order tools are blocked in code. MarketPilot never asks for your Robinhood password.</p>
          </Card>
        </div>
      )}

      <Card title="Economic & earnings events" className="mt-3">
        <div id="events" className="grid sm:grid-cols-4 gap-2 mb-3">
          <Field label="Kind"><select value={ev.kind} onChange={(e) => setEv({ ...ev, kind: e.target.value })}><option>macro</option><option>earnings</option></select></Field>
          <Field label="Name"><input value={ev.name} onChange={(e) => setEv({ ...ev, name: e.target.value })} placeholder="e.g. PCE inflation" /></Field>
          <Field label="Date"><input type="date" value={ev.date} onChange={(e) => setEv({ ...ev, date: e.target.value })} /></Field>
          <Field label="Time ET (HH:MM / bmo / amc)"><input value={ev.time_et} onChange={(e) => setEv({ ...ev, time_et: e.target.value })} /></Field>
          {ev.kind === "earnings" && <Field label="Symbol"><input value={ev.symbol} onChange={(e) => setEv({ ...ev, symbol: e.target.value.toUpperCase() })} /></Field>}
          <Field label="Importance"><select value={ev.importance} onChange={(e) => setEv({ ...ev, importance: e.target.value })}><option>high</option><option>medium</option><option>low</option></select></Field>
          <Field label="Source (required)"><input value={ev.source} onChange={(e) => setEv({ ...ev, source: e.target.value })} placeholder="BEA, company IR…" /></Field>
          <Field label="Source URL"><input value={ev.source_url} onChange={(e) => setEv({ ...ev, source_url: e.target.value })} /></Field>
        </div>
        <div className="flex gap-2 mb-3">
          <Button variant="primary" onClick={async () => { if (await act.run(() => post("/api/events", { ...ev, symbol: ev.symbol || "*", source_url: ev.source_url || null }))) events.reload(); }}>Add event</Button>
          <Button onClick={async () => { const r = await act.run(() => post("/api/events/refresh-earnings")); if (r) events.reload(); }}>Refresh earnings (Finnhub)</Button>
        </div>
        {!events.data ? <Loading /> : (
          <div className="overflow-x-auto"><table className="grid-table"><thead><tr><th>Date</th><th>Time ET</th><th>Kind</th><th>Symbol</th><th>Name</th><th>Importance</th><th>Source</th><th>Verified</th><th></th></tr></thead>
            <tbody>{events.data.map((e) => (
              <tr key={e.id}><td className="num">{e.date}</td><td className="num">{e.time_et || "—"}</td><td><Badge color={e.kind === "macro" ? "blue" : "amber"}>{e.kind}</Badge></td><td>{e.symbol}</td><td>{e.name}</td><td>{e.importance}</td>
                <td>{e.source_url ? <a className="text-accent" href={e.source_url} target="_blank" rel="noreferrer">{e.source}</a> : e.source}</td><td className="text-mute">{e.verified_at}</td>
                <td><button className="text-mute hover:text-down" onClick={async () => { await del(`/api/events/${e.id}`); events.reload(); }}><Trash2 className="w-3.5 h-3.5" /></button></td></tr>
            ))}</tbody></table></div>
        )}
      </Card>
    </div>
  );
}
