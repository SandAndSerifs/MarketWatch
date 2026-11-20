"use client";
import { useEffect, useRef } from "react";
import {
  CandlestickSeries, ColorType, createChart, createSeriesMarkers, CrosshairMode, HistogramSeries, LineSeries,
  type IChartApi, type SeriesMarker, type Time, type UTCTimestamp,
} from "lightweight-charts";

const THEME = {
  layout: { background: { type: ColorType.Solid, color: "#10161d" }, textColor: "#7f8c9b", fontSize: 11 },
  grid: { vertLines: { color: "#161f29" }, horzLines: { color: "#161f29" } },
  rightPriceScale: { borderColor: "#1f2a36" },
  timeScale: { borderColor: "#1f2a36", timeVisible: true, secondsVisible: false },
  crosshair: { mode: CrosshairMode.Normal },
};

export type Bar = { t: string; o: number; h: number; l: number; c: number; v: number };

const ts = (iso: string) => Math.floor(new Date(iso).getTime() / 1000) as UTCTimestamp;

export type Overlay = { key: string; values: (number | null)[]; color: string; pane?: number; width?: number };
export type Marker = { time: string; position: "aboveBar" | "belowBar"; color: string; shape: "arrowUp" | "arrowDown" | "circle"; text: string };
export type PriceLine = { price: number; color: string; title: string };

export function CandleChart({ bars, overlays = [], markers = [], priceLines = [], height = 420, showVolume = true, histPanes = [] }: {
  bars: Bar[]; overlays?: Overlay[]; markers?: Marker[]; priceLines?: PriceLine[]; height?: number; showVolume?: boolean;
  histPanes?: { key: string; values: (number | null)[]; pane: number }[];
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current || bars.length === 0) return;
    const chart: IChartApi = createChart(ref.current, { ...THEME, height, autoSize: true });
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: "#22c55e", downColor: "#f05252", borderVisible: false, wickUpColor: "#22c55e", wickDownColor: "#f05252",
    });
    const times = bars.map((b) => ts(b.t));
    candles.setData(bars.map((b, i) => ({ time: times[i], open: b.o, high: b.h, low: b.l, close: b.c })));
    if (showVolume) {
      const vol = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "vol", color: "#2a3a4d" });
      vol.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
      vol.setData(bars.map((b, i) => ({ time: times[i], value: b.v, color: b.c >= b.o ? "#1f4d33" : "#5a2427" })));
    }
    for (const o of overlays) {
      const s = chart.addSeries(LineSeries, { color: o.color, lineWidth: (o.width ?? 1) as 1, priceLineVisible: false, lastValueVisible: false }, o.pane ?? 0);
      s.setData(o.values.map((v, i) => (v === null ? { time: times[i] } : { time: times[i], value: v })) as any);
    }
    for (const h of histPanes) {
      const s = chart.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, h.pane);
      s.setData(h.values.map((v, i) => (v === null ? { time: times[i] } : { time: times[i], value: v, color: v >= 0 ? "#1f6b45" : "#7a2c30" })) as any);
    }
    for (const p of priceLines) candles.createPriceLine({ price: p.price, color: p.color, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: p.title });
    if (markers.length) {
      const mk: SeriesMarker<Time>[] = markers
        .map((m) => ({ time: ts(m.time), position: m.position, color: m.color, shape: m.shape, text: m.text }))
        .sort((a, b) => (a.time as number) - (b.time as number));
      createSeriesMarkers(candles, mk);
    }
    const panes = chart.panes();
    panes.forEach((p, i) => { if (i > 0) p.setHeight(90); });
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [bars, overlays, markers, priceLines, height, showVolume, histPanes]);
  return <div ref={ref} className="w-full" style={{ height }} />;
}

export function LineChart({ series, height = 260, percent = false }: {
  series: { name: string; color: string; points: { t: string; v: number }[] }[]; height?: number; percent?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, { ...THEME, height, autoSize: true });
    for (const s of series) {
      if (!s.points.length) continue;
      const line = chart.addSeries(LineSeries, {
        color: s.color, lineWidth: 2, title: s.name,
        priceFormat: percent ? { type: "custom", formatter: (x: number) => `${x.toFixed(2)}%` } : undefined,
      });
      const seen = new Set<number>();
      const pts = s.points
        .map((p) => ({ time: ts(p.t), value: p.v }))
        .sort((a, b) => (a.time as number) - (b.time as number))
        .filter((p) => (seen.has(p.time as number) ? false : (seen.add(p.time as number), true)));
      line.setData(pts);
    }
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [series, height, percent]);
  return <div ref={ref} className="w-full" style={{ height }} />;
}

/** Normalise an equity curve and benchmark prices to % change from the first point. */
export function toPctSeries(points: { t: string; v: number | null }[]) {
  const valid = points.filter((p) => p.v !== null && p.v !== undefined) as { t: string; v: number }[];
  if (!valid.length) return [];
  const base = valid[0].v;
  return valid.map((p) => ({ t: p.t, v: (p.v / base - 1) * 100 }));
}
