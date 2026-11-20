"use client";
import { useEffect, useMemo, useState } from "react";
import { FlaskConical, Play } from "lucide-react";
import { LineChart } from "@/components/Charts";
import { Badge, Button, Card, Empty, ErrorBox, Field, Loading, PageHeader, Pct, StatusBadge, Tabs } from "@/components/ui";
import { post } from "@/lib/api";
import { useAction, useApi } from "@/lib/hooks";
import { fmtNum, fmtTime } from "@/lib/format";

const SEGS = ["train", "validation", "test", "full"];
const METRICS: [string, string][] = [["return_pct", "Return %"], ["benchmark_spy_return_pct", "SPY %"], ["max_drawdown_pct", "Max DD %"], ["sharpe", "Sharpe"], ["sortino", "Sortino"],
  ["trades", "Trades"], ["trades_per_month", "Trades/mo"], ["win_rate", "Win %"], ["profit_factor", "Profit factor"], ["expectancy_r", "Expectancy R"], ["avg_win", "Avg win $"], ["avg_loss", "Avg loss $"], ["longest_losing_streak", "Max loss streak"]];

function BacktestDetail({ id }: { id: number }) {
  const bt = useApi<any>(`/api/backtests/${id}`, 5000);
  const [tab, setTab] = useState("segments");
  const b = bt.data;
  const curve = useMemo(() => (b?.equity_curve || []).map((p: any) => ({ t: p.date + "T16:00:00-05:00", v: p.equity })), [b]);
  if (bt.error) return <ErrorBox error={bt.error} />;
  if (!b) return <Loading />;
  return (
    <Card title={`Backtest #${b.id} · ${b.strategy_key} v${b.strategy_version}`} right={<StatusBadge s={b.status} />}>
      <div className="text-[12px] text-mute mb-2">{b.start} → {b.end}{b.scenario ? ` · scenario ${b.scenario}` : ""} · {b.universe_size} symbols · data {b.data_source} · params {JSON.stringify(b.params)}</div>
      {b.status === "running" && <Loading label="Running backtest on genuine historical data" />}
      {b.status === "failed" && <ErrorBox error={b.error} />}
      {b.warnings?.length > 0 && <ul className="mb-3 text-[12px] text-warn list-disc pl-5">{b.warnings.map((w: string, i: number) => <li key={i}>{w}</li>)}</ul>}
      {b.status === "complete" && (
        <>
          <Tabs value={tab} onChange={setTab} tabs={[{ key: "segments", label: "Train / validation / out-of-sample" }, { key: "curve", label: "Equity curve" }, { key: "regime", label: "By market regime" }, { key: "trades", label: `Trades (${b.trades.length})` }, { key: "assump", label: "Assumptions" }]} />
          {tab === "segments" && (
            <div className="overflow-x-auto">
              <table className="grid-table"><thead><tr><th>Metric</th>{SEGS.map((s) => <th key={s} className="text-right">{s === "test" ? "out-of-sample test" : s}</th>)}</tr></thead>
                <tbody>
                  <tr><td className="text-mute">Period</td>{SEGS.map((s) => <td key={s} className="num text-right text-[11px]">{b.segments[s] ? `${b.segments[s].start} → ${b.segments[s].end}` : "—"}</td>)}</tr>
                  {METRICS.map(([k, l]) => <tr key={k}><td className="text-mute">{l}</td>{SEGS.map((s) => <td key={s} className="num text-right">{b.segments[s]?.[k] != null ? fmtNum(b.segments[s][k]) : "—"}</td>)}</tr>)}
                </tbody></table>
              <p className="text-[11px] text-mute mt-2">Choose parameters on train/validation only. Read the out-of-sample column once. Historical results do not predict future results; they are kept separate from forward paper trading.</p>
              {b.segments.test?.sample_warning && <p className="text-[12px] text-warn mt-1">Out-of-sample: {b.segments.test.sample_warning}</p>}
            </div>
          )}
          {tab === "curve" && (curve.length < 2 ? <Empty>No equity data.</Empty> : <LineChart series={[{ name: "Equity", color: "#3b82f6", points: curve }]} height={300} />)}
          {tab === "regime" && (
            <table className="grid-table"><thead><tr><th>Regime at entry</th><th className="text-right">Trades</th><th className="text-right">Win %</th><th className="text-right">PF</th><th className="text-right">Expectancy R</th></tr></thead>
              <tbody>{Object.entries(b.segments.by_regime || {}).map(([k, v]: any) => <tr key={k}><td>{k}</td><td className="num text-right">{v.trades}</td><td className="num text-right">{fmtNum(v.win_rate, 1)}</td><td className="num text-right">{fmtNum(v.profit_factor)}</td><td className="num text-right">{fmtNum(v.expectancy_r, 3)}</td></tr>)}</tbody></table>
          )}
          {tab === "trades" && (
            <div className="overflow-x-auto max-h-[480px]">
              <table className="grid-table"><thead><tr><th>Symbol</th><th>Entry</th><th className="text-right">Px</th><th>Exit</th><th className="text-right">Px</th><th>Rule</th><th className="text-right">R</th><th className="text-right">Net $</th><th className="text-right">MAE/MFE R</th></tr></thead>
                <tbody>{b.trades.map((t: any, i: number) => (
                  <tr key={i}><td>{t.symbol}</td><td className="num">{t.entry_date}</td><td className="num text-right">{fmtNum(t.entry_price)}</td><td className="num">{t.exit_date}</td><td className="num text-right">{fmtNum(t.exit_price)}</td>
                    <td title={t.exit_reason}>{t.exit_rule}</td><td className="num text-right">{fmtNum(t.r_multiple)}</td><td className="text-right"><Pct v={t.net_pnl} /></td><td className="num text-right text-mute">{t.mae_r}/{t.mfe_r}</td></tr>
                ))}</tbody></table>
            </div>
          )}
          {tab === "assump" && <pre className="text-[11px] bg-panel2 p-3 rounded overflow-x-auto">{JSON.stringify(b.assumptions, null, 2)}</pre>}
        </>
      )}
    </Card>
  );
}

export default function Lab() {
  const strategies = useApi<any[]>("/api/strategies");
  const bts = useApi<any[]>("/api/backtests", 10000);
  const scen = useApi<any>("/api/scenarios");
  const versions = useApi<any[]>("/api/strategies/versions", 30000);
  const [key, setKey] = useState("trend_pullback");
  const [params, setParams] = useState<Record<string, any>>({});
  const [start, setStart] = useState("2019-01-02");
  const [end, setEnd] = useState("2025-12-31");
  const [sel, setSel] = useState<number | null>(null);
  const [tab, setTab] = useState("backtest");
  const [grid, setGrid] = useState('{"target_r": [1.5, 2, 3], "rsi2_max": [10, 15]}');
  const [opt, setOpt] = useState<any>(null);
  const [reason, setReason] = useState("");
  const act = useAction();
  const strat = strategies.data?.find((s) => s.key === key);
  useEffect(() => { if (strat) setParams({ ...strat.params }); }, [key, strategies.data]); // eslint-disable-line react-hooks/exhaustive-deps
  const numParams = () => Object.fromEntries(Object.entries(params).filter(([k]) => k !== "rules").map(([k, v]) => [k, Number(v)]));

  const runBt = async () => { const r = await act.run(() => post("/api/backtests", { strategy_key: key, params: numParams(), start, end })); if (r) { setSel(r.id); bts.reload(); } };
  const runScen = async () => { const r = await act.run(() => post("/api/scenarios/run", { strategy_key: key, params: numParams(), scenarios: Object.keys(scen.data || {}).filter((k) => k !== "gfc_2008") })); if (r) bts.reload(); };
  const runOpt = async () => { let g; try { g = JSON.parse(grid); } catch { act.setError("Grid must be valid JSON"); return; } const r = await act.run(() => post("/api/backtests/optimize", { strategy_key: key, grid: g, start, end })); if (r) setOpt(r); };
  const saveVersion = async () => { const r = await act.run(() => post("/api/strategies/versions", { strategy_key: key, params: numParams(), change_reason: reason || "Parameter change from Strategy Lab" })); if (r) versions.reload(); };

  return (
    <div>
      <PageHeader title="Strategy Lab" subtitle="Backtest on genuine historical data with realistic costs, chronological train/validation/out-of-sample splits, regime breakdowns and historical scenario replays. Every parameter set is a distinct, permanently recorded version." />
      <ErrorBox error={act.error} />
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
        <Card title="Configure" className="xl:col-span-1">
          <Tabs value={tab} onChange={setTab} tabs={[{ key: "backtest", label: "Backtest" }, { key: "scenarios", label: "Scenarios" }, { key: "optimize", label: "Optimize" }, { key: "versions", label: "Versions" }]} />
          <div className="flex flex-col gap-3">
            <Field label="Strategy"><select value={key} onChange={(e) => setKey(e.target.value)}>{(strategies.data || []).filter((s) => s.key !== "custom").map((s) => <option key={s.key} value={s.key} disabled={!s.backtestable}>{s.name}{!s.backtestable ? " (forward-test only)" : ""}</option>)}</select></Field>
            {strat && <p className="text-[12px] text-mute">{strat.description}</p>}
            {strat && <div className="grid grid-cols-2 gap-2">{strat.param_specs.map((p: any) => (
              <Field key={p.name} label={p.name}><input type="number" step="any" value={params[p.name] ?? ""} onChange={(e) => setParams({ ...params, [p.name]: e.target.value })} title={p.description} /></Field>
            ))}</div>}
            {tab !== "scenarios" && tab !== "versions" && <div className="grid grid-cols-2 gap-2"><Field label="Start"><input type="date" value={start} onChange={(e) => setStart(e.target.value)} /></Field><Field label="End"><input type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></Field></div>}
            {tab === "backtest" && <Button variant="primary" onClick={runBt} disabled={act.busy}><Play className="w-4 h-4" />Run backtest</Button>}
            {tab === "scenarios" && (
              <>
                <ul className="text-[12px] flex flex-col gap-1">{Object.entries(scen.data || {}).map(([k, v]: any) => <li key={k}><b>{v.name}</b> <span className="text-mute">{v.start} → {v.end} · {v.type}{v.note ? ` · ${v.note}` : ""}</span></li>)}</ul>
                <Button variant="primary" onClick={runScen} disabled={act.busy}><FlaskConical className="w-4 h-4" />Replay all available scenarios</Button>
                <p className="text-[11px] text-mute">Replays use only information available at each simulated decision time (causal indicators, completed bars, next-bar fills).</p>
              </>
            )}
            {tab === "optimize" && (
              <>
                <Field label="Parameter grid (JSON, max 40 combinations)"><textarea rows={3} value={grid} onChange={(e) => setGrid(e.target.value)} className="num text-[12px]" /></Field>
                <Button variant="primary" onClick={runOpt} disabled={act.busy}>{act.busy ? "Optimizing…" : "Optimize on training segment"}</Button>
                <p className="text-[11px] text-mute">Scored on train only; validation shown for honesty; the out-of-sample test segment is never used for selection.</p>
              </>
            )}
            {tab === "versions" && (
              <>
                <Field label="Reason for change"><input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. tighter time stop after review" /></Field>
                <Button onClick={saveVersion} disabled={act.busy}>Save parameters as new draft version</Button>
                <p className="text-[11px] text-mute">Approval requires a completed out-of-sample backtest of that exact version. Active experiments are never modified silently.</p>
              </>
            )}
          </div>
        </Card>
        <div className="xl:col-span-2 flex flex-col gap-3 min-w-0">
          {tab === "optimize" && opt && (
            <Card title={`Optimization: ${opt.configs_tested} configurations`}>
              <p className="text-warn text-[12px] mb-2">{opt.warning}</p>
              <div className="overflow-x-auto"><table className="grid-table"><thead><tr><th>Params</th><th className="text-right">Train trades</th><th className="text-right">Train exp R</th><th className="text-right">Train PF</th><th className="text-right">Val trades</th><th className="text-right">Val exp R</th><th className="text-right">Val PF</th></tr></thead>
                <tbody>{opt.all.map((r: any, i: number) => <tr key={i}><td className="num text-[11px]">{JSON.stringify(r.params)}</td><td className="num text-right">{r.train.trades}</td><td className="num text-right">{fmtNum(r.train.expectancy_r, 3)}</td><td className="num text-right">{fmtNum(r.train.profit_factor)}</td><td className="num text-right">{r.validation.trades}</td><td className="num text-right">{fmtNum(r.validation.expectancy_r, 3)}</td><td className="num text-right">{fmtNum(r.validation.profit_factor)}</td></tr>)}</tbody></table></div>
            </Card>
          )}
          {tab === "versions" ? (
            <Card title="Strategy versions (permanent record)" pad={false}>
              {!versions.data ? <Loading /> : (
                <div className="overflow-x-auto"><table className="grid-table"><thead><tr><th>Strategy</th><th>Version</th><th>Status</th><th>By</th><th>Reason</th><th>Params</th><th>Created</th><th></th></tr></thead>
                  <tbody>{versions.data.map((v) => (
                    <tr key={v.id}><td>{v.strategy_key}</td><td className="num">{v.version}</td><td><Badge color={v.status === "approved" ? "green" : v.status === "retired" ? "gray" : "amber"}>{v.status}</Badge></td><td>{v.created_by}</td>
                      <td className="text-mute max-w-xs truncate" title={v.change_reason}>{v.change_reason}</td><td className="num text-[11px] max-w-xs truncate" title={JSON.stringify(v.params)}>{JSON.stringify(v.params)}</td><td className="text-mute whitespace-nowrap">{fmtTime(v.created_at)}</td>
                      <td className="whitespace-nowrap">{["testing", "approved", "retired"].filter((s) => s !== v.status).map((s) => (
                        <button key={s} className="text-accent mr-2 text-[12px]" onClick={async () => { const r = await act.run(() => post(`/api/strategies/versions/${v.id}/status`, { status: s })); if (r) versions.reload(); }}>{s}</button>
                      ))}</td></tr>
                  ))}</tbody></table></div>
              )}
            </Card>
          ) : (
            <>
              <Card title="Backtest runs" pad={false}>
                {!bts.data ? <Loading /> : bts.data.length === 0 ? <Empty>No backtests yet.</Empty> : (
                  <div className="overflow-x-auto max-h-72"><table className="grid-table"><thead><tr><th>#</th><th>Strategy</th><th>Period</th><th>Scenario</th><th>Status</th><th className="text-right">OOS return</th><th className="text-right">OOS trades</th><th className="text-right">OOS PF</th><th className="text-right">Full DD</th></tr></thead>
                    <tbody>{bts.data.map((b) => (
                      <tr key={b.id} className={`cursor-pointer ${sel === b.id ? "bg-accent/10" : ""}`} onClick={() => setSel(b.id)}>
                        <td className="num">{b.id}</td><td>{b.strategy_key} <span className="text-mute num">v{b.strategy_version}</span></td><td className="num text-[12px]">{b.start} → {b.end}</td><td>{b.scenario || "—"}</td>
                        <td><StatusBadge s={b.status} /></td><td className="text-right"><Pct v={b.segments?.test?.return_pct ?? b.segments?.full?.return_pct} /></td>
                        <td className="num text-right">{b.segments?.test?.trades ?? "—"}</td><td className="num text-right">{fmtNum(b.segments?.test?.profit_factor)}</td><td className="num text-right">{fmtNum(b.segments?.full?.max_drawdown_pct)}%</td>
                      </tr>
                    ))}</tbody></table></div>
                )}
              </Card>
              {sel && <BacktestDetail key={sel} id={sel} />}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
