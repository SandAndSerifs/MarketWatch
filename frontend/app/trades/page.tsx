"use client";
import Link from "next/link";
import { useState } from "react";
import { Badge, Card, Empty, ErrorBox, Loading, PageHeader, PaperBadge } from "@/components/ui";
import { useApi } from "@/lib/hooks";
import { fmtMoney, fmtNum, fmtTime, tone } from "@/lib/format";

export default function Trades() {
  const [status, setStatus] = useState("");
  const [exp, setExp] = useState("");
  const [sym, setSym] = useState("");
  const exps = useApi<any[]>("/api/experiments?include_archived=true");
  const trades = useApi<any[]>(`/api/trades?limit=500${status ? `&status=${status}` : ""}${exp ? `&experiment_id=${exp}` : ""}${sym ? `&symbol=${sym}` : ""}`, 30000);
  return (
    <div>
      <PageHeader title="Trade History" subtitle="Every simulated trade with its original rationale. Click Review to audit triggers, rules, exits and the post-trade assessment." right={<PaperBadge />} />
      <Card pad={false} right={
        <div className="flex gap-2">
          <select value={exp} onChange={(e) => setExp(e.target.value)}><option value="">All experiments</option>{(exps.data || []).map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}</select>
          <select value={status} onChange={(e) => setStatus(e.target.value)}><option value="">Open & closed</option><option value="open">Open</option><option value="closed">Closed</option></select>
          <input value={sym} onChange={(e) => setSym(e.target.value.toUpperCase())} placeholder="Symbol" className="w-24" />
        </div>
      } title="Simulated trades">
        {trades.error ? <div className="p-3"><ErrorBox error={trades.error} /></div> : !trades.data ? <Loading /> : trades.data.length === 0 ? <Empty>No trades yet.</Empty> : (
          <div className="overflow-x-auto">
            <table className="grid-table">
              <thead><tr><th>#</th><th>Experiment</th><th>Symbol</th><th>Strategy</th><th>Status</th><th>Entry</th><th className="text-right">Entry px</th><th>Exit</th><th className="text-right">Exit px</th><th className="text-right">Qty</th><th className="text-right">Net P&L</th><th className="text-right">R</th><th>Exit reason</th><th>Process</th><th></th></tr></thead>
              <tbody>{trades.data.map((t) => (
                <tr key={t.id}>
                  <td className="num">{t.id}</td><td className="max-w-[160px] truncate">{t.experiment_name}</td>
                  <td><Link className="text-accent" href={`/analysis/${t.symbol}`}>{t.symbol}</Link></td><td>{t.strategy_key}</td>
                  <td><Badge color={t.status === "open" ? "blue" : "gray"}>{t.status}</Badge></td>
                  <td className="text-mute whitespace-nowrap">{fmtTime(t.entry_ts)}</td><td className="num text-right">{fmtNum(t.entry_price)}</td>
                  <td className="text-mute whitespace-nowrap">{fmtTime(t.exit_ts)}</td><td className="num text-right">{fmtNum(t.exit_price)}</td>
                  <td className="num text-right">{t.qty}</td><td className={`num text-right ${tone(t.net_pnl)}`}>{fmtMoney(t.net_pnl)}</td>
                  <td className="num text-right">{fmtNum(t.r_multiple)}</td><td className="text-mute max-w-[200px] truncate" title={t.exit_reason}>{t.exit_reason || "—"}</td>
                  <td>{t.review ? <Badge color={t.review.decision_quality === "Plan followed" ? "green" : "amber"}>{t.review.decision_quality}</Badge> : "—"}</td>
                  <td><Link href={`/trades/${t.id}`} className="px-2 py-0.5 rounded bg-accent/20 text-accent whitespace-nowrap">Review</Link></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
