"use client";
import { useEffect, useState } from "react";
import { Button, ErrorBox, Field } from "./ui";
import { post } from "@/lib/api";
import { useAction, useApi } from "@/lib/hooks";

const RISK_FIELDS: [string, string, string][] = [
  ["max_position_pct", "Max position (% of starting equity)", "Hard ceiling 20"],
  ["max_concurrent_positions", "Max concurrent positions", "Hard ceiling 10"],
  ["max_daily_loss_pct", "Max daily loss (% of starting equity)", "Hard ceiling 5"],
  ["risk_per_trade_pct", "Risk per trade (% of equity at stop)", "Hard ceiling 2"],
  ["min_reward_risk", "Minimum reward:risk", ""],
  ["max_sector_positions", "Max positions per sector", ""],
  ["earnings_blackout_days", "Earnings blackout (sessions)", ""],
];

export default function ExperimentForm({ onCreated }: { onCreated: (e: any) => void }) {
  const strategies = useApi<any[]>("/api/strategies");
  const settings = useApi<any>("/api/settings");
  const [name, setName] = useState("My paper experiment");
  const [key, setKey] = useState("trend_pullback");
  const [capital, setCapital] = useState(10000);
  const [params, setParams] = useState<Record<string, any>>({});
  const [risk, setRisk] = useState<Record<string, any>>({});
  const [universe, setUniverse] = useState("");
  const act = useAction();
  const strat = strategies.data?.find((s) => s.key === key);
  useEffect(() => { if (strat) setParams({ ...strat.params }); }, [key, strategies.data]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (settings.data && !Object.keys(risk).length) setRisk({ ...settings.data.risk_defaults }); }, [settings.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async () => {
    const riskBody: any = {};
    for (const [k] of RISK_FIELDS) riskBody[k] = Number(risk[k]);
    riskBody.exit_before_earnings = !!risk.exit_before_earnings;
    riskBody.allow_fractional = !!risk.allow_fractional;
    const p = Object.fromEntries(Object.entries(params).filter(([k]) => k !== "rules").map(([k, v]) => [k, Number(v)]));
    const e = await act.run(() => post("/api/experiments", {
      name, strategy_key: key, strategy_params: p, starting_capital: capital, risk: riskBody,
      universe: universe.trim() ? universe.split(/[\s,]+/).filter(Boolean) : null,
    }));
    if (e) onCreated(e);
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="grid sm:grid-cols-3 gap-3">
        <Field label="Name"><input value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Strategy">
          <select value={key} onChange={(e) => setKey(e.target.value)}>{(strategies.data || []).filter((s) => s.key !== "custom").map((s) => <option key={s.key} value={s.key}>{s.name}</option>)}</select>
        </Field>
        <Field label="Hypothetical starting capital ($)"><input type="number" min={1000} step={1000} value={capital} onChange={(e) => setCapital(Number(e.target.value))} /></Field>
      </div>
      {strat && <p className="text-mute text-[12px]">{strat.description}</p>}
      {strat && (
        <div className="grid sm:grid-cols-3 gap-3">
          {strat.param_specs.map((p: any) => (
            <Field key={p.name} label={p.name} hint={`${p.description} (default ${p.default})`}>
              <input type="number" step="any" min={p.min ?? undefined} max={p.max ?? undefined} value={params[p.name] ?? ""} onChange={(e) => setParams({ ...params, [p.name]: e.target.value })} />
            </Field>
          ))}
        </div>
      )}
      <details>
        <summary className="cursor-pointer text-[12px] text-mute">Risk tolerance (defaults prioritise capital preservation)</summary>
        <div className="grid sm:grid-cols-3 gap-3 mt-2">
          {RISK_FIELDS.map(([k, label, hint]) => (
            <Field key={k} label={label} hint={hint}><input type="number" step="any" value={risk[k] ?? ""} onChange={(e) => setRisk({ ...risk, [k]: e.target.value })} /></Field>
          ))}
          <label className="flex items-center gap-2 mt-4"><input type="checkbox" checked={!!risk.exit_before_earnings} onChange={(e) => setRisk({ ...risk, exit_before_earnings: e.target.checked })} />Exit before earnings</label>
          <label className="flex items-center gap-2 mt-4"><input type="checkbox" checked={!!risk.allow_fractional} onChange={(e) => setRisk({ ...risk, allow_fractional: e.target.checked })} />Fractional shares</label>
        </div>
        <p className="text-[11px] text-mute mt-2">Fixed rules: long-only U.S. stocks/ETFs, no margin, no leverage, no options, no short selling.</p>
        <Field label="Universe (optional; default = liquid large caps + sector ETFs)"><textarea rows={2} value={universe} onChange={(e) => setUniverse(e.target.value.toUpperCase())} placeholder="AAPL MSFT NVDA …" /></Field>
      </details>
      <ErrorBox error={act.error} />
      <div><Button variant="primary" onClick={submit} disabled={act.busy}>Create experiment</Button></div>
    </div>
  );
}
