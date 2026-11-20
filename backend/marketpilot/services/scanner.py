"""Mode 1 - market monitoring, signals and plain-English alerts.

Jobs (driven by the scheduler, keyed by session phase):
  * full_scan       - every enabled strategy x (universe + watchlists) on completed daily bars.
  * premarket_brief - overnight moves, gaps, today's events, regime.
  * intraday_watch  - trigger hits / invalidations for armed signals, unusual moves and
                      volume, opening-range breakouts, support/resistance tests, late-session moves.
  * manage_watch    - SELL / EXIT and HOLD / MANAGE signals for paper positions.
  * daily_summary   - after the close.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from ..alerts.service import AlertService
from ..data import calendar as cal
from ..data.providers.base import ProviderError
from ..data.service import MarketDataService
from ..data.universe import DEFAULT_UNIVERSE, INDEX_PROXIES, SECTOR_ETFS
from ..db import AppSetting, Decision, Experiment, Signal, Trade, WatchlistItem, session_scope
from ..decision.checklist import summarize
from ..events.calendar import upcoming_events
from ..risk.manager import RiskConfig
from ..strategies.library import create_strategy
from .analysis import AnalysisService, reference_portfolio

log = logging.getLogger(__name__)

DEFAULT_SCANNER = {"strategies": ["trend_pullback", "breakout", "momentum", "mean_reversion"], "use_default_universe": True,
                   "extra_symbols": [], "alert_watch_signals": False, "unusual_move_pct": 4.0, "unusual_rvol": 2.5}


def scanner_settings(s: Any) -> dict[str, Any]:
    row = s.get(AppSetting, "scanner")
    return {**DEFAULT_SCANNER, **(row.value if row else {})}


def watchlist_symbols(s: Any) -> list[str]:
    return sorted({i.symbol for i in s.execute(select(WatchlistItem)).scalars()})


def signal_to_dict(sig: Signal) -> dict[str, Any]:
    return {"id": sig.id, "ts": sig.ts.isoformat(), "symbol": sig.symbol, "category": sig.category,
            "strategy_key": sig.strategy_key, "strategy_version": sig.strategy_version, "price": sig.price,
            "price_ts": sig.price_ts.isoformat(), "data_feed": sig.data_feed, "entry": sig.entry, "stop": sig.stop,
            "target": sig.target, "risk_reward": sig.risk_reward, "summary": sig.summary, "decision_id": sig.decision_id,
            "expires_at": sig.expires_at.isoformat() if sig.expires_at else None}


class Scanner:
    def __init__(self, md: MarketDataService, analysis: AnalysisService, alerts: AlertService) -> None:
        self.md = md
        self.analysis = analysis
        self.alerts = alerts
        self.last_scan: dict[str, Any] | None = None
        self._orb: dict[str, tuple[str, float, float]] = {}

    def universe(self) -> list[str]:
        with session_scope() as s:
            cfg = scanner_settings(s)
            wl = watchlist_symbols(s)
        syms = set(wl) | set(cfg["extra_symbols"])
        if cfg["use_default_universe"]:
            syms |= set(DEFAULT_UNIVERSE)
        return sorted(syms)

    async def full_scan(self, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        with session_scope() as s:
            cfg = scanner_settings(s)
        strategies = [create_strategy(k) for k in cfg["strategies"]]
        strategies = [st for st in strategies if st.timeframe == "1Day"]
        universe = self.universe()
        bars_map = await self.analysis.daily_multi(universe, now)
        try:
            await self.md.get_snapshots(universe)
        except ProviderError:
            pass
        regime = await self.analysis.regime()
        risk_cfg = RiskConfig()
        counts: dict[str, int] = {}
        new_signals = 0
        with session_scope() as s:
            for sym in universe:
                bars = bars_map.get(sym) or []
                if len(bars) < 60:
                    continue
                ctx = self.analysis.context(s, sym, bars, regime, now)
                for st in strategies:
                    proposal, record = await self.analysis.evaluate(s, st, ctx, risk_cfg, reference_portfolio(), now,
                                                                    with_news=False)
                    if proposal is None or record is None:
                        continue
                    cat = record["steps"]["7_decision"]["category"]
                    counts[cat] = counts.get(cat, 0) + 1
                    key = f"{sym}:{st.key}:{cat}:{ctx.tech.get('as_of', '')[:10]}"
                    if s.execute(select(Signal.id).where(Signal.dedupe_key == key)).first():
                        continue
                    dec = Decision(ts=now, symbol=sym, strategy_key=st.key, strategy_version=st.version, category=cat,
                                   approved=cat == "BUY_CANDIDATE", record=record, context="scanner")
                    s.add(dec)
                    s.flush()
                    q = self.md.quotes.get(sym)
                    summary = summarize(record)
                    sig = Signal(ts=now, symbol=sym, category=cat, strategy_key=st.key, strategy_version=st.version,
                                 price=q.price if q else ctx.tech["close"], price_ts=q.exchange_ts if q else bars[-1].t,
                                 data_feed=q.source if q else "daily-close", entry=proposal.entry_price, stop=proposal.stop,
                                 target=proposal.target, risk_reward=round(proposal.reward_risk, 2) if proposal.reward_risk else None,
                                 summary=summary, decision_id=dec.id, dedupe_key=key,
                                 expires_at=_expiry(now, proposal.valid_days))
                    s.add(sig)
                    s.flush()
                    new_signals += 1
                    if cat == "BUY_CANDIDATE" or (cat == "WATCH" and cfg["alert_watch_signals"]):
                        self.alerts.create(s, kind="signal", severity="notice" if cat == "BUY_CANDIDATE" else "info",
                                           symbol=sym, signal_id=sig.id,
                                           title=f"{cat.replace('_', ' ')}: {sym} ({st.name})", body=summary,
                                           dedupe_key=f"signal:{key}", cooldown_minutes=24 * 60)
        self.last_scan = {"at": now.isoformat(), "symbols": len(universe), "counts": counts, "new_signals": new_signals,
                          "strategies": [st.key for st in strategies]}
        self.md.watch(universe)
        return self.last_scan

    async def manage_watch(self, now: datetime | None = None) -> int:
        """SELL / EXIT and HOLD / MANAGE signals for open paper positions (completed daily bars)."""
        now = now or datetime.now(timezone.utc)
        with session_scope() as s:
            trades = list(s.execute(select(Trade).where(Trade.status == "open")).scalars())
            info = [(t.id, t.symbol, t.strategy_key, t.experiment_id) for t in trades]
            params = {e.id: e.strategy_params for e in s.execute(select(Experiment)).scalars()}
        if not info:
            return 0
        bars = await self.analysis.daily_multi(sorted({i[1] for i in info}), now)
        regime = await self.analysis.regime()
        n = 0
        from ..paper.engine import trade_view_for

        with session_scope() as s:
            for tid, sym, skey, exp_id in info:
                trade = s.get(Trade, tid)
                if trade is None or not bars.get(sym):
                    continue
                st = create_strategy(skey, params.get(exp_id))
                ctx = self.analysis.context(s, sym, bars[sym], regime, now)
                instr = st.manage(ctx, trade_view_for(trade, now))
                cat = "SELL_EXIT_CANDIDATE" if (instr and instr.exit_now) else "HOLD_MANAGE"
                text = instr.reason if instr else (f"Holding {sym}: no exit rule triggered on the last completed bar. "
                                                   f"Stop {trade.stop_current:.2f}, target {trade.target_initial or 0:.2f}.")
                key = f"manage:{tid}:{cat}:{ctx.tech.get('as_of', '')[:10]}"
                if s.execute(select(Signal.id).where(Signal.dedupe_key == key)).first():
                    continue
                q = self.md.quotes.get(sym)
                s.add(Signal(ts=now, symbol=sym, category=cat, strategy_key=skey, strategy_version=trade.strategy_version,
                             price=q.price if q else ctx.tech.get("close", 0), price_ts=q.exchange_ts if q else bars[sym][-1].t,
                             data_feed=q.source if q else "daily-close", entry=trade.entry_price, stop=trade.stop_current,
                             target=trade.target_initial, risk_reward=None, summary=text, decision_id=trade.decision_id,
                             dedupe_key=key))
                if cat == "SELL_EXIT_CANDIDATE":
                    self.alerts.create(s, kind="signal", severity="notice", symbol=sym, title=f"SELL / EXIT CANDIDATE: {sym}",
                                       body=text + " (The paper trader applies this rule automatically at the next open.)",
                                       dedupe_key=f"signal:{key}", cooldown_minutes=12 * 60)
                n += 1
        return n

    async def premarket_brief(self, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        syms = sorted(set(INDEX_PROXIES) | set(self.universe()))
        snaps = await self.md.get_snapshots(syms)
        lines = []
        for sym in INDEX_PROXIES:
            sn = snaps.get(sym)
            if sn and sn.change_pct is not None:
                lines.append(f"{sym} {sn.change_pct:+.2f}% vs prior close (last {sn.last_price:.2f}, {sn.feed})")
        gaps = sorted([sn for sn in snaps.values() if sn.change_pct is not None and abs(sn.change_pct) >= 2.0
                       and sn.symbol not in INDEX_PROXIES], key=lambda x: -abs(x.change_pct or 0))[:10]
        with session_scope() as s:
            evs = upcoming_events(s, syms, cal.et_date(now), 0)
            reg = await self.analysis.regime()
            body = "Overnight / pre-market:\n" + ("\n".join(lines) or "No index data") + "\n\n"
            body += "Notable gaps (>=2%):\n" + ("\n".join(f"{g.symbol} {g.change_pct:+.2f}%" for g in gaps) or "None") + "\n\n"
            body += "Today's scheduled events:\n" + ("\n".join(f"{e['time_et'] or ''} {e['name']} {'' if e['symbol']=='*' else e['symbol']}" for e in evs) or "None on file") + "\n\n"
            body += f"Regime: {reg.get('label')} - {reg.get('description', '')}"
            self.alerts.create(s, kind="summary", severity="notice", title=f"Pre-market brief {cal.et_date(now)}", body=body,
                               dedupe_key=f"premarket:{cal.et_date(now)}", cooldown_minutes=12 * 60)

    async def intraday_watch(self, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        phase = cal.session_phase(now)
        with session_scope() as s:
            cfg = scanner_settings(s)
            armed = list(s.execute(select(Signal).where(Signal.category == "BUY_CANDIDATE", Signal.expires_at > now)).scalars())
            wl = watchlist_symbols(s)
        syms = sorted({a.symbol for a in armed} | set(wl) | set(INDEX_PROXIES))
        try:
            snaps = await self.md.get_snapshots(syms)
        except ProviderError:
            return
        today = cal.et_date(now).isoformat()
        with session_scope() as s:
            for sig in armed:
                q = self.md.quotes.get(sig.symbol)
                fresh, _ = self.md.quote_freshness(sig.symbol, now)
                if not q or not fresh or sig.entry is None:
                    continue
                dec = s.get(Decision, sig.decision_id) if sig.decision_id else None
                etype = dec.record["steps"]["6_risk"]["entry_type"] if dec else "buy_stop"
                if sig.stop and q.price <= sig.stop:
                    self.alerts.create(s, kind="signal", severity="info", symbol=sig.symbol,
                                       title=f"Setup invalidated: {sig.symbol}",
                                       body=f"{sig.symbol} traded at {q.price:.2f}, below the invalidation level {sig.stop:.2f} "
                                            f"before triggering. The {sig.strategy_key} idea is void.",
                                       dedupe_key=f"invalid:{sig.id}", cooldown_minutes=24 * 60)
                    db_sig = s.get(Signal, sig.id)
                    if db_sig:
                        db_sig.expires_at = now
                elif (etype == "buy_stop" and q.price >= sig.entry) or (etype == "limit" and q.price <= sig.entry):
                    self.alerts.create(s, kind="signal", severity="warning", symbol=sig.symbol,
                                       title=f"Trigger hit: {sig.symbol} {q.price:.2f} (BUY CANDIDATE active)",
                                       body=f"{sig.summary}\n\nLive price {q.price:.2f} at {q.exchange_ts.isoformat()} ({q.source}). "
                                            "Re-check spread and news before acting. Paper trading only by default.",
                                       dedupe_key=f"trigger:{sig.id}", cooldown_minutes=24 * 60)
            for sym, sn in snaps.items():
                if sn.change_pct is None or sym in INDEX_PROXIES:
                    continue
                if abs(sn.change_pct) >= cfg["unusual_move_pct"]:
                    self.alerts.create(s, kind="market", severity="info", symbol=sym,
                                       title=f"Unusual move: {sym} {sn.change_pct:+.1f}%",
                                       body=f"{sym} is {sn.change_pct:+.2f}% today at {sn.last_price:.2f} ({sn.feed}). "
                                            "Check news before treating this as a setup.",
                                       dedupe_key=f"move:{sym}:{today}:{int(sn.change_pct // 2)}", cooldown_minutes=180)
                st = cal.session_times(cal.et_date(now))
                if phase == "opening" or not st:
                    continue
                # Opening range (first 30 minutes) breakouts for watchlist names
                if sym in wl and sn.day_high and sn.day_low:
                    orb = self._orb.get(sym)
                    if orb is None or orb[0] != today:
                        self._orb[sym] = (today, sn.day_high, sn.day_low)
                        continue
                    _, orh, orl = orb
                    if sn.last_price and sn.last_price > orh * 1.001:
                        self.alerts.create(s, kind="market", severity="info", symbol=sym,
                                           title=f"Opening-range breakout: {sym}",
                                           body=f"{sym} {sn.last_price:.2f} broke above its opening range high {orh:.2f}.",
                                           dedupe_key=f"orb_up:{sym}:{today}", cooldown_minutes=24 * 60)
                    elif sn.last_price and sn.last_price < orl * 0.999:
                        self.alerts.create(s, kind="market", severity="info", symbol=sym,
                                           title=f"Opening-range breakdown: {sym}",
                                           body=f"{sym} {sn.last_price:.2f} fell below its opening range low {orl:.2f}.",
                                           dedupe_key=f"orb_dn:{sym}:{today}", cooldown_minutes=24 * 60)
                if phase == "power_hour" and sym in wl and sn.last_price and sn.day_high and sn.prev_close:
                    if sn.last_price >= sn.day_high * 0.998 and sn.last_price > sn.prev_close:
                        self.alerts.create(s, kind="market", severity="info", symbol=sym,
                                           title=f"Closing-range strength: {sym}",
                                           body=f"{sym} trades within 0.2% of its high of day ({sn.day_high:.2f}) in the final hour.",
                                           dedupe_key=f"closestrength:{sym}:{today}", cooldown_minutes=24 * 60)

    async def daily_summary(self, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        from ..paper.accounting import equity

        try:
            snaps = await self.md.get_snapshots(sorted(set(INDEX_PROXIES) | set(SECTOR_ETFS)))
        except ProviderError:
            snaps = {}
        start = datetime.combine(cal.et_date(now), datetime.min.time(), tzinfo=cal.ET).astimezone(timezone.utc)
        with session_scope() as s:
            sig_counts = dict(s.execute(select(Signal.category, func.count(Signal.id)).where(Signal.ts >= start)
                                        .group_by(Signal.category)).all())
            lines = [f"{k} {snaps[k].change_pct:+.2f}%" for k in INDEX_PROXIES if k in snaps and snaps[k].change_pct is not None]
            secs = sorted([(k, snaps[k].change_pct) for k in SECTOR_ETFS if k in snaps and snaps[k].change_pct is not None],
                          key=lambda kv: -(kv[1] or 0))
            exp_lines = []
            for exp in s.execute(select(Experiment).where(Experiment.archived.is_(False), Experiment.started_at.is_not(None))).scalars():
                eq, _ = equity(s, exp)
                day = eq - (exp.day_start_equity or eq)
                exp_lines.append(f"{exp.name}: equity {eq:,.2f} ({day:+,.2f} today, {(eq / exp.starting_capital - 1) * 100:+.2f}% total) [{exp.status}]")
            evs = upcoming_events(s, None, cal.et_date(now) + timedelta(days=1), 3)
            body = ("Market (ETF proxies): " + (", ".join(lines) or "n/a") + "\n"
                    "Sectors: " + (", ".join(f"{k} {v:+.1f}%" for k, v in secs) or "n/a") + "\n\n"
                    "Signals today: " + (", ".join(f"{k} {v}" for k, v in sig_counts.items()) or "none") + "\n\n"
                    "Paper trading (hypothetical):\n" + ("\n".join(exp_lines) or "No experiments started") + "\n\n"
                    "Next 3 days: " + ("; ".join(f"{e['date']} {e['name']} {'' if e['symbol']=='*' else e['symbol']}" for e in evs[:12]) or "none on file"))
            self.alerts.create(s, kind="summary", severity="notice", title=f"Daily summary {cal.et_date(now)}", body=body,
                               dedupe_key=f"daily:{cal.et_date(now)}", cooldown_minutes=12 * 60)


def _expiry(now: datetime, valid_days: int) -> datetime:
    from ..paper.engine import expiry_after_sessions

    return expiry_after_sessions(now, valid_days)

