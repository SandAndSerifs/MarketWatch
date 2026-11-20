"use client";
import { useEffect, useRef, useState } from "react";
import { Bot, Send, Wrench } from "lucide-react";
import { Button, Card, ErrorBox, PageHeader } from "@/components/ui";
import { post } from "@/lib/api";

const EXAMPLES = [
  "Why is Nvidia moving today?",
  "What are the strongest bullish setups right now?",
  "Analyze Tesla like a professional trader.",
  "What is the biggest risk with buying AAPL here?",
  "Which strategy has been performing best?",
  "What trades did the paper trader make today?",
  "Explain a bullish engulfing candlestick pattern and its limits.",
  "How is the market reacting to today's economic news?",
];

type Msg = { role: "user" | "assistant"; content: string; tools?: any[]; model?: string };

function Rich({ text }: { text: string }) {
  // Minimal formatting: bold, labels, bullets, headings. No HTML injection.
  return (
    <div className="flex flex-col gap-1 leading-relaxed">
      {text.split("\n").map((line, i) => {
        const h = line.match(/^#{1,3}\s+(.*)/);
        if (h) return <div key={i} className="font-semibold mt-2">{h[1]}</div>;
        const isBullet = /^\s*[-*]\s+/.test(line);
        const body = isBullet ? line.replace(/^\s*[-*]\s+/, "") : line;
        const parts = body.split(/(\*\*[^*]+\*\*|\[(?:Fact|Interpretation|Estimate|Uncertain)\])/g).filter(Boolean);
        const content = parts.map((p, j) => {
          if (p.startsWith("**")) return <b key={j}>{p.slice(2, -2)}</b>;
          const lab = p.match(/^\[(Fact|Interpretation|Estimate|Uncertain)\]$/);
          if (lab) {
            const c = { Fact: "bg-up/15 text-up", Interpretation: "bg-accent/15 text-accent", Estimate: "bg-warn/15 text-warn", Uncertain: "bg-down/15 text-down" }[lab[1]];
            return <span key={j} className={`text-[10px] px-1 rounded mr-1 ${c}`}>{lab[1]}</span>;
          }
          return <span key={j}>{p}</span>;
        });
        if (isBullet) return <div key={i} className="pl-4 relative"><span className="absolute left-1 text-mute">•</span>{content}</div>;
        return <div key={i}>{line.trim() === "" ? <br /> : content}</div>;
      })}
    </div>
  );
}

export default function Analyst() {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [cid, setCid] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<any>(null);
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, busy]);

  const send = async (text: string) => {
    if (!text.trim() || busy) return;
    setErr(null);
    setMsgs((m) => [...m, { role: "user", content: text }]);
    setInput("");
    setBusy(true);
    try {
      const r = await post("/api/ai/chat", { message: text, conversation_id: cid });
      setCid(r.conversation_id);
      setMsgs((m) => [...m, { role: "assistant", content: r.answer, tools: r.tool_calls, model: r.model }]);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col h-[calc(100vh-7rem)]">
      <PageHeader title="AI Market Analyst" subtitle="Answers are grounded in tool calls to verified market data, recorded trades and the knowledge library. Statements are labelled Fact / Interpretation / Estimate / Uncertain. Not financial advice."
        right={<Button onClick={() => { setMsgs([]); setCid(null); }}>New conversation</Button>} />
      <ErrorBox error={err} />
      <Card className="flex-1 flex flex-col min-h-0" pad={false}>
        <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-4">
          {msgs.length === 0 && (
            <div className="text-mute">
              <div className="flex items-center gap-2 mb-3"><Bot className="w-5 h-5 text-accent" />Ask about markets, setups, risk, your paper trades or trading concepts.</div>
              <div className="grid sm:grid-cols-2 gap-2">{EXAMPLES.map((e) => (
                <button key={e} onClick={() => send(e)} className="text-left px-3 py-2 rounded-md bg-panel2 border border-line hover:border-accent text-ink">{e}</button>
              ))}</div>
            </div>
          )}
          {msgs.map((m, i) => (
            <div key={i} className={m.role === "user" ? "self-end max-w-[80%] bg-accent/15 border border-accent/30 rounded-lg px-3 py-2" : "max-w-[90%]"}>
              {m.role === "assistant" ? (
                <>
                  <Rich text={m.content} />
                  {m.tools && m.tools.length > 0 && (
                    <details className="mt-2 text-[11px] text-mute">
                      <summary className="cursor-pointer flex items-center gap-1"><Wrench className="w-3 h-3" />{m.tools.length} data lookups · {m.model}</summary>
                      <ul className="mt-1 pl-4 list-disc">{m.tools.map((t, j) => <li key={j}>{t.tool} {t.input ? JSON.stringify(t.input) : ""} {t.ok ? "" : `(error: ${t.error})`}</li>)}</ul>
                    </details>
                  )}
                </>
              ) : m.content}
            </div>
          ))}
          {busy && <div className="text-mute animate-pulse">Analyzing with live tools…</div>}
          <div ref={endRef} />
        </div>
        <form className="border-t border-line p-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); send(input); }}>
          <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask the analyst…" className="flex-1" />
          <Button type="submit" variant="primary" disabled={busy}><Send className="w-4 h-4" />Send</Button>
        </form>
      </Card>
    </div>
  );
}
