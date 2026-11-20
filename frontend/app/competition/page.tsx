"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Plus } from "lucide-react";
import { LineChart, toPctSeries } from "@/components/Charts";
import { Button, Card, Empty, ErrorBox, Field, Loading, PageHeader, PaperBadge, Pct, StatusBadge } from "@/components/ui";
import { post } from "@/lib/api";
import { useAction, useApi } from "@/lib/hooks";
import { fmtMoney, fmtNum } from "@/lib/format";

const COLORS = ["#3b82f6", "#22c55e", "#f5a524", "#a855f7", "#14b8a6", "#f05252"];

export default function Competition() {
  const comps = useApi<any[]>("/api/competitions", 30000);
  const strategies = useApi<any[]>("/api/strategies");
  const [sel, setSel] = useState<string | null>(null);
  const [show, setShow] = useState(false);
  const [name, setName] = useState("Season 1");
  const [picked, setPicked] = useState<string[]>(["momentum", "breakout", "mean_reversion", "trend_pullback"]);
  const [capital, setCapital] = useState(10000);
  const act = useAction();
  useEffect(() => { if (!sel && comps.data?.length) setSel(comps.data[0].name); }, [comps.data, sel]);
  const board = comps.data?.find((c) => c.name === sel);
  const series = useMemo(() => (board?.rows || []).map((r: any, i: number) => ({
    name: r.name.split(": ").pop(), color: COLORS[i % COLORS.length],
    points: toPctSeries((r.equity_curve || []).map((p: any) => ({ t: p.ts, v: p.equity }))),
  })), [board]);
  const spy = useMemo(() => {
    const r = board?.rows?.[0];
    return r ? toPctSeries((r.equity_curve || []).map((p: any) => ({ t: p.ts, v: p.benchmark_price }))) : [];
  }, [board]);

  const create = async () => {
    const r = await act.run(() => post("/api/competitions", { name, strategies: picked.map((k) => ({ strategy_key: k })), starting_capital: capital }));
    if (r) { setShow(false); setSel(name); comps.reload(); }
  };

  return (
    <div>
      <PageHeader title="Strategy Competition" subtitle="Independent agents, separate hypothetical portfolios, identical capital, risk limits, universe and evaluation period. Ranked by risk-adjusted score, so taking more risk does not win by itself."
        right={<><PaperBadge /><Button variant="primary" onClick={() => setShow((s) => !s)}><Plus className="w-4 h-4" />New competition</Button></>} />
      {show && (
        <Card title="New competition" className="mb-3">
          <div className="grid sm:grid-cols-3 gap-3">
            <Field label="Name"><input value={name} onChange={(e) => setName(e.target.value)} /></Field>
            <Field label="Capital per agent ($)"><input type="number" value={capital} onChange={(e) => setCapital(Number(e.target.value))} /></Field>
          </div>
          <div className="flex flex-wrap gap-2 mt-3">{(strategies.data || []).filter((s) => s.key !== "custom").map((s) => (
            <label key={s.key} className={`px-2 py-1 rounded border cursor-pointer ${picked.includes(s.key) ? "border-accent bg-accent/10" : "border-line"}`}>
              <input type="checkbox" className="mr-1" checked={picked.includes(s.key)} onChange={() => setPicked((p) => (p.includes(s.key) ? p.filter((x) => x !== s.key) : [...p, s.key]))} />{s.name}
            </label>
          ))}</div>
          <ErrorBox error={act.error} />
          <Button variant="primary" className="mt-3" onClick={create} disabled={act.busy || picked.length < 2}>Create & start</Button>
        </Card>
      )}
      {comps.error ? <ErrorBox error={comps.error} /> : !comps.data ? <Loading /> : comps.data.length === 0 ? <Card><Empty>No competitions yet.</Empty></Card> : (
        <>
          <div className="flex gap-2 mb-3 flex-wrap">{comps.data.map((c) => (
            <button key={c.name} onClick={() => setSel(c.name)} className={`px-3 py-1 rounded-md border ${sel === c.name ? "border-accent bg-accent/10" : "border-line"}`}>{c.name}</button>
          ))}</div>
          {board && (
            <>
              <Card title="Leaderboard" pad={false} right={<span className="text-[11px] text-mute">{board.ranking}</span>}>
                <div className="overflow-x-auto">
                  <table className="grid-table">
                    <thead><tr><th>#</th><th>Agent</th><th>Status</th><th className="text-right">Equity</th><th className="text-right">Return</th><th className="text-right">Max DD</th><th className="text-right">Sharpe</th><th className="text-right">Win rate</th><th className="text-right">Trades</th><th className="text-right">PF</th><th className="text-right">Score</th><th>Sample</th></tr></thead>
                    <tbody>{board.rows.map((r: any, i: number) => (
                      <tr key={r.experiment_id}>
                        <td className="num">{i + 1}</td>
                        <td><Link href={`/paper`} className="text-accent">{r.name}</Link><div className="text-[11px] text-mute">{r.strategy_key} v{r.strategy_version}</div></td>
                        <td><StatusBadge s={r.status} /></td>
                        <td className="num text-right">{fmtMoney(r.equity)}</td><td className="text-right"><Pct v={r.total_return_pct} /></td>
                        <td className="num text-right text-down">{fmtNum(r.max_drawdown_pct)}%</td><td className="num text-right">{fmtNum(r.sharpe)}</td>
                        <td className="num text-right">{r.win_rate != null ? `${fmtNum(r.win_rate, 1)}%` : "—"}</td><td className="num text-right">{r.trades}</td>
                        <td className="num text-right">{fmtNum(r.profit_factor)}</td><td className="num text-right font-semibold" title={r.score.method}>{fmtNum(r.score.score, 3)}</td>
                        <td className="text-[11px] text-mute">{r.sample_warning ? "insufficient" : `conf ${r.score.sample_confidence}`}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
                <p className="text-[11px] text-mute p-3">Score = {board.rows[0]?.score.method}. {board.identical_rules} Benchmark: SPY over the same snapshots.</p>
              </Card>
              <Card title="Equity curves (% change) vs SPY" className="mt-3">
                {series.every((s: any) => s.points.length < 2) ? <Empty>Curves appear after the first equity snapshots.</Empty> :
                  <LineChart percent series={[...series, { name: "SPY", color: "#7f8c9b", points: spy }]} height={320} />}
              </Card>
            </>
          )}
        </>
      )}
    </div>
  );
}
