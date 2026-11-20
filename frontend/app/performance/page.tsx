"use client";
import { useEffect, useState } from "react";
import { LineChart, toPctSeries } from "@/components/Charts";
import { Badge, Card, Empty, ErrorBox, Loading, PageHeader, PaperBadge, Pct, Stat, Tabs } from "@/components/ui";
import { useApi } from "@/lib/hooks";
import { fmtMoney, fmtNum, tone } from "@/lib/format";

export default function Performance() {
  const exps = useApi<any[]>("/api/experiments?include_archived=true", 60000);
  const [sel, setSel] = useState<number | null>(null);
  const [period, setPeriod] = useState("weekly");
  useEffect(() => { if (!sel && exps.data?.length) setSel(exps.data[0].id); }, [exps.data, sel]);
  const ex = useApi<any>(sel ? `/api/experiments/${sel}` : null, 60000);
  const rep = useApi<any>(sel ? `/api/reports/performance/${sel}?period=${period}` : null);
  const review = useApi<any>("/api/reports/strategy-review?days=7", 300000);
  const e = ex.data;
  const s = e?.stats;
  const ts = s?.trade_stats;

  return (
    <div>
      <PageHeader title="Performance Analytics" subtitle="Hypothetical results only, always compared with SPY over matching periods. Small samples are flagged; no claim of profitability is made without measurable evidence." right={<PaperBadge />} />
      {exps.error && <ErrorBox error={exps.error} />}
      <div className="flex gap-2 mb-3 flex-wrap">{(exps.data || []).map((x) => (
        <button key={x.id} onClick={() => setSel(x.id)} className={`px-3 py-1 rounded-md border ${sel === x.id ? "border-accent bg-accent/10" : "border-line"}`}>{x.name}{x.archived ? " (archived)" : ""}</button>
      ))}</div>
      {!sel ? <Card><Empty>No experiments yet.</Empty></Card> : !e ? <Loading /> : (
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-2">
            <Stat label="Starting balance" value={fmtMoney(e.starting_capital, 0)} />
            <Stat label="Current equity" value={fmtMoney(e.equity)} valueClass={tone(e.equity - e.starting_capital)} />
            <Stat label="Available cash" value={fmtMoney(e.cash)} />
            <Stat label="Realized / unrealized" value={<span><span className={tone(e.realized_pnl)}>{fmtMoney(e.realized_pnl)}</span> / <span className={tone(e.unrealized_pnl)}>{fmtMoney(e.unrealized_pnl)}</span></span>} />
            <Stat label="Cumulative return" value={<Pct v={s.total_return_pct} />} sub={s.benchmark ? `SPY ${fmtNum(s.benchmark.return_pct)}% · excess ${fmtNum(s.benchmark.excess_return_pct)}%` : "SPY: needs snapshots"} />
            <Stat label="Max drawdown" value={`${fmtNum(s.max_drawdown_pct)}%`} sub={s.benchmark ? `SPY ${fmtNum(s.benchmark.max_drawdown_pct)}%` : undefined} valueClass="text-down" />
            <Stat label="Sharpe / Sortino" value={`${fmtNum(s.sharpe)} / ${fmtNum(s.sortino)}`} />
            <Stat label="Win rate" value={ts.win_rate != null ? `${fmtNum(ts.win_rate, 1)}%` : "—"} sub={ts.win_rate_ci95 ? `95% CI ${ts.win_rate_ci95.join("–")}%` : undefined} />
            <Stat label="Avg win / loss" value={`${fmtMoney(ts.avg_win)} / ${fmtMoney(ts.avg_loss)}`} />
            <Stat label="Largest win / loss" value={<span><span className="text-up">{fmtMoney(ts.largest_win)}</span> / <span className="text-down">{fmtMoney(ts.largest_loss)}</span></span>} />
            <Stat label="Profit factor / expectancy" value={`${fmtNum(ts.profit_factor)} / ${ts.expectancy_r != null ? fmtNum(ts.expectancy_r) + "R" : "—"}`} />
            <Stat label="Completed trades" value={ts.trades} sub={ts.avg_hold_days != null ? `avg hold ${fmtNum(ts.avg_hold_days, 1)} d` : undefined} />
          </div>
          {ts.sample_warning && <p className="text-warn text-[12px]">{ts.sample_warning}</p>}
          <Card title="Equity curve vs SPY (% change)">
            {(e.equity_curve || []).length < 2 ? <Empty>Needs at least two equity snapshots.</Empty> : (
              <LineChart percent series={[
                { name: e.name, color: "#3b82f6", points: toPctSeries(e.equity_curve.map((p: any) => ({ t: p.ts, v: p.equity }))) },
                { name: "SPY", color: "#7f8c9b", points: toPctSeries(e.equity_curve.map((p: any) => ({ t: p.ts, v: p.benchmark_price }))) },
              ]} />
            )}
          </Card>
          <Card title="Periodic reports" pad={false}>
            <div className="px-3 pt-2"><Tabs value={period} onChange={setPeriod} tabs={[{ key: "daily", label: "Daily" }, { key: "weekly", label: "Weekly" }, { key: "monthly", label: "Monthly" }]} /></div>
            {rep.error ? <div className="p-3"><ErrorBox error={rep.error} /></div> : !rep.data ? <Loading /> : rep.data.rows.length === 0 ? <Empty>No data yet.</Empty> : (
              <div className="overflow-x-auto"><table className="grid-table"><thead><tr><th>Period</th><th className="text-right">Start equity</th><th className="text-right">End equity</th><th className="text-right">Return</th><th className="text-right">SPY</th><th className="text-right">Closed trades</th><th className="text-right">Win %</th><th className="text-right">Net P&L</th><th className="text-right">Exp. R</th></tr></thead>
                <tbody>{rep.data.rows.map((r: any) => (
                  <tr key={r.period}><td className="num">{r.period}</td><td className="num text-right">{fmtMoney(r.start_equity)}</td><td className="num text-right">{fmtMoney(r.end_equity)}</td>
                    <td className="text-right"><Pct v={r.return_pct} /></td><td className="text-right"><Pct v={r.spy_return_pct} /></td><td className="num text-right">{r.trades_closed}</td>
                    <td className="num text-right">{fmtNum(r.win_rate, 1)}</td><td className={`num text-right ${tone(r.net_pnl)}`}>{fmtMoney(r.net_pnl)}</td><td className="num text-right">{fmtNum(r.expectancy_r, 3)}</td></tr>
                ))}</tbody></table></div>
            )}
          </Card>
        </div>
      )}
      <Card title="Weekly strategy review (continuous learning)" className="mt-3">
        {review.error ? <ErrorBox error={review.error} /> : !review.data ? <Loading /> : (
          <>
            <p className="text-[12px] text-mute mb-3">{review.data.policy}</p>
            {review.data.strategies.length === 0 ? <Empty>No closed trades yet.</Empty> : review.data.strategies.map((r: any) => (
              <div key={r.strategy + r.version} className="border border-line rounded-md p-3 mb-2">
                <div className="flex flex-wrap gap-2 items-center"><b>{r.strategy}</b><span className="num text-mute">v{r.version}</span>
                  <Badge>all-time {r.all_time.trades} trades</Badge><Badge>win {fmtNum(r.all_time.win_rate, 1)}%</Badge><Badge>exp {fmtNum(r.all_time.expectancy_r, 3)}R</Badge>
                  <Badge color={r.plan_deviations ? "amber" : "green"}>{r.plan_deviations} plan deviations</Badge></div>
                <div className="text-[12px] text-mute mt-1">Exit rules: {Object.entries(r.exit_rules).map(([k, v]) => `${k} ${v}`).join(" · ")}</div>
                {r.objection_outcomes.length > 0 && (
                  <table className="grid-table mt-2"><thead><tr><th>Objection raised at entry</th><th className="text-right">Trades</th><th className="text-right">Avg R with</th><th className="text-right">Avg R without</th><th>Assessment</th></tr></thead>
                    <tbody>{r.objection_outcomes.map((o: any) => <tr key={o.objection}><td>{o.objection}</td><td className="num text-right">{o.trades_with}</td><td className="num text-right">{fmtNum(o.avg_r_with, 3)}</td><td className="num text-right">{fmtNum(o.avg_r_without, 3)}</td><td className="text-mute">{o.assessment}</td></tr>)}</tbody></table>
                )}
              </div>
            ))}
          </>
        )}
      </Card>
    </div>
  );
}
