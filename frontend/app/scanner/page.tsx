"use client";
import Link from "next/link";
import { useState } from "react";
import { Play, X } from "lucide-react";
import DecisionRecord from "@/components/DecisionRecord";
import { Button, Card, CategoryBadge, Empty, ErrorBox, Loading, PageHeader } from "@/components/ui";
import { api, post, put } from "@/lib/api";
import { useAction, useApi } from "@/lib/hooks";
import { fmtNum, fmtTime } from "@/lib/format";

const CATS = ["", "BUY_CANDIDATE", "SELL_EXIT_CANDIDATE", "WATCH", "HOLD_MANAGE", "NO_TRADE"];

export default function Scanner() {
  const [cat, setCat] = useState("");
  const [sym, setSym] = useState("");
  const sigs = useApi<any[]>(`/api/scanner/signals?limit=300${cat ? `&category=${cat}` : ""}${sym ? `&symbol=${sym}` : ""}`, 60000);
  const settings = useApi<any>("/api/scanner/settings");
  const strategies = useApi<any[]>("/api/strategies");
  const status = useApi<any>("/api/status", 30000);
  const scan = useAction();
  const [last, setLast] = useState<any>(null);
  const [detail, setDetail] = useState<any>(null);

  const run = async () => {
    const r = await scan.run(() => post("/api/scanner/run"));
    if (r) { setLast(r); sigs.reload(); }
  };
  const toggle = async (key: string) => {
    const cur: string[] = settings.data.strategies;
    const next = cur.includes(key) ? cur.filter((k) => k !== key) : [...cur, key];
    settings.setData(await put("/api/scanner/settings", { strategies: next }));
  };
  const open = async (id: number) => setDetail(await api(`/api/signals/${id}`));
  const ls = last || status.data?.scanner?.last_scan;

  return (
    <div>
      <PageHeader title="Market Scanner"
        subtitle="Every enabled strategy is evaluated on completed daily bars across the scan universe (default liquid large caps + ETFs + your watchlists). Each hit runs the full 8-step checklist; signals are plans, not guarantees."
        right={<Button variant="primary" onClick={run} disabled={scan.busy}><Play className="w-4 h-4" />{scan.busy ? "Scanning…" : "Run scan now"}</Button>} />
      <ErrorBox error={scan.error} />
      <div className="grid grid-cols-1 xl:grid-cols-4 gap-3">
        <Card title="Scanner settings" className="xl:col-span-1">
          {!settings.data || !strategies.data ? <Loading /> : (
            <div className="flex flex-col gap-2">
              {strategies.data.filter((s) => s.timeframe === "1Day" && s.key !== "custom").map((s) => (
                <label key={s.key} className="flex items-start gap-2 cursor-pointer">
                  <input type="checkbox" checked={settings.data.strategies.includes(s.key)} onChange={() => toggle(s.key)} className="mt-1" />
                  <span><b>{s.name}</b><br /><span className="text-mute text-[12px]">{s.style}</span></span>
                </label>
              ))}
              <div className="text-[12px] text-mute border-t border-line pt-2">
                {ls ? <>Last scan {fmtTime(ls.at)} · {ls.symbols} symbols · new signals {ls.new_signals}<br />{Object.entries(ls.counts || {}).map(([k, v]) => `${k}: ${v}`).join(" · ")}</> : "No scan yet this session. Scans run automatically pre-market and after the close."}
              </div>
            </div>
          )}
        </Card>
        <Card title="Signals" className="xl:col-span-3" right={
          <div className="flex gap-2">
            <select value={cat} onChange={(e) => setCat(e.target.value)}>{CATS.map((c) => <option key={c} value={c}>{c ? c.replace(/_/g, " ") : "All categories"}</option>)}</select>
            <input placeholder="Symbol" value={sym} onChange={(e) => setSym(e.target.value.toUpperCase())} className="w-24" />
          </div>
        } pad={false}>
          {sigs.error ? <div className="p-3"><ErrorBox error={sigs.error} /></div> : !sigs.data ? <Loading /> : sigs.data.length === 0 ? <Empty>No signals yet. Run a scan (requires a configured market-data provider).</Empty> : (
            <div className="overflow-x-auto">
              <table className="grid-table">
                <thead><tr><th>Time</th><th>Symbol</th><th>Signal</th><th>Strategy</th><th className="text-right">Price</th><th className="text-right">Entry</th><th className="text-right">Stop</th><th className="text-right">Target</th><th className="text-right">R:R</th><th>Summary</th></tr></thead>
                <tbody>{sigs.data.map((s) => (
                  <tr key={s.id} className="cursor-pointer" onClick={() => open(s.id)}>
                    <td className="whitespace-nowrap text-mute">{fmtTime(s.ts)}</td>
                    <td><Link onClick={(e) => e.stopPropagation()} className="text-accent" href={`/analysis/${s.symbol}`}>{s.symbol}</Link></td>
                    <td><CategoryBadge c={s.category} /></td>
                    <td className="whitespace-nowrap">{s.strategy_key}</td>
                    <td className="num text-right" title={`${s.data_feed} @ ${s.price_ts}`}>{fmtNum(s.price)}</td>
                    <td className="num text-right">{fmtNum(s.entry)}</td><td className="num text-right">{fmtNum(s.stop)}</td>
                    <td className="num text-right">{fmtNum(s.target)}</td><td className="num text-right">{fmtNum(s.risk_reward)}</td>
                    <td className="text-mute max-w-md truncate">{s.summary}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
      {detail && (
        <div className="fixed inset-0 z-40 bg-black/60 flex justify-end" onClick={() => setDetail(null)}>
          <div className="w-full max-w-3xl h-full overflow-y-auto bg-bg border-l border-line p-4" onClick={(e) => e.stopPropagation()}>
            <div className="flex justify-between items-start mb-3">
              <div><h2 className="text-lg font-semibold">{detail.signal.symbol} · {detail.signal.strategy_key}</h2>
                <p className="text-mute text-[12px]">{detail.signal.summary}</p></div>
              <button onClick={() => setDetail(null)}><X className="w-5 h-5" /></button>
            </div>
            <DecisionRecord record={detail.decision?.record} />
          </div>
        </div>
      )}
    </div>
  );
}
