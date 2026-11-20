"use client";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { CandleChart, type Overlay } from "@/components/Charts";
import { Badge, Card, CategoryBadge, Empty, ErrorBox, KV, Loading, PageHeader, Pct, Tabs } from "@/components/ui";
import { useApi } from "@/lib/hooks";
import { useLive } from "@/lib/live";
import { fmtNum, fmtTime, fmtVol } from "@/lib/format";

const TFS = ["1Min", "5Min", "15Min", "1Hour", "1Day"];
const OVL: Record<string, string> = { sma20: "#f5a524", sma50: "#3b82f6", sma200: "#a855f7", ema20: "#14b8a6", bb_upper: "#475569", bb_lower: "#475569", vwap: "#eab308" };

export default function SymbolAnalysis() {
  const { symbol } = useParams<{ symbol: string }>();
  const sym = String(symbol).toUpperCase();
  const [tf, setTf] = useState("1Day");
  const [ovl, setOvl] = useState<string[]>(["sma20", "sma50", "sma200"]);
  const [lower, setLower] = useState<"rsi" | "macd" | "none">("rsi");
  const bars = useApi<any>(`/api/market/bars/${sym}?timeframe=${tf}`, tf === "1Day" ? 120000 : 30000);
  const an = useApi<any>(`/api/market/analysis/${sym}`);
  const { quotes, subscribe } = useLive();
  const [tab, setTab] = useState("setups");
  const [openSetup, setOpenSetup] = useState<string | null>(null);
  useEffect(() => { subscribe([sym]); }, [sym]); // eslint-disable-line react-hooks/exhaustive-deps

  const overlays = useMemo<Overlay[]>(() => {
    if (!bars.data) return [];
    const o: Overlay[] = ovl.filter((k) => bars.data.overlays[k]).map((k) => ({ key: k, values: bars.data.overlays[k], color: OVL[k] }));
    if (lower === "rsi" && bars.data.overlays.rsi14) o.push({ key: "rsi", values: bars.data.overlays.rsi14, color: "#38bdf8", pane: 1 });
    if (lower === "macd" && bars.data.overlays.macd) {
      o.push({ key: "macd", values: bars.data.overlays.macd, color: "#38bdf8", pane: 1 });
      o.push({ key: "macds", values: bars.data.overlays.macd_signal, color: "#f5a524", pane: 1 });
    }
    return o;
  }, [bars.data, ovl, lower]);
  const hist = useMemo(() => (lower === "macd" && bars.data?.overlays.macd_hist ? [{ key: "h", values: bars.data.overlays.macd_hist, pane: 1 }] : []), [bars.data, lower]);
  const levels = useMemo(() => {
    const t = an.data?.technicals;
    if (!t?.ok) return [];
    return [...(t.support || []).slice(0, 3).map((l: any) => ({ price: l.price, color: "#22c55e", title: `S ${l.touches}x` })),
      ...(t.resistance || []).slice(0, 3).map((l: any) => ({ price: l.price, color: "#f05252", title: `R ${l.touches}x` }))];
  }, [an.data]);

  const snap = an.data?.snapshot;
  const lq = quotes[sym];
  const price = lq?.price ?? snap?.last_price;
  const chg = price && snap?.prev_close ? (price / snap.prev_close - 1) * 100 : snap?.change_pct;
  const t = an.data?.technicals;

  return (
    <div>
      <PageHeader title={sym} subtitle={an.data?.quality ? `${an.data.quality.provider} · ${an.data.quality.label}` : undefined}
        right={price != null && <div className="text-right"><div className="num text-2xl font-semibold">{fmtNum(price)} <Pct v={chg} /></div><div className="text-[11px] text-mute">{fmtTime(lq?.exchange_ts ?? snap?.last_ts)} · {lq?.source ?? snap?.feed}</div></div>} />
      <Card pad={false} title={
        <div className="flex flex-wrap gap-1">{TFS.map((x) => <button key={x} onClick={() => setTf(x)} className={`px-2 py-0.5 rounded text-[12px] ${tf === x ? "bg-accent text-white" : "bg-panel2 text-mute"}`}>{x}</button>)}</div>
      } right={
        <div className="flex flex-wrap gap-1 items-center">
          {Object.keys(OVL).map((k) => (
            <button key={k} onClick={() => setOvl((o) => (o.includes(k) ? o.filter((x) => x !== k) : [...o, k]))} className={`px-1.5 py-0.5 rounded text-[11px] border ${ovl.includes(k) ? "border-transparent" : "border-line text-mute"}`} style={ovl.includes(k) ? { background: OVL[k] + "33", color: OVL[k] } : {}}>{k}</button>
          ))}
          <select value={lower} onChange={(e) => setLower(e.target.value as any)} className="py-0.5 text-[12px]"><option value="rsi">RSI pane</option><option value="macd">MACD pane</option><option value="none">No pane</option></select>
        </div>
      }>
        {bars.error ? <div className="p-3"><ErrorBox error={bars.error} /></div> : !bars.data ? <Loading /> : bars.data.bars.length === 0 ? <Empty>No bars returned for {sym} at {tf}.</Empty> : (
          <>
            <CandleChart bars={bars.data.bars} overlays={overlays} histPanes={hist} priceLines={tf === "1Day" ? levels : []} height={480} />
            <div className="px-3 py-1.5 text-[11px] text-mute border-t border-line">{bars.data.source}{bars.data.last_bar_partial ? " · last daily bar is still forming (excluded from signals)" : ""} · {bars.data.bars.length} bars · S/R lines from confirmed swing pivots</div>
          </>
        )}
      </Card>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-3 mt-3">
        <Card title="Technicals (completed daily bars)">
          {an.error ? <ErrorBox error={an.error} compact /> : !t ? <Loading /> : !t.ok ? <Empty>{t.reason}</Empty> : (
            <KV rows={[
              ["Trend", <Badge key="t" color={t.trend === "uptrend" ? "green" : t.trend === "downtrend" ? "red" : "amber"}>{t.trend}</Badge>],
              ["SMA 20 / 50 / 200", `${fmtNum(t.sma20)} / ${fmtNum(t.sma50)} / ${fmtNum(t.sma200)}`],
              ["RSI 14 / 2", `${fmtNum(t.rsi14, 1)} / ${fmtNum(t.rsi2, 1)}`], ["MACD / signal / hist", `${fmtNum(t.macd, 3)} / ${fmtNum(t.macd_signal, 3)} / ${fmtNum(t.macd_hist, 3)}`],
              ["Bollinger %B / width pct", `${fmtNum(t.pct_b, 2)} / ${fmtNum(t.bb_width_pctile, 0)}`], ["ATR 14 (%)", `${fmtNum(t.atr14)} (${fmtNum(t.atr_pct)}%)`],
              ["ADX 14 (+DI / -DI)", `${fmtNum(t.adx14, 1)} (${fmtNum(t.plus_di, 1)} / ${fmtNum(t.minus_di, 1)})`], ["Relative volume 20d", fmtNum(t.rvol20)],
              ["ROC 20 / 63 / 126", `${fmtNum(t.roc20, 1)}% / ${fmtNum(t.roc63, 1)}% / ${fmtNum(t.roc126, 1)}%`], ["52w high / low", `${fmtNum(t.high252)} / ${fmtNum(t.low252)}`],
              ["From 52w high", `${fmtNum(t.pct_from_52w_high)}%`], ["Avg $ volume 20d", `$${fmtVol(t.avg_dollar_volume20)}`],
              ["Support", (t.support || []).map((l: any) => l.price).join(", ") || "—"], ["Resistance", (t.resistance || []).map((l: any) => l.price).join(", ") || "—"],
            ]} />
          )}
        </Card>
        <Card title="Context" className="xl:col-span-2">
          <Tabs value={tab} onChange={setTab} tabs={[{ key: "setups", label: "Strategy checklists" }, { key: "events", label: "Events" }, { key: "news", label: "News" }]} />
          {an.error ? <ErrorBox error={an.error} compact /> : !an.data ? <Loading /> : tab === "setups" ? (
            <div className="flex flex-col gap-2">
              {an.data.setups.map((s: any) => (
                <div key={s.strategy} className="border border-line rounded-md">
                  <button className="w-full flex flex-wrap items-center gap-2 px-3 py-2 text-left" onClick={() => setOpenSetup(openSetup === s.strategy ? null : s.strategy)}>
                    <b className="w-40">{s.strategy}</b>
                    {s.category ? <CategoryBadge c={s.category} /> : <Badge>no setup</Badge>}
                    <span className="text-mute truncate flex-1">{s.category ? s.rationale : s.result}</span>
                    {s.plan && <span className="num text-[12px]">entry {fmtNum(s.plan.entry)} · stop {fmtNum(s.plan.stop)} · tgt {fmtNum(s.plan.target)} · R:R {fmtNum(s.plan.reward_risk)}</span>}
                  </button>
                  {openSetup === s.strategy && s.category && (
                    <div className="px-3 pb-3 text-[13px] flex flex-col gap-2">
                      <p>{s.thesis}</p>
                      <div><b>Evidence</b><ul className="list-disc pl-5">{s.evidence.map((e: string, i: number) => <li key={i}>{e}</li>)}</ul></div>
                      <div><b>Objections</b><ul className="list-disc pl-5">{s.objections.map((o: any, i: number) => <li key={i}><Badge color={o.severity === "caution" ? "amber" : o.severity === "info" ? "gray" : "red"}>{o.severity}</Badge> {o.issue}: {o.detail}</li>)}</ul></div>
                      <div><b>Would be invalidated by</b><ul className="list-disc pl-5">{s.invalidation.map((x: string, i: number) => <li key={i}>{x}</li>)}</ul></div>
                    </div>
                  )}
                </div>
              ))}
              <p className="text-[11px] text-mute">Evaluated now on completed daily bars against an illustrative $10,000 account. Not a recommendation.</p>
            </div>
          ) : tab === "events" ? (
            an.data.events.length === 0 ? <Empty>No events on file for {sym} (earnings dates need FINNHUB_API_KEY).</Empty> :
              <ul className="flex flex-col gap-1">{an.data.events.map((e: any) => <li key={e.id}>{e.date} {e.time_et || ""} · {e.name} {e.symbol !== "*" ? e.symbol : ""} <span className="text-mute">({e.source})</span></li>)}</ul>
          ) : (
            an.data.news.length === 0 ? <Empty>No news returned for {sym}.</Empty> :
              <ul className="flex flex-col gap-1.5">{an.data.news.map((n: any) => <li key={n.id}><span className="text-mute text-[11px] mr-2">{fmtTime(n.created_at)}</span><a href={n.url} target="_blank" rel="noreferrer" className="hover:text-accent">{n.headline}</a> <span className="text-mute text-[11px]">{n.source}</span></li>)}</ul>
          )}
        </Card>
      </div>
    </div>
  );
}
