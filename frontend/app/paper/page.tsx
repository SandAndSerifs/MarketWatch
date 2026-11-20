"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Pause, Play, Plus, RotateCcw, Square, Wand2 } from "lucide-react";
import { LineChart, toPctSeries } from "@/components/Charts";
import ExperimentForm from "@/components/ExperimentForm";
import { Badge, Button, Card, CategoryBadge, Empty, ErrorBox, Loading, PageHeader, PaperBadge, Pct, Stat, StatusBadge, Tabs } from "@/components/ui";
import { post } from "@/lib/api";
import { useAction, useApi } from "@/lib/hooks";
import { fmtMoney, fmtNum, fmtTime, tone } from "@/lib/format";

function ExperimentDetail({ id, onChanged }: { id: number; onChanged: () => void }) {
  const ex = useApi<any>(`/api/experiments/${id}`, 15000);
  const dec = useApi<any[]>(`/api/experiments/${id}/decisions?limit=100`, 60000);
  const ord = useApi<any[]>(`/api/experiments/${id}/orders`, 30000);
  const status = useApi<any>("/api/status", 30000);
  const act = useAction();
  const [tab, setTab] = useState("positions");
  const [msg, setMsg] = useState<string | null>(null);
  const control = async (a: string) => {
    if (a === "reset" && !confirm("Reset archives this experiment (history is kept) and creates a fresh copy. Continue?")) return;
    const r = await act.run(() => post(`/api/experiments/${id}/${a}`));
    if (r) {
      setMsg(r.setups ? `Evaluated ${r.setups.evaluated} symbols, ${r.setups.proposals} proposals, ${r.setups.armed} armed setups.` : r.setups_error || null);
      ex.reload(); dec.reload(); onChanged();
    }
  };
  if (ex.error) return <ErrorBox error={ex.error} />;
  if (!ex.data) return <Loading />;
  const e = ex.data;
  const s = e.stats;
  const ts = s.trade_stats;
  const autoPaused = status.data?.engine?.auto_paused?.[String(id)];
  const curve = toPctSeries((e.equity_curve || []).map((p: any) => ({ t: p.ts, v: p.equity })));
  const bench = toPctSeries((e.equity_curve || []).map((p: any) => ({ t: p.ts, v: p.benchmark_price })));

  return (
    <div className="flex flex-col gap-3">
      <Card title={<span className="normal-case text-ink text-[14px]">{e.name}</span>} right={
        <div className="flex flex-wrap gap-1.5">
          <StatusBadge s={e.status} />
          {e.status === "stopped" && <Button variant="success" onClick={() => control("start")} disabled={act.busy}><Play className="w-4 h-4" />Start</Button>}
          {e.status === "running" && <Button onClick={() => control("pause")} disabled={act.busy}><Pause className="w-4 h-4" />Pause</Button>}
          {(e.status === "paused" || e.status === "halted") && <Button variant="success" onClick={() => control("resume")} disabled={act.busy}><Play className="w-4 h-4" />Resume</Button>}
          {e.status !== "stopped" && <Button onClick={() => control("stop")} disabled={act.busy}><Square className="w-4 h-4" />Stop</Button>}
          <Button onClick={() => control("generate-setups")} disabled={act.busy} title="Scan the universe now on completed daily bars"><Wand2 className="w-4 h-4" />Scan now</Button>
          {e.status === "stopped" && <Button onClick={() => control("reset")} disabled={act.busy}><RotateCcw className="w-4 h-4" />Reset</Button>}
        </div>
      }>
        <ErrorBox error={act.error} />
        {msg && <p className="text-[12px] text-mute mb-2">{msg}</p>}
        {e.halted_reason && <p className="text-down text-[12px] mb-2">Halted: {e.halted_reason}</p>}
        {autoPaused && <p className="text-warn text-[12px] mb-2">Automatically paused: {autoPaused}</p>}
        <div className="text-[12px] text-mute mb-3">{e.strategy_key} v{e.strategy_version} · universe {e.universe_size} symbols · started {fmtTime(e.started_at)} · max position {e.risk_effective?.max_position_pct}% of start · max {e.risk_effective?.max_concurrent_positions} positions · daily loss limit {e.risk_effective?.max_daily_loss_pct}% · risk {e.risk_effective?.risk_per_trade_pct}%/trade</div>
        <div className="grid grid-cols-2 md:grid-cols-4 2xl:grid-cols-8 gap-2">
          <Stat label="Starting" value={fmtMoney(e.starting_capital, 0)} />
          <Stat label="Equity" value={fmtMoney(e.equity)} valueClass={tone(e.equity - e.starting_capital)} />
          <Stat label="Cash" value={fmtMoney(e.cash)} />
          <Stat label="Realized P&L" value={fmtMoney(e.realized_pnl)} valueClass={tone(e.realized_pnl)} />
          <Stat label="Unrealized" value={fmtMoney(e.unrealized_pnl)} valueClass={tone(e.unrealized_pnl)} />
          <Stat label="Today" value={fmtMoney(e.day_pnl)} valueClass={tone(e.day_pnl)} />
          <Stat label="Total return" value={<Pct v={s.total_return_pct} />} sub={s.benchmark ? `SPY ${fmtNum(s.benchmark.return_pct)}%` : "SPY n/a"} />
          <Stat label="Max drawdown" value={`${fmtNum(s.max_drawdown_pct)}%`} valueClass="text-down" />
          <Stat label="Hit rate" value={ts.win_rate != null ? `${fmtNum(ts.win_rate, 1)}%` : "—"} sub={ts.win_rate_ci95 ? `95% CI ${ts.win_rate_ci95[0]}–${ts.win_rate_ci95[1]}%` : `${ts.trades} closed`} />
          <Stat label="Profit factor" value={fmtNum(ts.profit_factor)} />
          <Stat label="Expectancy" value={ts.expectancy_r != null ? `${fmtNum(ts.expectancy_r)}R` : "—"} />
          <Stat label="Sharpe (daily)" value={fmtNum(s.sharpe)} />
          <Stat label="Largest win" value={fmtMoney(ts.largest_win)} valueClass="text-up" />
          <Stat label="Largest loss" value={fmtMoney(ts.largest_loss)} valueClass="text-down" />
          <Stat label="Open / closed" value={`${e.open_trades} / ${e.closed_trades}`} />
          <Stat label="Armed setups" value={e.armed_setups.length} />
        </div>
        {ts.sample_warning && <p className="text-[11px] text-warn mt-2">{ts.sample_warning}</p>}
      </Card>

      <Card title="Equity curve vs SPY (same period, % change)">
        {curve.length < 2 ? <Empty>Equity snapshots are recorded every 30 minutes during the session and at the close.</Empty> :
          <LineChart percent series={[{ name: "Experiment", color: "#3b82f6", points: curve }, { name: "SPY", color: "#7f8c9b", points: bench }]} />}
      </Card>

      <Card pad={false}>
        <div className="px-3 pt-2"><Tabs value={tab} onChange={setTab} tabs={[
          { key: "positions", label: `Open positions (${e.positions.length})` }, { key: "setups", label: `Armed setups (${e.armed_setups.length})` },
          { key: "decisions", label: "Decision log" }, { key: "orders", label: "Simulated orders" }]} /></div>
        <div className="overflow-x-auto">
          {tab === "positions" && (e.positions.length === 0 ? <Empty>No open positions. Holding cash is a valid decision.</Empty> : (
            <table className="grid-table"><thead><tr><th>Symbol</th><th className="text-right">Qty</th><th className="text-right">Avg cost</th><th className="text-right">Last</th><th className="text-right">Value</th><th className="text-right">Unrealized</th><th className="text-right">Stop</th><th className="text-right">Target</th><th>Marked</th><th></th></tr></thead>
              <tbody>{e.positions.map((p: any) => (
                <tr key={p.symbol}><td><Link href={`/analysis/${p.symbol}`} className="text-accent">{p.symbol}</Link></td><td className="num text-right">{p.qty}</td>
                  <td className="num text-right">{fmtNum(p.avg_cost)}</td><td className="num text-right">{fmtNum(p.last_price)}</td><td className="num text-right">{fmtMoney(p.market_value)}</td>
                  <td className={`num text-right ${tone(p.unrealized_pnl)}`}>{fmtMoney(p.unrealized_pnl)}</td><td className="num text-right">{fmtNum(p.stop)}</td><td className="num text-right">{fmtNum(p.target)}</td>
                  <td className="text-mute">{fmtTime(p.last_price_ts)}</td>
                  <td className="whitespace-nowrap"><Link href={`/trades/${p.trade_id}`} className="text-accent mr-3">Review</Link>
                    <button className="text-down" onClick={async () => { if (confirm(`Close ${p.symbol} at the simulated market price?`)) { await act.run(() => post(`/api/trades/${p.trade_id}/close`)); ex.reload(); } }}>Close</button></td></tr>
              ))}</tbody></table>
          ))}
          {tab === "setups" && (e.armed_setups.length === 0 ? <Empty>No armed setups. Setups are generated after the close (and at startup) from completed daily bars.</Empty> : (
            <table className="grid-table"><thead><tr><th>Symbol</th><th className="text-right">Trigger</th><th className="text-right">Stop</th><th className="text-right">Target</th><th>Expires</th><th></th></tr></thead>
              <tbody>{e.armed_setups.map((a: any) => (
                <tr key={a.id}><td>{a.symbol}</td><td className="num text-right">{fmtNum(a.trigger)}</td><td className="num text-right">{fmtNum(a.stop)}</td><td className="num text-right">{fmtNum(a.target)}</td>
                  <td className="text-mute">{fmtTime(a.expires_at)}</td><td><Link className="text-accent" href={`/review?decision=${a.decision_id}`}>Checklist</Link></td></tr>
              ))}</tbody></table>
          ))}
          {tab === "decisions" && (!dec.data ? <Loading /> : dec.data.length === 0 ? <Empty>No decisions yet.</Empty> : (
            <table className="grid-table"><thead><tr><th>Time</th><th>Symbol</th><th>Decision</th><th>Approved</th><th>Rationale</th><th></th></tr></thead>
              <tbody>{dec.data.map((d) => (
                <tr key={d.id}><td className="text-mute whitespace-nowrap">{fmtTime(d.ts)}</td><td>{d.symbol}</td><td><CategoryBadge c={d.category} /></td>
                  <td>{d.approved ? <Badge color="green">yes</Badge> : <Badge>no</Badge>}</td><td className="text-mute max-w-xl truncate" title={d.rejections?.join("; ")}>{d.summary}{d.rejections?.length ? ` — ${d.rejections.join("; ")}` : ""}</td>
                  <td><Link className="text-accent" href={`/review?decision=${d.id}`}>Open</Link></td></tr>
              ))}</tbody></table>
          ))}
          {tab === "orders" && (!ord.data ? <Loading /> : ord.data.length === 0 ? <Empty>No simulated orders yet.</Empty> : (
            <table className="grid-table"><thead><tr><th>Time</th><th>Client id</th><th>Symbol</th><th>Side</th><th>Type</th><th>Purpose</th><th className="text-right">Qty</th><th className="text-right">Filled</th><th className="text-right">Avg px</th><th className="text-right">Fees</th><th>Status</th></tr></thead>
              <tbody>{ord.data.map((o) => (
                <tr key={o.id}><td className="text-mute whitespace-nowrap">{fmtTime(o.created_at)}</td><td className="num text-[11px] text-mute">{o.client_order_id}</td><td>{o.symbol}</td>
                  <td className={o.side === "buy" ? "text-up" : "text-down"}>{o.side}</td><td>{o.order_type}</td><td>{o.purpose}</td><td className="num text-right">{o.qty}</td>
                  <td className="num text-right">{o.filled_qty}</td><td className="num text-right">{fmtNum(o.avg_fill_price)}</td><td className="num text-right">{fmtNum(o.fees)}</td>
                  <td title={o.reject_reason || ""}><Badge color={o.status === "filled" ? "green" : o.status === "rejected" ? "red" : "gray"}>{o.status}</Badge></td></tr>
              ))}</tbody></table>
          ))}
        </div>
      </Card>
    </div>
  );
}

export default function Paper() {
  const list = useApi<any[]>("/api/experiments", 20000);
  const status = useApi<any>("/api/status", 30000);
  const [sel, setSel] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  useEffect(() => { if (!sel && list.data?.length) setSel(list.data[0].id); }, [list.data, sel]);
  const ks = status.data?.engine?.kill_switch;
  return (
    <div>
      <PageHeader title="Autonomous Paper Trader"
        subtitle="Real market data, hypothetical money. The engine scans, argues against each idea, sizes positions, simulates fills with spread/slippage/fees and manages exits. Deterministic risk controls cannot be bypassed by AI."
        right={<><PaperBadge /><Button variant="primary" onClick={() => setCreating((c) => !c)}><Plus className="w-4 h-4" />New experiment</Button></>} />
      {ks?.active && (
        <div className="mb-3 rounded-md border border-down/50 bg-down/10 p-3 flex items-center justify-between gap-3">
          <span><b className="text-down">Emergency STOP active</b> since {fmtTime(ks.at)}. All experiments are halted.</span>
          <Button onClick={async () => { await post("/api/emergency-stop/clear"); status.reload(); }}>Clear STOP</Button>
        </div>
      )}
      {status.data && !status.data.data.configured && <div className="mb-3"><ErrorBox error={{ status: 503, message: "No market data provider configured: the paper trader cannot see prices, so it will not trade." } as any} /></div>}
      {creating && <Card title="New experiment" className="mb-3"><ExperimentForm onCreated={(e) => { setCreating(false); setSel(e.id); list.reload(); }} /></Card>}
      <div className="grid grid-cols-1 xl:grid-cols-5 gap-3">
        <Card title="Experiments" pad={false} className="xl:col-span-1">
          {list.error ? <div className="p-3"><ErrorBox error={list.error} /></div> : !list.data ? <Loading /> : list.data.length === 0 ? <Empty>No experiments. Create one to start with $10,000 hypothetical capital.</Empty> : (
            <ul className="divide-y divide-line">{list.data.map((e) => (
              <li key={e.id} onClick={() => setSel(e.id)} className={`px-3 py-2 cursor-pointer ${sel === e.id ? "bg-accent/10" : "hover:bg-panel2"}`}>
                <div className="flex justify-between gap-2"><span className="truncate">{e.name}</span><StatusBadge s={e.status} /></div>
                <div className="flex justify-between text-[12px] mt-0.5"><span className="text-mute">{e.strategy_key}</span><span className="num">{fmtMoney(e.equity, 0)} <Pct v={e.stats.total_return_pct} /></span></div>
              </li>
            ))}</ul>
          )}
        </Card>
        <div className="xl:col-span-4 min-w-0">{sel ? <ExperimentDetail key={sel} id={sel} onChanged={list.reload} /> : <Empty>Select or create an experiment.</Empty>}</div>
      </div>
    </div>
  );
}
