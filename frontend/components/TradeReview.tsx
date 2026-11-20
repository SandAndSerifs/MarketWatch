"use client";
import Link from "next/link";
import { useMemo, useState } from "react";
import { MessageSquare } from "lucide-react";
import { CandleChart, type Marker, type PriceLine } from "./Charts";
import DecisionRecord from "./DecisionRecord";
import { Badge, Button, Card, Empty, ErrorBox, KV, Loading, PaperBadge, Stat } from "./ui";
import { post } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { fmtMoney, fmtNum, fmtTime, tone } from "@/lib/format";

export default function TradeReview({ id }: { id: number }) {
  const d = useApi<any>(`/api/trades/${id}`);
  const [answers, setAnswers] = useState<Record<string, any>>({});
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const markers = useMemo<Marker[]>(() => {
    if (!d.data) return [];
    const t = d.data.trade;
    const m: Marker[] = [{ time: t.entry_ts, position: "belowBar", color: "#22c55e", shape: "arrowUp", text: `BUY ${fmtNum(t.entry_price)}` }];
    if (t.exit_ts) m.push({ time: t.exit_ts, position: "aboveBar", color: "#f05252", shape: "arrowDown", text: `SELL ${fmtNum(t.exit_price)}` });
    // daily chart: snap marker times to the bar's date (00:00 ET)
    const days = new Map<string, string>((d.data.chart_bars || []).map((b: any) => [new Date(b.t).toLocaleDateString("en-CA", { timeZone: "America/New_York" }), b.t]));
    return m.map((x) => {
      const local = new Date(x.time).toLocaleDateString("en-CA", { timeZone: "America/New_York" });
      const match = [...days.keys()].find((k) => k >= local);
      return { ...x, time: (match ? days.get(match) : x.time) as string };
    });
  }, [d.data]);
  const lines = useMemo<PriceLine[]>(() => {
    if (!d.data) return [];
    const t = d.data.trade;
    const l: PriceLine[] = [{ price: t.stop_initial, color: "#f05252", title: "initial stop" }];
    if (t.target_initial) l.push({ price: t.target_initial, color: "#22c55e", title: "target" });
    if (t.stop_current !== t.stop_initial) l.push({ price: t.stop_current, color: "#f5a524", title: "final stop" });
    return l;
  }, [d.data]);

  const ask = async (key: string, question: string) => {
    setBusy(key); setErr(null);
    try {
      const r = await post(`/api/trades/${id}/ask`, { question });
      setAnswers((a) => ({ ...a, [key]: r }));
    } catch (e) { setErr((e as Error).message); } finally { setBusy(null); }
  };

  if (d.error) return <ErrorBox error={d.error} />;
  if (!d.data) return <Loading />;
  const { trade: t, decision, setup_decision, orders, fills, execution_costs, experiment } = d.data;
  const rec = decision?.record;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-semibold">Trade #{t.id}: {t.symbol}</h1><PaperBadge />
        <Badge color={t.status === "open" ? "blue" : (t.net_pnl ?? 0) > 0 ? "green" : "red"}>{t.status}</Badge>
        <span className="text-mute">{experiment?.name} · {t.strategy_key} v{t.strategy_version}</span>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        <Stat label="Entry" value={fmtNum(t.entry_price)} sub={fmtTime(t.entry_ts)} />
        <Stat label="Exit" value={fmtNum(t.exit_price)} sub={fmtTime(t.exit_ts)} />
        <Stat label="Position size" value={`${t.qty} sh`} sub={fmtMoney(t.qty * t.entry_price)} />
        <Stat label="Initial stop / target" value={`${fmtNum(t.stop_initial)} / ${fmtNum(t.target_initial)}`} />
        <Stat label="Net P&L (hypothetical)" value={fmtMoney(t.net_pnl)} valueClass={tone(t.net_pnl)} sub={`gross ${fmtMoney(t.gross_pnl)}`} />
        <Stat label="R multiple" value={t.r_multiple != null ? `${fmtNum(t.r_multiple)}R` : "—"} valueClass={tone(t.r_multiple)} />
        <Stat label="Execution costs" value={fmtMoney(t.fees)} sub={`slippage vs ref ${fmtMoney(execution_costs.slippage_vs_reference)}`} />
        <Stat label="MAE / MFE" value={`${fmtNum(t.mae)} / ${fmtNum(t.mfe)}`} />
      </div>
      <Card title="Price chart with trade markers (daily)" pad={false}>
        {d.data.chart_error ? <div className="p-3"><ErrorBox error={d.data.chart_error} compact /></div> : d.data.chart_bars?.length ? <CandleChart bars={d.data.chart_bars} markers={markers} priceLines={lines} height={360} /> : <Empty>No chart data.</Empty>}
      </Card>

      <div className="grid grid-cols-1 xl:grid-cols-5 gap-3">
        <div className="xl:col-span-3 flex flex-col gap-3 min-w-0">
          <Card title="Exit">
            <KV rows={[["Reason for exiting", t.exit_reason || (t.status === "open" ? "Still open" : "—")], ["Exit rule", t.review?.exit_rule || "—"], ["Current stop", fmtNum(t.stop_current)], ["Max hold", t.max_hold_days ? `${t.max_hold_days} sessions` : "—"]]} />
          </Card>
          <Card title="Original decision record (the only source used for explanations)">
            {rec ? <DecisionRecord record={rec} review={t.review} /> : <Empty>No decision record attached.</Empty>}
          </Card>
          {setup_decision && (
            <details className="bg-panel border border-line rounded-lg p-3">
              <summary className="cursor-pointer text-mute">Setup decision recorded when the plan was armed (#{setup_decision.id}, {fmtTime(setup_decision.ts)})</summary>
              <div className="mt-3"><DecisionRecord record={setup_decision.record} /></div>
            </details>
          )}
        </div>
        <div className="xl:col-span-2 flex flex-col gap-3 min-w-0">
          <Card title="Ask about this trade">
            <p className="text-[12px] text-mute mb-2">Answers come from the recorded data above. Without an AI key, standard questions are answered directly from the record.</p>
            <div className="flex flex-col gap-2">
              {Object.entries(d.data.standard_questions as Record<string, string>).map(([key, question]) => (
                <div key={key} className="border border-line rounded-md">
                  <button className="w-full flex items-center justify-between gap-2 px-3 py-2 text-left hover:bg-panel2" onClick={() => setAnswers((a) => ({ ...a, [key]: a[key] || { answer: d.data.standard_answers[key], source: "record" } }))}>
                    <span>{question}</span><MessageSquare className="w-4 h-4 text-mute shrink-0" />
                  </button>
                  {answers[key] && (
                    <div className="px-3 pb-3 text-[13px] whitespace-pre-line">
                      {answers[key].answer}
                      <div className="flex items-center gap-2 mt-2">
                        <Badge color={answers[key].source === "ai" ? "blue" : "gray"}>{answers[key].source === "ai" ? `AI (${answers[key].model})` : "from record"}</Badge>
                        {answers[key].source !== "ai" && <button className="text-accent text-[12px]" disabled={busy === key} onClick={() => ask(key, question)}>{busy === key ? "Asking AI…" : "Ask AI for a fuller explanation"}</button>}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
            <form className="flex gap-2 mt-3" onSubmit={(e) => { e.preventDefault(); if (q.trim()) ask(`custom-${Date.now()}`, q); }}>
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask anything about this trade…" className="flex-1" />
              <Button type="submit" variant="primary" disabled={!!busy}>Ask</Button>
            </form>
            {err && <div className="mt-2"><ErrorBox error={err} compact /></div>}
            {Object.entries(answers).filter(([k]) => k.startsWith("custom-")).map(([k, a]) => (
              <div key={k} className="mt-3 border-t border-line pt-2 text-[13px] whitespace-pre-line">{a.answer}<div className="mt-1"><Badge color={a.source === "ai" ? "blue" : "gray"}>{a.source}</Badge></div></div>
            ))}
          </Card>
          <Card title="Simulated orders & fills" pad={false}>
            <table className="grid-table"><thead><tr><th>Order</th><th>Side</th><th className="text-right">Qty</th><th className="text-right">Price</th><th className="text-right">Ref</th><th className="text-right">Fees</th><th>Time</th></tr></thead>
              <tbody>{fills.map((f: any, i: number) => (
                <tr key={i} title={JSON.stringify(f.model)}><td className="num text-[11px] text-mute">{f.order}</td><td className={f.side === "buy" ? "text-up" : "text-down"}>{f.side}</td>
                  <td className="num text-right">{f.qty}</td><td className="num text-right">{fmtNum(f.price, 4)}</td><td className="num text-right text-mute">{fmtNum(f.reference_price, 4)}</td>
                  <td className="num text-right">{fmtNum(f.fees)}</td><td className="text-mute whitespace-nowrap">{fmtTime(f.ts)}</td></tr>
              ))}</tbody></table>
            <div className="p-3 text-[11px] text-mute">{orders.length} orders. Hover a fill for the execution model (spread, slippage, latency).</div>
          </Card>
          <Link href="/trades" className="text-accent text-[12px]">← All trades</Link>
        </div>
      </div>
    </div>
  );
}
