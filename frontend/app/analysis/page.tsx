"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Card, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";

export default function AnalysisIndex() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [res, setRes] = useState<any[]>([]);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (!q) { setRes([]); return; }
    const id = setTimeout(async () => {
      try { setRes(await api(`/api/market/search?q=${encodeURIComponent(q)}`)); setErr(null); } catch (e) { setErr((e as Error).message); }
    }, 300);
    return () => clearTimeout(id);
  }, [q]);
  return (
    <div>
      <PageHeader title="Stock Analysis" subtitle="Charts, technicals, support/resistance, events, news and every strategy's checklist for one symbol." />
      <Card>
        <form onSubmit={(e) => { e.preventDefault(); if (q) router.push(`/analysis/${q.toUpperCase()}`); }}>
          <input autoFocus value={q} onChange={(e) => setQ(e.target.value.toUpperCase())} placeholder="Search symbol or company…" className="w-full text-base py-2" />
        </form>
        {err && <p className="text-warn mt-2 text-[12px]">{err} — you can still type an exact symbol and press Enter.</p>}
        <div className="mt-2 flex flex-col">
          {res.map((r) => (
            <button key={r.symbol} onClick={() => router.push(`/analysis/${r.symbol}`)} className="text-left px-2 py-1.5 hover:bg-panel2 rounded flex gap-3">
              <b className="w-16">{r.symbol}</b><span className="text-mute">{r.name}</span><span className="ml-auto text-[11px] text-mute">{r.exchange}</span>
            </button>
          ))}
        </div>
        <div className="flex flex-wrap gap-2 mt-3">{["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "TSLA", "META", "JPM"].map((s) => (
          <button key={s} onClick={() => router.push(`/analysis/${s}`)} className="px-2 py-1 rounded bg-panel2 border border-line hover:border-accent">{s}</button>
        ))}</div>
      </Card>
    </div>
  );
}
