"use client";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import DecisionRecord from "@/components/DecisionRecord";
import TradeReview from "@/components/TradeReview";
import { Badge, Card, Empty, ErrorBox, Loading, PageHeader, PaperBadge } from "@/components/ui";
import { useApi } from "@/lib/hooks";
import { fmtMoney, fmtTime, tone } from "@/lib/format";

function DecisionView({ id }: { id: string }) {
  const d = useApi<any>(`/api/decisions/${id}`);
  if (d.error) return <ErrorBox error={d.error} />;
  if (!d.data) return <Loading />;
  return (
    <Card title={`Decision #${d.data.id} · ${d.data.symbol} · ${d.data.context} · ${fmtTime(d.data.ts)}`}>
      <DecisionRecord record={d.data.record} />
    </Card>
  );
}

function ReviewInner() {
  const params = useSearchParams();
  const decision = params.get("decision");
  const trades = useApi<any[]>("/api/trades?limit=200", 60000);
  const [sel, setSel] = useState<number | null>(null);
  useEffect(() => { if (!sel && trades.data?.length) setSel(trades.data[0].id); }, [trades.data, sel]);
  if (decision) return <DecisionView id={decision} />;
  return (
    <div className="grid grid-cols-1 xl:grid-cols-5 gap-3">
      <Card title="Trades to review" pad={false} className="xl:col-span-1">
        {trades.error ? <div className="p-3"><ErrorBox error={trades.error} /></div> : !trades.data ? <Loading /> : trades.data.length === 0 ? <Empty>No simulated trades yet.</Empty> : (
          <ul className="divide-y divide-line max-h-[80vh] overflow-y-auto">{trades.data.map((t) => (
            <li key={t.id} onClick={() => setSel(t.id)} className={`px-3 py-2 cursor-pointer ${sel === t.id ? "bg-accent/10" : "hover:bg-panel2"}`}>
              <div className="flex justify-between"><b>{t.symbol}</b><span className={`num ${tone(t.net_pnl)}`}>{t.status === "open" ? <Badge color="blue">open</Badge> : fmtMoney(t.net_pnl)}</span></div>
              <div className="text-[11px] text-mute">#{t.id} · {t.strategy_key} · {fmtTime(t.entry_ts)}</div>
            </li>
          ))}</ul>
        )}
      </Card>
      <div className="xl:col-span-4 min-w-0">{sel ? <TradeReview key={sel} id={sel} /> : <Empty>Select a trade.</Empty>}</div>
    </div>
  );
}

export default function Review() {
  return (
    <div>
      <PageHeader title="Trade Review" subtitle="Audit every trigger, rule, exit condition and post-trade assessment. Explanations are built only from what was recorded at decision time." right={<PaperBadge />} />
      <Suspense fallback={<Loading />}><ReviewInner /></Suspense>
    </div>
  );
}
