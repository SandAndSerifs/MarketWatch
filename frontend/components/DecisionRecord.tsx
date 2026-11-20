"use client";
import { CheckCircle2, ShieldAlert, XCircle } from "lucide-react";
import { Badge, CategoryBadge, KV, SeverityBadge } from "./ui";
import { fmtMoney, fmtNum, fmtTime } from "@/lib/format";

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <div className="border border-line rounded-md">
      <div className="px-3 py-1.5 border-b border-line bg-panel2 flex items-center gap-2">
        <span className="num text-[11px] text-accent">STEP {n}</span>
        <span className="font-semibold text-[13px]">{title}</span>
      </div>
      <div className="p-3 text-[13px]">{children}</div>
    </div>
  );
}

export default function DecisionRecord({ record, review }: { record: any; review?: any }) {
  if (!record) return <div className="text-mute">No decision record.</div>;
  const st = record.steps;
  const r6 = st["6_risk"];
  const verdict = r6.verdict;
  const t = st["2_stock_analysis"].technicals;
  const reg = st["1_market_conditions"].regime;
  const quant = record.roles?.quant_analyst;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2 text-[12px] text-mute">
        <CategoryBadge c={st["7_decision"].category} />
        <span>{record.symbol} · {record.strategy.name} v{record.strategy.version}</span>
        <span>· evaluated {fmtTime(record.evaluated_at)}</span>
        {record.data?.quality && <Badge color="sky" title={(record.data.quality.caveats || []).join("\n")}>{record.data.quality.provider}: {record.data.quality.label}</Badge>}
        {record.data?.verified_price != null && <span>· verified price <span className="num text-ink">{fmtNum(record.data.verified_price)}</span> @ {fmtTime(record.data.price_ts)}</span>}
        <span>· daily bars through {fmtTime(record.data?.daily_bars_through)}</span>
      </div>

      <Step n={1} title="Market conditions">
        <p><b>{reg?.label?.replace("_", " ")}</b> — {reg?.description}</p>
        <div className="text-mute mt-1">SPY {fmtNum(reg?.spy_close)} · above 50d: {String(reg?.spy_above_50)} · above 200d: {String(reg?.spy_above_200)} · 20d realized vol {fmtNum(reg?.realized_vol20)}% · drawdown from 52w high {fmtNum(reg?.drawdown_from_52w_high_pct)}%</div>
        {st["1_market_conditions"].sector && <div className="text-mute">Sector {st["1_market_conditions"].sector.symbol}: rank {st["1_market_conditions"].sector.rank}, 20d RS vs SPY {fmtNum(st["1_market_conditions"].sector.rel_strength_vs_spy)}%</div>}
        {st["1_market_conditions"].upcoming_events?.length > 0 && (
          <ul className="mt-1 text-mute list-disc pl-5">{st["1_market_conditions"].upcoming_events.slice(0, 5).map((e: any, i: number) => <li key={i}>{e.date} {e.time_et || ""} {e.name} {e.symbol !== "*" ? e.symbol : ""} ({e.source})</li>)}</ul>
        )}
      </Step>

      <Step n={2} title="Stock analysis">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-1 num text-[12px]">
          {[["Close", t.close], ["Chg %", t.change_pct], ["SMA20", t.sma20], ["SMA50", t.sma50], ["SMA200", t.sma200], ["EMA20", t.ema20],
            ["RSI14", t.rsi14], ["RSI2", t.rsi2], ["MACD hist", t.macd_hist], ["ATR14", t.atr14], ["ATR %", t.atr_pct], ["ADX14", t.adx14],
            ["RVOL20", t.rvol20], ["ROC20 %", t.roc20], ["ROC126 %", t.roc126], ["From 52w high %", t.pct_from_52w_high]].map(([k, v]) => (
            <div key={k as string} className="flex justify-between gap-2"><span className="text-mute">{k}</span><span>{v ?? "—"}</span></div>
          ))}
        </div>
        <div className="text-mute mt-2">Trend: <b className="text-ink">{t.trend}</b> · Liquidity: ${fmtNum((st["2_stock_analysis"].liquidity.avg_dollar_volume20 || 0) / 1e6, 1)}M/day avg</div>
        {(t.resistance?.length > 0 || t.support?.length > 0) && (
          <div className="text-mute">Support: {(t.support || []).map((l: any) => l.price).join(", ") || "—"} · Resistance: {(t.resistance || []).map((l: any) => l.price).join(", ") || "—"}</div>
        )}
        {st["2_stock_analysis"].news?.length > 0 && (
          <ul className="mt-1 list-disc pl-5">{st["2_stock_analysis"].news.map((n: any) => <li key={n.id}><a className="text-accent" href={n.url} target="_blank" rel="noreferrer">{n.headline}</a> <span className="text-mute">({n.source}, {fmtTime(n.created_at)})</span></li>)}</ul>
        )}
      </Step>

      <Step n={3} title="Trading thesis">
        <p>{st["3_thesis"].thesis}</p>
        <p className="text-mute mt-1">{st["3_thesis"].strategy_description}</p>
      </Step>

      <Step n={4} title="Confirming evidence">
        <ul className="list-disc pl-5">{st["4_evidence"].supporting.map((e: string, i: number) => <li key={i}>{e}</li>)}</ul>
      </Step>

      <Step n={5} title="Challenge the trade (argue against it)">
        {st["5_challenge"].objections.length === 0 ? <p className="text-mute">No objections raised.</p> : (
          <ul className="flex flex-col gap-1">{st["5_challenge"].objections.map((o: any, i: number) => (
            <li key={i} className="flex gap-2 items-start"><SeverityBadge s={o.severity} /><span><b>{o.issue}:</b> {o.detail}</span></li>
          ))}</ul>
        )}
        <div className="mt-2">
          <div className="text-[11px] uppercase text-mute mb-1">What would prove this wrong (logged before acting)</div>
          <ul className="list-disc pl-5">{st["5_challenge"].what_would_prove_it_wrong.map((f: string, i: number) => <li key={i}>{f}</li>)}</ul>
        </div>
        {quant && <div className="mt-2 text-mute"><b className="text-ink">Quant Analyst:</b> {quant.status} — {quant.note}{quant.forward_paper?.closed_trades ? ` · forward paper trades: ${quant.forward_paper.closed_trades}` : ""}</div>}
      </Step>

      <Step n={6} title="Risk assessment (Risk Manager)">
        <div className="grid sm:grid-cols-2 gap-4">
          <KV rows={[
            ["Entry", `${r6.entry_type.replace("_", " ")} @ ${fmtNum(r6.entry)}`], ["Stop / invalidation", fmtNum(r6.stop)],
            ["Target", fmtNum(r6.target)], ["Risk per share", fmtNum(r6.risk_per_share)], ["Reward : risk", fmtNum(r6.reward_risk)],
            ["Time stop", `${r6.time_stop_days} sessions`], ["Holding", r6.holding],
            ["Size", verdict ? `${verdict.qty} sh · ${fmtMoney(verdict.notional)}` : "—"],
            ["Risk at stop", verdict ? fmtMoney(verdict.risk_amount) : "—"],
            ["Binding limit", verdict?.sizing?.binding_constraint || "—"],
          ]} />
          {verdict && (
            <ul className="flex flex-col gap-0.5 text-[12px]">{verdict.checks.map((c: any, i: number) => (
              <li key={i} className="flex gap-1.5 items-start">
                {c.passed ? <CheckCircle2 className="w-3.5 h-3.5 text-up mt-0.5 shrink-0" /> : c.blocking ? <XCircle className="w-3.5 h-3.5 text-down mt-0.5 shrink-0" /> : <ShieldAlert className="w-3.5 h-3.5 text-warn mt-0.5 shrink-0" />}
                <span><span className="text-mute">{c.rule}:</span> {c.detail}</span>
              </li>
            ))}</ul>
          )}
        </div>
      </Step>

      <Step n={7} title="Decision">
        <div className="flex items-center gap-2"><CategoryBadge c={st["7_decision"].category} /><span>{st["7_decision"].rationale}</span></div>
        {st["7_decision"].timing_gates?.length > 0 && <div className="text-mute mt-1">Timing gates re-checked at trigger: {st["7_decision"].timing_gates.join("; ")}</div>}
        {record.trigger && <div className="text-mute mt-1">Triggered {fmtTime(record.trigger.triggered_at)} at live price {fmtNum(record.trigger.live_price)} (armed trigger {fmtNum(record.trigger.trigger_price)}; setup still valid on latest bar: {String(record.trigger.setup_still_valid_on_latest_bar)}).</div>}
      </Step>

      <Step n={8} title="Post-trade evaluation">
        {!review ? <p className="text-mute">Written automatically when the position closes.</p> : (
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap gap-2 items-center">
              <Badge color={review.outcome === "win" ? "green" : review.outcome === "loss" ? "red" : "gray"}>{review.outcome}</Badge>
              <Badge color={review.decision_quality === "Plan followed" ? "green" : "amber"}>{review.decision_quality}</Badge>
              <span className="num">{review.r_multiple ?? "—"}R · net {fmtMoney(review.net_pnl)} · MAE {review.mae_r ?? "—"}R · MFE {review.mfe_r ?? "—"}R</span>
            </div>
            <div>{review.thesis_status} (exit rule: {review.exit_rule})</div>
            <ul className="list-disc pl-5">{review.process_checks.map((c: any, i: number) => <li key={i}>{c.ok ? "✓" : "✗"} {c.rule} — {c.detail}</li>)}</ul>
            <div><div className="text-[11px] uppercase text-mute">Lessons</div><ul className="list-disc pl-5">{review.lessons.map((l: string, i: number) => <li key={i}>{l}</li>)}</ul></div>
            <p className="text-mute text-[12px]">{review.caveat}</p>
          </div>
        )}
      </Step>
    </div>
  );
}
