"use client";
import Link from "next/link";
import { useEffect } from "react";
import { Badge, Card, Empty, ErrorBox, Loading, PageHeader, Pct, PaperBadge, SeverityBadge, StatusBadge } from "@/components/ui";
import { useApi } from "@/lib/hooks";
import { useLive } from "@/lib/live";
import { ago, fmtMoney, fmtNum, fmtTime, fmtVol, tone } from "@/lib/format";

function QualityBanner({ q }: { q: any }) {
  if (!q) return null;
  return (
    <div className={`rounded-md border px-3 py-2 mb-3 text-[12px] ${q.realtime ? "border-info/30 bg-info/5" : "border-warn/40 bg-warn/5"}`}>
      <b>{q.provider}</b> · {q.label} · {q.coverage}
      {q.caveats?.length > 0 && <ul className="list-disc pl-5 mt-1 text-mute">{q.caveats.map((c: string, i: number) => <li key={i}>{c}</li>)}</ul>}
    </div>
  );
}

function IndexCards({ indices }: { indices: any[] }) {
  const { quotes } = useLive();
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      {indices.map((ix) => {
        const lq = quotes[ix.symbol];
        const price = lq?.price ?? ix.last_price;
        const chg = price && ix.prev_close ? (price / ix.prev_close - 1) * 100 : ix.change_pct;
        return (
          <Link key={ix.symbol} href={`/analysis/${ix.symbol}`} className="bg-panel border border-line rounded-lg p-3 hover:border-accent/50">
            <div className="text-[11px] text-mute truncate">{ix.label}</div>
            <div className="flex items-baseline justify-between mt-1">
              <span className="num text-xl font-semibold">{fmtNum(price)}</span>
              <Pct v={chg} />
            </div>
            <div className="text-[11px] text-mute mt-1">{ix.symbol} · {fmtTime(lq?.exchange_ts ?? ix.last_ts, false)}</div>
          </Link>
        );
      })}
    </div>
  );
}

function SectorHeat({ sectors }: { sectors: any[] }) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-4 gap-1.5">
      {sectors.map((s) => {
        const v = s.change_pct ?? 0;
        const a = Math.min(Math.abs(v) / 2.5, 1);
        const bg = v >= 0 ? `rgba(34,197,94,${0.1 + a * 0.45})` : `rgba(240,82,82,${0.1 + a * 0.45})`;
        return (
          <Link href={`/analysis/${s.symbol}`} key={s.symbol} className="rounded p-2" style={{ background: bg }}>
            <div className="text-[11px] truncate">{s.name}</div>
            <div className="flex justify-between num text-[12px]"><span>{s.symbol}</span><span>{s.change_pct != null ? `${v > 0 ? "+" : ""}${v.toFixed(2)}%` : "—"}</span></div>
          </Link>
        );
      })}
    </div>
  );
}

function MoverTable({ rows, title }: { rows: any[]; title: string }) {
  return (
    <div>
      <div className="text-[11px] uppercase text-mute mb-1">{title}</div>
      <table className="grid-table"><tbody>
        {rows.slice(0, 8).map((m) => (
          <tr key={m.symbol}>
            <td><Link className="text-accent" href={`/analysis/${m.symbol}`}>{m.symbol}</Link></td>
            <td className="num text-right">{fmtNum(m.price)}</td>
            <td className={`num text-right ${tone(m.change_pct)}`}>{m.change_pct != null ? `${m.change_pct > 0 ? "+" : ""}${m.change_pct.toFixed(2)}%` : "—"}</td>
          </tr>
        ))}
      </tbody></table>
    </div>
  );
}

export default function Dashboard() {
  const ov = useApi<any>("/api/market/overview", 30000);
  const mv = useApi<any>("/api/market/movers", 60000);
  const un = useApi<any>("/api/market/unusual", 120000);
  const news = useApi<any>("/api/market/news?limit=15", 120000);
  const ev = useApi<any[]>("/api/events?days=10", 300000);
  const al = useApi<any>("/api/alerts?limit=8", 30000);
  const ex = useApi<any[]>("/api/experiments", 30000);
  const { subscribe } = useLive();
  useEffect(() => { subscribe(["SPY", "QQQ", "DIA", "IWM"]); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const reg = ov.data?.regime;

  return (
    <div>
      <PageHeader title="Dashboard" subtitle="Live U.S. market overview, signals and paper-trading status. Index levels are shown via liquid ETF proxies." right={<PaperBadge />} />
      {ov.error ? <ErrorBox error={ov.error} /> : ov.loading ? <Loading /> : (
        <>
          <QualityBanner q={ov.data.quality} />
          <IndexCards indices={ov.data.indices} />
        </>
      )}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-3 mt-3">
        <Card title="Market regime" className="xl:col-span-1">
          {!reg ? <Loading /> : !reg.ok ? <ErrorBox error={reg.error || reg.reason} compact /> : (
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-2"><Badge color={{ risk_on: "green", neutral: "amber", risk_off: "red", high_volatility: "red" }[reg.label as string] || "gray"}>{reg.label.replace("_", " ")}</Badge><span className="text-mute text-[12px]">as of {fmtTime(reg.as_of)}</span></div>
              <p>{reg.description}</p>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 num text-[12px]">
                <span className="text-mute">SPY close</span><span className="text-right">{fmtNum(reg.spy_close)}</span>
                <span className="text-mute">50 / 200-day</span><span className="text-right">{fmtNum(reg.spy_sma50)} / {fmtNum(reg.spy_sma200)}</span>
                <span className="text-mute">20d realized vol</span><span className="text-right">{fmtNum(reg.realized_vol20)}%</span>
                <span className="text-mute">From 52w high</span><span className="text-right">{fmtNum(reg.drawdown_from_52w_high_pct)}%</span>
              </div>
            </div>
          )}
        </Card>
        <Card title="Sector performance (today)" className="xl:col-span-2">
          {ov.data ? <SectorHeat sectors={ov.data.sectors} /> : ov.error ? <Empty>Unavailable</Empty> : <Loading />}
          {reg?.sectors?.length > 0 && <div className="text-[11px] text-mute mt-2">20-day leaders vs SPY: {reg.sectors.slice(0, 3).map((s: any) => `${s.symbol} ${s.rel_strength_vs_spy > 0 ? "+" : ""}${s.rel_strength_vs_spy}%`).join(" · ")} · laggards: {reg.sectors.slice(-2).map((s: any) => `${s.symbol} ${s.rel_strength_vs_spy}%`).join(" · ")}</div>}
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 mt-3">
        <Card title="Gainers & losers" right={mv.data?.as_of && <span className="text-[11px] text-mute">{fmtTime(mv.data.as_of)}</span>}>
          {mv.error ? <ErrorBox error={mv.error} compact /> : !mv.data ? <Loading /> : mv.data.movers_error ? <Empty>{mv.data.movers_error}</Empty> : (
            <div className="grid grid-cols-2 gap-3"><MoverTable rows={mv.data.gainers} title="Gainers" /><MoverTable rows={mv.data.losers} title="Losers" /></div>
          )}
        </Card>
        <Card title="Unusual volume & volatility">
          {un.error ? <ErrorBox error={un.error} compact /> : !un.data ? <Loading /> : (
            <>
              <table className="grid-table"><thead><tr><th>Sym</th><th className="text-right">Chg</th><th className="text-right">RVOL*</th><th className="text-right">Move σ</th></tr></thead><tbody>
                {un.data.rows.slice(0, 10).map((r: any) => (
                  <tr key={r.symbol}><td><Link className="text-accent" href={`/analysis/${r.symbol}`}>{r.symbol}</Link></td>
                    <td className="text-right"><Pct v={r.change_pct} /></td><td className="num text-right">{r.rvol_time_adjusted ?? "—"}</td><td className="num text-right">{r.move_zscore ?? "—"}</td></tr>
                ))}
              </tbody></table>
              <p className="text-[11px] text-mute mt-2">*{un.data.caveats?.[0]}</p>
            </>
          )}
        </Card>
        <Card title="Most active (volume)">
          {mv.data?.most_active ? (
            <table className="grid-table"><tbody>{mv.data.most_active.slice(0, 10).map((m: any) => (
              <tr key={m.symbol}><td><Link className="text-accent" href={`/analysis/${m.symbol}`}>{m.symbol}</Link></td><td className="num text-right">{fmtVol(m.volume)}</td></tr>
            ))}</tbody></table>
          ) : mv.data?.most_active_error ? <Empty>{mv.data.most_active_error}</Empty> : mv.error ? <Empty>Unavailable</Empty> : <Loading />}
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 mt-3">
        <Card title="Paper trading" right={<Link href="/paper" className="text-accent text-[12px]">Open</Link>}>
          {ex.error ? <ErrorBox error={ex.error} compact /> : !ex.data ? <Loading /> : ex.data.length === 0 ? <Empty>No experiments yet. <Link href="/paper" className="text-accent">Create one with $10,000 hypothetical capital.</Link></Empty> : (
            <table className="grid-table"><tbody>{ex.data.slice(0, 6).map((e) => (
              <tr key={e.id}><td className="truncate max-w-[140px]">{e.name}</td><td><StatusBadge s={e.status} /></td>
                <td className="num text-right">{fmtMoney(e.equity, 0)}</td><td className="text-right"><Pct v={e.stats.total_return_pct} /></td></tr>
            ))}</tbody></table>
          )}
        </Card>
        <Card title="Latest alerts" right={<Link href="/alerts" className="text-accent text-[12px]">All</Link>}>
          {al.error ? <ErrorBox error={al.error} compact /> : !al.data ? <Loading /> : al.data.alerts.length === 0 ? <Empty>No alerts yet.</Empty> : (
            <ul className="flex flex-col gap-2">{al.data.alerts.map((a: any) => (
              <li key={a.id} className="flex gap-2 items-start"><SeverityBadge s={a.severity} /><div className="min-w-0"><div className="truncate">{a.title}</div><div className="text-[11px] text-mute">{ago(a.ts)}</div></div></li>
            ))}</ul>
          )}
        </Card>
        <Card title="Upcoming events" right={<Link href="/settings#events" className="text-accent text-[12px]">Manage</Link>}>
          {ev.error ? <ErrorBox error={ev.error} compact /> : !ev.data ? <Loading /> : ev.data.length === 0 ? <Empty>No events on file in the next 10 days.</Empty> : (
            <ul className="flex flex-col gap-1.5">{ev.data.slice(0, 10).map((e) => (
              <li key={e.id} className="flex justify-between gap-2"><span className="truncate"><Badge color={e.kind === "macro" ? "blue" : "amber"}>{e.kind}</Badge> {e.symbol !== "*" && <b>{e.symbol} </b>}{e.name}</span><span className="num text-mute whitespace-nowrap">{e.date} {e.time_et || ""}</span></li>
            ))}</ul>
          )}
        </Card>
      </div>

      <Card title="Market news" className="mt-3">
        {news.error ? <ErrorBox error={news.error} compact /> : !news.data ? <Loading /> : news.data.items.length === 0 ? <Empty>{news.data.error || "No news returned by the provider."}</Empty> : (
          <ul className="flex flex-col divide-y divide-line">{news.data.items.map((n: any) => (
            <li key={n.id} className="py-1.5 flex gap-3">
              <span className="text-[11px] text-mute whitespace-nowrap w-28 shrink-0">{fmtTime(n.created_at)}</span>
              <span className="min-w-0"><a href={n.url} target="_blank" rel="noreferrer" className="hover:text-accent">{n.headline}</a>
                <span className="text-[11px] text-mute"> · {n.source} {n.symbols?.slice(0, 5).map((s: string) => <Link key={s} href={`/analysis/${s}`} className="text-accent ml-1">{s}</Link>)}</span></span>
            </li>
          ))}</ul>
        )}
      </Card>
    </div>
  );
}
