"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { Button, Card, Empty, ErrorBox, Loading, PageHeader, Pct } from "@/components/ui";
import { api, del, post } from "@/lib/api";
import { useAction, useApi } from "@/lib/hooks";
import { useLive } from "@/lib/live";
import { fmtNum, fmtTime, fmtVol } from "@/lib/format";

export default function Watchlists() {
  const wls = useApi<any[]>("/api/watchlists");
  const [active, setActive] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [sym, setSym] = useState("");
  const [results, setResults] = useState<any[]>([]);
  const act = useAction();
  const { quotes, subscribe } = useLive();
  const wl = wls.data?.find((w) => w.id === active) || wls.data?.[0];
  const symbols = useMemo(() => (wl?.items || []).map((i: any) => i.symbol), [wl]);
  const snaps = useApi<any>(symbols.length ? `/api/market/quotes?symbols=${symbols.join(",")}` : null, 20000);
  useEffect(() => { if (symbols.length) subscribe(symbols); }, [symbols]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (sym.length < 1) { setResults([]); return; }
    const id = setTimeout(async () => { try { setResults(await api(`/api/market/search?q=${encodeURIComponent(sym)}`)); } catch { setResults([]); } }, 300);
    return () => clearTimeout(id);
  }, [sym]);

  const add = async (s: string) => {
    if (!wl) return;
    const r = await act.run(() => post(`/api/watchlists/${wl.id}/items`, { symbol: s }));
    if (r) { setSym(""); setResults([]); wls.reload(); }
  };

  return (
    <div>
      <PageHeader title="Watchlists" subtitle="Symbols here are monitored by the scanner and intraday alerts (opening-range breaks, unusual moves, closing strength)." />
      <ErrorBox error={act.error} />
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-3">
        <Card title="Lists">
          {!wls.data ? <Loading /> : (
            <div className="flex flex-col gap-1">
              {wls.data.map((w) => (
                <div key={w.id} className={`flex items-center justify-between px-2 py-1.5 rounded cursor-pointer ${wl?.id === w.id ? "bg-accent/15" : "hover:bg-panel2"}`} onClick={() => setActive(w.id)}>
                  <span>{w.name} <span className="text-mute">({w.items.length})</span></span>
                  <button title="Delete list" onClick={async (e) => { e.stopPropagation(); if (confirm(`Delete ${w.name}?`)) { await del(`/api/watchlists/${w.id}`); wls.reload(); } }} className="text-mute hover:text-down"><Trash2 className="w-3.5 h-3.5" /></button>
                </div>
              ))}
              <form className="flex gap-1 mt-2" onSubmit={async (e) => { e.preventDefault(); if (name.trim() && await act.run(() => post("/api/watchlists", { name }))) { setName(""); wls.reload(); } }}>
                <input value={name} onChange={(e) => setName(e.target.value)} placeholder="New list" className="flex-1 min-w-0" />
                <Button type="submit"><Plus className="w-4 h-4" /></Button>
              </form>
            </div>
          )}
        </Card>
        <Card title={wl ? wl.name : "Watchlist"} className="lg:col-span-3" right={
          <div className="relative">
            <input value={sym} onChange={(e) => setSym(e.target.value.toUpperCase())} onKeyDown={(e) => { if (e.key === "Enter" && sym) add(sym); }} placeholder="Add symbol…" className="w-48" />
            {results.length > 0 && (
              <div className="absolute right-0 top-9 z-20 w-80 bg-panel2 border border-line rounded-md max-h-72 overflow-y-auto">
                {results.map((r) => (
                  <button key={r.symbol} onClick={() => add(r.symbol)} className="w-full text-left px-2 py-1.5 hover:bg-panel flex justify-between gap-2">
                    <b>{r.symbol}</b><span className="text-mute truncate">{r.name}</span><span className="text-mute text-[11px]">{r.exchange}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        } pad={false}>
          {!wl ? <Empty>Create a watchlist.</Empty> : wl.items.length === 0 ? <Empty>Empty list. Add a symbol above.</Empty> : (
            <>
              {snaps.error && <div className="p-3"><ErrorBox error={snaps.error} compact /></div>}
              <div className="overflow-x-auto">
                <table className="grid-table">
                  <thead><tr><th>Symbol</th><th className="text-right">Last</th><th className="text-right">Chg %</th><th className="text-right">Bid</th><th className="text-right">Ask</th><th className="text-right">Day range</th><th className="text-right">Volume</th><th>Updated</th><th>Feed</th><th></th></tr></thead>
                  <tbody>{wl.items.map((i: any) => {
                    const s = snaps.data?.snapshots?.[i.symbol];
                    const lq = quotes[i.symbol];
                    const price = lq?.price ?? s?.last_price;
                    const chg = price && s?.prev_close ? (price / s.prev_close - 1) * 100 : s?.change_pct;
                    return (
                      <tr key={i.symbol}>
                        <td><Link className="text-accent font-semibold" href={`/analysis/${i.symbol}`}>{i.symbol}</Link></td>
                        <td className="num text-right">{fmtNum(price)}</td>
                        <td className="text-right"><Pct v={chg} /></td>
                        <td className="num text-right">{fmtNum(lq?.bid ?? s?.bid)}</td>
                        <td className="num text-right">{fmtNum(lq?.ask ?? s?.ask)}</td>
                        <td className="num text-right text-mute">{s ? `${fmtNum(s.day_low)} – ${fmtNum(s.day_high)}` : "—"}</td>
                        <td className="num text-right">{fmtVol(s?.day_volume)}</td>
                        <td className="text-mute whitespace-nowrap">{fmtTime(lq?.exchange_ts ?? s?.last_ts)}</td>
                        <td className="text-mute text-[11px]">{lq?.source ?? s?.feed ?? "—"}</td>
                        <td><button className="text-mute hover:text-down" onClick={async () => { await del(`/api/watchlists/${wl.id}/items/${i.symbol}`); wls.reload(); }}><Trash2 className="w-3.5 h-3.5" /></button></td>
                      </tr>
                    );
                  })}</tbody>
                </table>
              </div>
            </>
          )}
        </Card>
      </div>
    </div>
  );
}
