"use client";
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { wsUrl } from "./api";

export type LiveQuote = {
  symbol: string;
  price: number;
  exchange_ts: string;
  received_at: string;
  bid: number | null;
  ask: number | null;
  source: string;
};

type LiveState = {
  connected: boolean;
  quotes: Record<string, LiveQuote>;
  lastAlert: any | null;
  status: any | null;
  feedHealth: any | null;
  subscribe: (symbols: string[]) => void;
  desktopEnabled: boolean;
  setDesktopEnabled: (v: boolean) => void;
};

const Ctx = createContext<LiveState | null>(null);

export function LiveProvider({ children }: { children: ReactNode }) {
  const [connected, setConnected] = useState(false);
  const [quotes, setQuotes] = useState<Record<string, LiveQuote>>({});
  const [lastAlert, setLastAlert] = useState<any>(null);
  const [status, setStatus] = useState<any>(null);
  const [feedHealth, setFeedHealth] = useState<any>(null);
  const [desktopEnabled, setDesktop] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const pending = useRef<string[]>([]);
  const desktopRef = useRef(false);

  useEffect(() => {
    try {
      const v = localStorage.getItem("mp_desktop_notifications") === "1";
      setDesktop(v);
      desktopRef.current = v;
    } catch {
      /* storage unavailable */
    }
  }, []);

  const setDesktopEnabled = (v: boolean) => {
    setDesktop(v);
    desktopRef.current = v;
    try {
      localStorage.setItem("mp_desktop_notifications", v ? "1" : "0");
    } catch {
      /* ignore */
    }
    if (v && typeof Notification !== "undefined" && Notification.permission === "default") Notification.requestPermission();
  };

  useEffect(() => {
    let stop = false;
    let retry = 1000;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const connect = () => {
      if (stop) return;
      const ws = new WebSocket(wsUrl());
      wsRef.current = ws;
      ws.onopen = () => {
        setConnected(true);
        retry = 1000;
        if (pending.current.length) ws.send(JSON.stringify({ subscribe: pending.current }));
      };
      ws.onclose = () => {
        setConnected(false);
        if (!stop) timer = setTimeout(connect, (retry = Math.min(retry * 2, 30000)));
      };
      ws.onerror = () => ws.close();
      ws.onmessage = (ev) => {
        let msg: any;
        try {
          msg = JSON.parse(ev.data);
        } catch {
          return;
        }
        if (msg.type === "quote") setQuotes((q) => ({ ...q, [msg.data.symbol]: msg.data }));
        else if (msg.type === "hello") setStatus(msg.data);
        else if (msg.type === "feed_health") setFeedHealth(msg.data);
        else if (msg.type === "alert") {
          setLastAlert(msg.data);
          const a = msg.data;
          if (desktopRef.current && a.channels?.includes("desktop") && typeof Notification !== "undefined" && Notification.permission === "granted") {
            new Notification(a.title, { body: String(a.body).slice(0, 240), tag: `mp-${a.id}` });
          }
        }
      };
    };
    connect();
    return () => {
      stop = true;
      if (timer) clearTimeout(timer);
      wsRef.current?.close();
    };
  }, []);

  const subscribe = (symbols: string[]) => {
    const syms = symbols.map((s) => s.toUpperCase());
    pending.current = Array.from(new Set([...pending.current, ...syms])).slice(-50);
    if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(JSON.stringify({ subscribe: syms }));
  };

  return (
    <Ctx.Provider value={{ connected, quotes, lastAlert, status, feedHealth, subscribe, desktopEnabled, setDesktopEnabled }}>
      {children}
    </Ctx.Provider>
  );
}

export function useLive() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useLive outside LiveProvider");
  return v;
}
