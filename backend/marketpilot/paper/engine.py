"""Autonomous paper-trading engine (hypothetical money only).

Lifecycle of a trade:
  1. After the close (and at startup before the open), each running experiment's
     strategy scans its universe on COMPLETED daily bars. Every proposal gets a full
     checklist record (approved or not). Approved proposals become armed
     PendingSetups with a trigger price and an expiry.
  2. During the regular session the engine watches live prices. When a trigger
     hits, the checklist is re-run with fresh data and the Risk Manager must
     approve again; only then is a simulated order created (idempotent client
     order id), filled by the ExecutionSimulator after the latency delay, and booked.
  3. Open positions are marked to market continuously; stops/targets are checked
     on live prices; strategy exit rules that depend on the daily close are
     evaluated at the next session open on completed bars (no look-ahead);
     earnings exits happen before the event; intraday strategies flatten at 15:50 ET.
  4. On exit, a deterministic post-trade review is attached to the trade.

Safety: stale data -> automatic pause (no actions) until data is healthy again;
daily loss limit -> experiment halted for the rest of the session; emergency STOP
-> all experiments halted, working orders/setups cancelled, optional flatten.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..alerts.service import AlertService
from ..data import calendar as cal
from ..data.service import MarketDataService
from ..data.universe import BENCHMARK, DEFAULT_UNIVERSE
from ..db import (
    AppSetting,
    Decision,
    EquitySnapshot,
    Experiment,
    Order,
    PendingSetup,
    Position,
    Trade,
    audit,
    session_scope,
    utcnow,
)
from ..decision.review import review_trade
from ..risk.manager import PortfolioState, RiskConfig, RiskManager
from ..services.analysis import AnalysisService
from ..strategies.base import TradeView
from ..strategies.library import create_strategy
from .accounting import AccountingError, apply_entry_fill, apply_exit_fill, equity, mark_position, open_positions
from .execution import ExecutionConfig, ExecutionSimulator, QuoteView

log = logging.getLogger(__name__)


def exp_risk_config(exp: Experiment) -> RiskConfig:
    return RiskConfig.from_dict((exp.risk_config or {}).get("risk"))


def exp_exec_config(exp: Experiment) -> ExecutionConfig:
    return ExecutionConfig.from_dict((exp.risk_config or {}).get("execution"))


def exp_strategy(exp: Experiment):  # type: ignore[no-untyped-def]
    return create_strategy(exp.strategy_key, exp.strategy_params)


def sessions_held(entry_ts: datetime, now: datetime) -> int:
    d0, d1 = cal.et_date(entry_ts), cal.et_date(now)
    return len([d for d in cal.trading_days_between(d0 + timedelta(days=1), d1)])


def trade_view_for(trade: Trade, now: datetime) -> TradeView:
    return TradeView(trade.symbol, trade.entry_price, trade.entry_ts, trade.stop_initial, trade.stop_current,
                     trade.target_initial, sessions_held(trade.entry_ts, now), trade.max_hold_days,
                     trade.mfe or trade.entry_price)


def expiry_after_sessions(now: datetime, n: int) -> datetime:
    d = cal.et_date(now)
    st = cal.session_times(d)
    if st is None or now >= st.close:
        d = cal.next_trading_day(d)
    for _ in range(max(n, 1) - 1):
        d = cal.next_trading_day(d)
    st2 = cal.session_times(d)
    assert st2 is not None
    return st2.close


def get_kill_switch(s: Session) -> dict[str, Any]:
    row = s.get(AppSetting, "kill_switch")
    return row.value if row else {"active": False}


class PaperEngine:
    def __init__(self, md: MarketDataService, analysis: AnalysisService, alerts: AlertService,
                 real_time: bool = True) -> None:
        self.real_time = real_time  # False in tests/replays: latency is modelled without sleeping
        self.md = md
        self.analysis = analysis
        self.alerts = alerts
        self.auto_paused: dict[int, str] = {}
        self.last_tick: datetime | None = None
        self._healthy_streak = 0
        self._lock = asyncio.Lock()
        self._done: dict[str, str] = {}  # job -> ET date last run

    # ------------------------------------------------------------- helpers
    def _quote_view(self, symbol: str, now: datetime) -> QuoteView:
        q = self.md.quotes.get(symbol)
        fresh, reason = self.md.quote_freshness(symbol, now)
        if q is None:
            return QuoteView(None, None, None, None, None, None, False, reason)
        return QuoteView(q.price, q.bid, q.ask, q.bid_size, q.ask_size, q.exchange_ts, fresh, reason)

    def portfolio_state(self, s: Session, exp: Experiment) -> PortfolioState:
        eq, _ = equity(s, exp)
        pending = [o.symbol for o in s.execute(select(Order).where(
            Order.experiment_id == exp.id, Order.purpose == "entry",
            Order.status.in_(("new", "partially_filled")))).scalars()]
        return PortfolioState(exp.starting_capital, exp.cash, eq, exp.day_start_equity or eq,
                              [p.symbol for p in open_positions(s, exp.id)], pending,
                              halted=exp.status == "halted", halted_reason=exp.halted_reason)

    def watched_symbols(self) -> set[str]:
        syms: set[str] = {BENCHMARK}
        with session_scope() as s:
            for exp in s.execute(select(Experiment).where(Experiment.status.in_(("running", "paused", "halted")))).scalars():
                syms |= set(p.symbol for p in open_positions(s, exp.id))
                syms |= {ps.symbol for ps in s.execute(select(PendingSetup).where(
                    PendingSetup.experiment_id == exp.id, PendingSetup.status == "armed")).scalars()}
        return syms

    # --------------------------------------------------------------- the tick
    async def tick(self, now: datetime | None = None) -> None:
        async with self._lock:
            now = now or datetime.now(timezone.utc)
            self.last_tick = now
            self.md.watch(self.watched_symbols())
            healthy, reason = self.md.is_feed_healthy(now)
            self._healthy_streak = self._healthy_streak + 1 if healthy else 0
            with session_scope() as s:
                kill = get_kill_switch(s)
                # Every non-archived experiment with open positions is managed (stops stay active even when
                # paused/stopped/halted); only 'running' experiments may open new positions.
                exps = list(s.execute(select(Experiment).where(Experiment.archived.is_(False))).scalars())
                ids = [e.id for e in exps if e.status in ("running", "paused", "halted") or open_positions(s, e.id)]
            if kill.get("active"):
                await self._process_flatten_queue(now)
                return
            for exp_id in ids:
                try:
                    await self._tick_experiment(exp_id, now, healthy, reason)
                except Exception:
                    log.exception("tick failed for experiment %s", exp_id)

    async def _tick_experiment(self, exp_id: int, now: datetime, healthy: bool, reason: str) -> None:
        regular = cal.is_regular_session(now)
        with session_scope() as s:
            exp = s.get(Experiment, exp_id)
            assert exp is not None
            # --- automatic pause on stale/unavailable data
            # Pause immediately on unhealthy data; once paused, require 2 consecutive healthy checks to resume.
            if not healthy or (exp_id in self.auto_paused and self._healthy_streak < 2):
                if regular and exp_id not in self.auto_paused and exp.status == "running":
                    self.auto_paused[exp_id] = reason
                    audit(s, "engine", "auto_pause_stale_data", exp_id, reason=reason)
                    self.alerts.create(s, kind="risk", severity="warning", title=f"{exp.name}: paused (market data stale)",
                                       body=f"Autonomous trading paused automatically: {reason}. It resumes when data is healthy.",
                                       dedupe_key=f"autopause:{exp_id}", cooldown_minutes=60)
                return
            if exp_id in self.auto_paused:
                audit(s, "engine", "auto_resume_data_healthy", exp_id, previous_reason=self.auto_paused.pop(exp_id))
            # --- new session bookkeeping
            today = cal.et_date(now).isoformat()
            if regular and exp.day_start_date != today:
                self._mark_all(s, exp, now)
                exp.day_start_equity, _ = equity(s, exp)
                exp.day_start_date = today
                if exp.status == "halted" and (exp.halted_reason or "").startswith("daily_loss"):
                    exp.status, exp.halted_reason = "running", None
                    audit(s, "engine", "daily_loss_halt_cleared_new_session", exp_id)
            if not regular:
                return
            self._mark_all(s, exp, now)
            rm = RiskManager(exp_risk_config(exp))
            pf = self.portfolio_state(s, exp)
            if exp.status == "running" and rm.daily_loss_breached(pf):
                exp.status = "halted"
                exp.halted_reason = f"daily_loss:{today}: equity change {pf.equity - pf.day_start_equity:,.2f}"
                audit(s, "risk_manager", "halt_daily_loss", exp_id, equity=pf.equity, day_start=pf.day_start_equity)
                self.alerts.create(s, kind="risk", severity="critical", title=f"{exp.name}: daily loss limit hit",
                                   body=f"Hypothetical P&L today {pf.equity - pf.day_start_equity:,.2f} breached the "
                                        f"{exp_risk_config(exp).max_daily_loss_pct}% limit. No new entries today; existing stops remain active.",
                                   dedupe_key=f"dailyloss:{exp_id}:{today}")
        await self._manage_positions(exp_id, now)
        await self._work_orders(exp_id, now)
        with session_scope() as s:
            exp = s.get(Experiment, exp_id)
            assert exp is not None
            status = exp.status
        if status == "running":
            await self._check_triggers(exp_id, now)

    def _mark_all(self, s: Session, exp: Experiment, now: datetime) -> None:
        for pos in open_positions(s, exp.id):
            q = self.md.quotes.get(pos.symbol)
            if q:
                trade = s.get(Trade, pos.trade_id)
                assert trade is not None
                mark_position(pos, trade, q.price, q.exchange_ts)

    # ------------------------------------------------------ position management
    async def _manage_positions(self, exp_id: int, now: datetime) -> None:
        et_now = cal.to_et(now)
        with session_scope() as s:
            exp = s.get(Experiment, exp_id)
            assert exp is not None
            strategy = exp_strategy(exp)
            cfg = exp_risk_config(exp)
            positions = open_positions(s, exp_id)
            daily_check_due = et_now.time() >= time(9, 35) and self._done.get(f"daily_manage:{exp_id}") != et_now.date().isoformat()
            symbols = [p.symbol for p in positions]
        bars_map = await self.analysis.daily_multi(symbols, now) if (positions and daily_check_due) else {}
        regime = await self.analysis.regime() if bars_map else {}
        with session_scope() as s:
            exp = s.get(Experiment, exp_id)
            assert exp is not None
            for pos in open_positions(s, exp_id):
                trade = s.get(Trade, pos.trade_id)
                assert trade is not None
                q = self.md.quotes.get(pos.symbol)
                fresh, _ = self.md.quote_freshness(pos.symbol, now)
                if q is None or not fresh:
                    continue
                price = q.price
                view = trade_view_for(trade, now)
                if price <= trade.stop_current:
                    rule = "stop" if trade.stop_current <= trade.stop_initial + 1e-9 else "trail"
                    await self._exit(s, exp, pos, trade, f"Stop {trade.stop_current:.2f} hit (last {price:.2f})", rule, now)
                    continue
                if trade.target_initial and price >= trade.target_initial:
                    await self._exit(s, exp, pos, trade, f"Target {trade.target_initial:.2f} reached (last {price:.2f})",
                                     "target", now, limit=trade.target_initial)
                    continue
                if strategy.holding == "intraday" and et_now.time() >= time(15, 50):
                    await self._exit(s, exp, pos, trade, "Intraday strategy: flat before the close", "eod", now)
                    continue
                if cfg.exit_before_earnings and et_now.time() >= time(15, 45):
                    ev = self._earnings_tomorrow_or_tonight(s, pos.symbol, now)
                    if ev:
                        await self._exit(s, exp, pos, trade, f"Exit before earnings on {ev['date']} ({ev.get('time_et') or 'n/a'})",
                                         "earnings", now)
                        continue
                if pos.symbol in bars_map:
                    ctx = self.analysis.context(s, pos.symbol, bars_map[pos.symbol], regime, now)
                    instr = strategy.manage(ctx, view)
                else:
                    instr = None
                    # continuous breakeven management from live highs
                    r = trade.entry_price - trade.stop_initial
                    if r > 0 and (trade.mfe or 0) >= trade.entry_price + r and trade.stop_current < trade.entry_price \
                            and strategy.key not in ("mean_reversion",):
                        trade.stop_current = round(trade.entry_price, 4)
                        audit(s, "engine", "stop_to_breakeven", exp.id, trade_id=trade.id, stop=trade.stop_current)
                if instr is not None:
                    if instr.new_stop is not None and not instr.exit_now:
                        if instr.new_stop > trade.stop_current:  # stops only ever tighten
                            trade.stop_current = instr.new_stop
                            audit(s, "engine", "stop_tightened", exp.id, trade_id=trade.id, stop=instr.new_stop, reason=instr.reason)
                    elif instr.exit_now:
                        await self._exit(s, exp, pos, trade, instr.reason, instr.rule, now)
            if daily_check_due and bars_map:
                self._done[f"daily_manage:{exp_id}"] = et_now.date().isoformat()

    def _earnings_tomorrow_or_tonight(self, s: Session, symbol: str, now: datetime) -> dict[str, Any] | None:
        from ..events.calendar import upcoming_events

        events = upcoming_events(s, [symbol], cal.et_date(now), 5)
        today = cal.et_date(now)
        nxt = cal.next_trading_day(today)
        for ev in events:
            if ev["kind"] != "earnings" or ev["symbol"] != symbol:
                continue
            d = datetime.fromisoformat(ev["date"]).date()
            if (d == today and ev.get("time_et") != "bmo") or (d == nxt and ev.get("time_et") in ("bmo", None, "dmh")):
                return ev
            if d == nxt and ev.get("time_et") == "amc":
                continue
        return None

    async def _exit(self, s: Session, exp: Experiment, pos: Position, trade: Trade, reason: str, rule: str,
                    now: datetime, limit: float | None = None) -> None:
        existing = s.execute(select(Order).where(Order.experiment_id == exp.id, Order.trade_id == trade.id,
                                                 Order.side == "sell", Order.status.in_(("new", "partially_filled")))).scalar_one_or_none()
        if existing is not None:
            return  # an exit is already working; never double-sell
        n = s.execute(select(Order).where(Order.trade_id == trade.id, Order.side == "sell")).scalars().all()
        order = Order(experiment_id=exp.id, client_order_id=f"exit:{trade.id}:{len(n) + 1}", symbol=pos.symbol,
                      side="sell", order_type="limit" if limit else "market", qty=pos.qty, limit_price=limit,
                      purpose=rule, status="new", trade_id=trade.id, created_at=now, updated_at=now)
        s.add(order)
        s.flush()
        await self._fill_order(s, exp, order, now, exit_reason=reason)

    # --------------------------------------------------------------- entries
    async def _check_triggers(self, exp_id: int, now: datetime) -> None:
        with session_scope() as s:
            setups = list(s.execute(select(PendingSetup).where(PendingSetup.experiment_id == exp_id,
                                                               PendingSetup.status == "armed")).scalars())
            for ps in setups:
                if now >= ps.expires_at:
                    ps.status = "expired"
                    audit(s, "engine", "setup_expired", exp_id, setup_id=ps.id, symbol=ps.symbol)
            setups = [ps for ps in setups if ps.status == "armed"]
            info = [(ps.id, ps.symbol, ps.trigger_price, ps.stop, ps.decision_id) for ps in setups]
        for setup_id, symbol, trigger, stop, decision_id in info:
            q = self.md.quotes.get(symbol)
            fresh, _ = self.md.quote_freshness(symbol, now)
            if q is None or not fresh:
                continue
            with session_scope() as s:
                d = s.get(Decision, decision_id)
                assert d is not None
                entry_type = d.record["steps"]["6_risk"]["entry_type"]
            if q.price <= stop:
                with session_scope() as s:
                    ps = s.get(PendingSetup, setup_id)
                    assert ps is not None
                    ps.status = "cancelled"
                    audit(s, "engine", "setup_invalidated_before_trigger", exp_id, setup_id=setup_id, price=q.price)
                continue
            hit = (entry_type == "buy_stop" and q.price >= trigger) or \
                  (entry_type == "limit" and (q.ask or q.price) <= trigger) or entry_type == "market"
            if hit:
                await self._enter(exp_id, setup_id, now)

    async def _enter(self, exp_id: int, setup_id: int, now: datetime) -> None:
        with session_scope() as s:
            exp = s.get(Experiment, exp_id)
            ps = s.get(PendingSetup, setup_id)
            assert exp is not None and ps is not None
            if ps.status != "armed" or exp.status != "running":
                return  # already triggered/cancelled: never enter twice
            symbol = ps.symbol
        bars = await self.analysis.daily(symbol, now)
        regime = await self.analysis.regime()
        with session_scope() as s:
            exp = s.get(Experiment, exp_id)
            ps = s.get(PendingSetup, setup_id)
            assert exp is not None and ps is not None
            strategy = exp_strategy(exp)
            cfg = exp_risk_config(exp)
            ctx = self.analysis.context(s, symbol, bars, regime, now)
            proposal = strategy.evaluate(ctx)
            setup_rec = s.get(Decision, ps.decision_id).record  # type: ignore[union-attr]
            # The trigger is evaluated on the ARMED plan (computed on the prior completed bar);
            # re-evaluate risk with live data. If today's bars changed the setup, keep the armed levels.
            from ..strategies.base import SetupProposal

            r6 = setup_rec["steps"]["6_risk"]
            plan = SetupProposal(symbol, strategy.key, strategy.version, setup_rec["steps"]["3_thesis"]["thesis"],
                                 setup_rec["steps"]["4_evidence"]["supporting"], r6["entry_type"], r6["entry"], r6["stop"],
                                 r6["target"], setup_rec["steps"]["5_challenge"]["what_would_prove_it_wrong"],
                                 r6["time_stop_days"], r6.get("valid_days", 2), r6.get("holding", "swing"))
            pf = self.portfolio_state(s, exp)
            market = self.analysis.market_state(s, ctx, now, bool(get_kill_switch(s).get("active")))
            q = self.md.quotes.get(symbol)
            entry_ref = q.ask if (q and q.ask) else (q.price if q else plan.entry_price)
            verdict = RiskManager(cfg).evaluate_entry(symbol, max(entry_ref, plan.entry_price) if plan.entry_type == "buy_stop" else entry_ref,
                                                      plan.stop, plan.target, plan.holding, pf, market)
            from ..decision.checklist import TIMING_RULES, build_decision, quant_view

            record = build_decision(ctx, strategy, plan, cfg, verdict, self.md.provider.quality(),
                                    quant_view(s, strategy.key, strategy.version), await self.analysis.news(symbol),
                                    pf.open_symbols, q.price if q else None, q.exchange_ts if q else None)
            record["trigger"] = {"setup_decision_id": ps.decision_id, "setup_id": ps.id, "trigger_price": ps.trigger_price,
                                 "triggered_at": now.isoformat(), "live_price": q.price if q else None,
                                 "setup_still_valid_on_latest_bar": proposal is not None}
            approved = verdict.approved and record["steps"]["7_decision"]["category"] == "BUY_CANDIDATE"
            dec = Decision(ts=now, experiment_id=exp.id, symbol=symbol, strategy_key=strategy.key,
                           strategy_version=strategy.version, category=record["steps"]["7_decision"]["category"],
                           approved=approved, record=record, context="paper")
            s.add(dec)
            s.flush()
            if not approved:
                failed = [c.rule for c in verdict.checks if c.blocking and not c.passed]
                if failed and all(r in TIMING_RULES for r in failed):
                    audit(s, "risk_manager", "entry_deferred_timing", exp.id, symbol=symbol, rules=failed, decision_id=dec.id)
                else:
                    ps.status = "cancelled"
                    audit(s, "risk_manager", "entry_rejected", exp.id, symbol=symbol, reasons=verdict.reasons, decision_id=dec.id)
                return
            ps.status = "triggered"
            order = Order(experiment_id=exp.id, client_order_id=f"entry:{exp.id}:{ps.id}", symbol=symbol, side="buy",
                          order_type="market", qty=verdict.qty, purpose="entry", status="new", decision_id=dec.id,
                          created_at=now, updated_at=now)
            s.add(order)
            try:
                s.flush()
            except Exception:
                s.rollback()
                log.warning("duplicate entry prevented for setup %s", setup_id)
                return
            meta = {"stop": plan.stop, "target": plan.target, "time_stop": plan.time_stop_days}
            order_id = order.id
        # Simulated network/exchange latency, then fill against the then-current quote.
        latency = exp_exec_config(exp).latency_ms / 1000
        if self.real_time:
            await asyncio.sleep(latency)
        with session_scope() as s:
            exp = s.get(Experiment, exp_id)
            order = s.get(Order, order_id)
            assert exp is not None and order is not None
            await self._fill_order(s, exp, order, now + timedelta(seconds=latency), entry_meta=meta)

    async def _fill_order(self, s: Session, exp: Experiment, order: Order, now: datetime,
                          entry_meta: dict[str, Any] | None = None, exit_reason: str | None = None) -> None:
        sim = ExecutionSimulator(exp_exec_config(exp))
        qv = self._quote_view(order.symbol, now)
        remaining = round(order.qty - order.filled_qty, 6)
        res = sim.simulate(order.side, remaining, order.order_type, qv, order.limit_price)
        if res.status in ("rejected",):
            order.reject_reason = res.reason
            if order.purpose == "entry":
                order.status = "rejected" if order.filled_qty == 0 else "partially_filled"
                audit(s, "broker_sim", "order_rejected", exp.id, order=order.client_order_id, reason=res.reason)
            return  # exits stay working and are retried on the next tick
        if res.status == "not_marketable":
            return
        if order.side == "buy":
            decision = s.get(Decision, order.decision_id) if order.decision_id else None
            meta = entry_meta or {}
            if not meta and decision:
                r6 = decision.record["steps"]["6_risk"]
                meta = {"stop": r6["stop"], "target": r6["target"], "time_stop": r6["time_stop_days"]}
            try:
                trade = apply_entry_fill(s, exp, order, res.qty, res.price, res.fees, res.reference_price or res.price,  # type: ignore[arg-type]
                                         now, res.model, strategy_key=exp.strategy_key, strategy_version=exp.strategy_version,
                                         stop=meta["stop"], target=meta.get("target"), max_hold_days=meta.get("time_stop") or None,
                                         decision_id=order.decision_id)
            except AccountingError as e:
                order.status, order.reject_reason = "rejected", str(e)
                return
            self.alerts.create(s, kind="trade", severity="notice", symbol=order.symbol,
                               title=f"[PAPER] {exp.name}: bought {res.qty:g} {order.symbol} @ {res.price:.2f}",
                               body=f"Simulated entry. Stop {trade.stop_initial:.2f}, target {trade.target_initial or 0:.2f}. "
                                    f"Fees {res.fees:.2f}. Open Trade Review #{trade.id} for the full rationale.",
                               dedupe_key=f"fill:{order.client_order_id}:{order.filled_qty}", cooldown_minutes=1)
        else:
            trade = apply_exit_fill(s, exp, order, res.qty, res.price, res.fees, res.reference_price or res.price,  # type: ignore[arg-type]
                                    now, res.model, exit_reason or order.purpose)
            if trade.status == "closed":
                decision = s.get(Decision, trade.decision_id) if trade.decision_id else None
                trade.review = review_trade(trade, decision.record if decision else None, order.purpose)
                self.alerts.create(s, kind="trade", severity="notice", symbol=order.symbol,
                                   title=f"[PAPER] {exp.name}: sold {order.symbol} @ {trade.exit_price:.2f} ({trade.net_pnl:+.2f})",
                                   body=f"Exit reason: {trade.exit_reason}. Result {trade.r_multiple if trade.r_multiple is not None else 'n/a'}R. "
                                        f"Review: {trade.review['decision_quality']}.",
                                   dedupe_key=f"close:{trade.id}", cooldown_minutes=1)

    async def _work_orders(self, exp_id: int, now: datetime) -> None:
        with session_scope() as s:
            exp = s.get(Experiment, exp_id)
            assert exp is not None
            working = list(s.execute(select(Order).where(Order.experiment_id == exp_id,
                                                         Order.status.in_(("new", "partially_filled")))).scalars())
            for o in working:
                if o.purpose == "entry" and (now - o.created_at) > timedelta(minutes=10):
                    o.status = "cancelled" if o.filled_qty == 0 else "filled"  # keep partial fill, cancel remainder
                    o.qty = o.filled_qty if o.filled_qty else o.qty
                    audit(s, "engine", "entry_remainder_cancelled", exp_id, order=o.client_order_id)
                    continue
                await self._fill_order(s, exp, o, now, exit_reason=None if o.side == "buy" else o.purpose)

    # ------------------------------------------------------- setup generation
    async def generate_setups(self, exp_id: int, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        with session_scope() as s:
            exp = s.get(Experiment, exp_id)
            assert exp is not None
            strategy = exp_strategy(exp)
            universe = list(exp.universe or DEFAULT_UNIVERSE)
            cfg = exp_risk_config(exp)
            if strategy.timeframe != "1Day":
                return {"skipped": "intraday strategy evaluates during the session"}
        bars_map = await self.analysis.daily_multi(universe, now)
        regime = await self.analysis.regime()
        created, evaluated, proposals = 0, 0, 0
        with session_scope() as s:
            exp = s.get(Experiment, exp_id)
            assert exp is not None
            # disarm stale setups from previous scans
            for ps in s.execute(select(PendingSetup).where(PendingSetup.experiment_id == exp_id,
                                                           PendingSetup.status == "armed")).scalars():
                ps.status = "expired" if now >= ps.expires_at else ps.status
            pf = self.portfolio_state(s, exp)
            kill = bool(get_kill_switch(s).get("active"))
            for sym in universe:
                bars = bars_map.get(sym) or []
                if len(bars) < 60:
                    continue
                evaluated += 1
                ctx = self.analysis.context(s, sym, bars, regime, now)
                proposal, record = await self.analysis.evaluate(s, strategy, ctx, cfg, pf, now, kill, with_news=False)
                if proposal is None or record is None:
                    continue
                proposals += 1
                cat = record["steps"]["7_decision"]["category"]
                dec = Decision(ts=now, experiment_id=exp_id, symbol=sym, strategy_key=strategy.key,
                               strategy_version=strategy.version, category=cat, approved=cat == "BUY_CANDIDATE",
                               record=record, context="paper")
                s.add(dec)
                s.flush()
                if cat == "BUY_CANDIDATE" and sym not in pf.open_symbols:
                    dup = s.execute(select(PendingSetup).where(PendingSetup.experiment_id == exp_id, PendingSetup.symbol == sym,
                                                               PendingSetup.status == "armed")).scalar_one_or_none()
                    if dup is None:
                        s.add(PendingSetup(experiment_id=exp_id, symbol=sym, decision_id=dec.id,
                                           trigger_price=proposal.entry_price, stop=proposal.stop, target=proposal.target,
                                           created_at=now, expires_at=expiry_after_sessions(now, proposal.valid_days)))
                        created += 1
            audit(s, "engine", "setups_generated", exp_id, evaluated=evaluated, proposals=proposals, armed=created)
        return {"evaluated": evaluated, "proposals": proposals, "armed": created}

    async def intraday_scan(self, exp_id: int, now: datetime) -> None:
        """For intraday strategies (5-minute bars): evaluate and arm 'market' setups immediately."""
        with session_scope() as s:
            exp = s.get(Experiment, exp_id)
            assert exp is not None
            strategy = exp_strategy(exp)
            if strategy.timeframe == "1Day" or exp.status != "running":
                return
            universe = list(exp.universe or DEFAULT_UNIVERSE)[:30]
            cfg = exp_risk_config(exp)
        daily = await self.analysis.daily_multi(universe, now)
        intraday = await self.md.get_bars_multi(universe, "5Min", timedelta(days=2))
        regime = await self.analysis.regime()
        with session_scope() as s:
            exp = s.get(Experiment, exp_id)
            assert exp is not None
            pf = self.portfolio_state(s, exp)
            for sym in universe:
                if sym in pf.open_symbols or len(daily.get(sym, [])) < 60:
                    continue
                ctx = self.analysis.context(s, sym, daily[sym], regime, now, intraday.get(sym))
                proposal, record = await self.analysis.evaluate(s, strategy, ctx, cfg, pf, now, with_news=False)
                if not proposal or not record or record["steps"]["7_decision"]["category"] != "BUY_CANDIDATE":
                    continue
                dec = Decision(ts=now, experiment_id=exp_id, symbol=sym, strategy_key=strategy.key,
                               strategy_version=strategy.version, category="BUY_CANDIDATE", approved=True,
                               record=record, context="paper")
                s.add(dec)
                s.flush()
                if not s.execute(select(PendingSetup).where(PendingSetup.experiment_id == exp_id, PendingSetup.symbol == sym,
                                                            PendingSetup.status == "armed")).first():
                    s.add(PendingSetup(experiment_id=exp_id, symbol=sym, decision_id=dec.id, trigger_price=proposal.entry_price,
                                       stop=proposal.stop, target=proposal.target, created_at=now,
                                       expires_at=now + timedelta(minutes=15)))

    # ------------------------------------------------------------ snapshots
    def snapshot_equity(self, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        spy = self.md.quotes.get(BENCHMARK)
        with session_scope() as s:
            for exp in s.execute(select(Experiment).where(Experiment.archived.is_(False),
                                                          Experiment.started_at.is_not(None))).scalars():
                self._mark_all(s, exp, now)
                eq, pv = equity(s, exp)
                s.add(EquitySnapshot(experiment_id=exp.id, ts=now, equity=round(eq, 2), cash=round(exp.cash, 2),
                                     positions_value=round(pv, 2), benchmark_price=spy.price if spy else None))

    # ------------------------------------------------------- emergency stop
    async def emergency_stop(self, flatten: bool, actor: str = "user") -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        with session_scope() as s:
            s.merge(AppSetting(key="kill_switch", value={"active": True, "at": now.isoformat(), "flatten": flatten}))
            n_exp = 0
            for exp in s.execute(select(Experiment).where(Experiment.status.in_(("running", "paused")))).scalars():
                exp.status, exp.halted_reason = "halted", "emergency_stop"
                n_exp += 1
            for o in s.execute(select(Order).where(Order.status.in_(("new", "partially_filled")), Order.side == "buy")).scalars():
                o.status = "cancelled"
            for ps in s.execute(select(PendingSetup).where(PendingSetup.status == "armed")).scalars():
                ps.status = "cancelled"
            audit(s, actor, "emergency_stop", None, flatten=flatten, experiments=n_exp)
            self.alerts.create(s, kind="risk", severity="critical", title="EMERGENCY STOP activated",
                               body=f"All paper trading halted ({n_exp} experiments). Flatten positions: {flatten}.",
                               dedupe_key=f"kill:{now.isoformat()}", cooldown_minutes=0)
        if flatten:
            await self._process_flatten_queue(now)
        return {"halted_experiments": n_exp, "flatten": flatten}

    async def _process_flatten_queue(self, now: datetime) -> None:
        with session_scope() as s:
            ks = get_kill_switch(s)
            if not ks.get("flatten") or not cal.is_regular_session(now):
                return
            for exp in s.execute(select(Experiment)).scalars():
                for pos in open_positions(s, exp.id):
                    trade = s.get(Trade, pos.trade_id)
                    assert trade is not None
                    await self._exit(s, exp, pos, trade, "Emergency STOP: flatten", "manual", now)

    def clear_emergency_stop(self, actor: str = "user") -> None:
        with session_scope() as s:
            s.merge(AppSetting(key="kill_switch", value={"active": False, "cleared_at": utcnow().isoformat()}))
            audit(s, actor, "emergency_stop_cleared")

    # ---------------------------------------------------------- status/report
    def status(self) -> dict[str, Any]:
        with session_scope() as s:
            ks = get_kill_switch(s)
        return {"last_tick": self.last_tick.isoformat() if self.last_tick else None,
                "auto_paused": {str(k): v for k, v in self.auto_paused.items()}, "kill_switch": ks}

