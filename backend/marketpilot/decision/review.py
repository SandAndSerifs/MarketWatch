"""Step 8 - deterministic post-trade review.

Separates *decision quality* from *outcome*: a losing trade that followed the plan
is a good decision with a bad outcome; a winning trade that broke the rules is a
bad decision with a lucky outcome. One trade is never treated as evidence that a
strategy works or fails.
"""
from __future__ import annotations

from typing import Any

from ..db import Trade

PLANNED_EXIT_RULES = {"stop", "target", "time_stop", "thesis_broken", "trail", "earnings", "eod"}


def review_trade(trade: Trade, decision_record: dict[str, Any] | None, exit_rule: str) -> dict[str, Any]:
    entry, exit_px = trade.entry_price, trade.exit_price or trade.entry_price
    risk = trade.entry_price - trade.stop_initial
    r = trade.r_multiple
    mae_r = round((trade.mae - entry) / risk, 2) if risk > 0 and trade.mae is not None else None
    mfe_r = round((trade.mfe - entry) / risk, 2) if risk > 0 and trade.mfe is not None else None
    outcome = "win" if (trade.net_pnl or 0) > 0 else ("scratch" if abs(r or 0) < 0.1 else "loss")
    planned_entry = None
    slippage_note = None
    if decision_record:
        planned_entry = decision_record["steps"]["6_risk"]["entry"]
        diff_pct = (entry - planned_entry) / planned_entry * 100
        slippage_note = f"Filled {entry:.2f} vs planned trigger {planned_entry:.2f} ({diff_pct:+.2f}%)."
    followed: list[dict[str, Any]] = [
        {"rule": "Exit by a predefined rule", "ok": exit_rule in PLANNED_EXIT_RULES, "detail": exit_rule},
        {"rule": "Stop never widened", "ok": trade.stop_current >= trade.stop_initial - 1e-9,
         "detail": f"initial {trade.stop_initial:.2f}, final {trade.stop_current:.2f}"},
        {"rule": "Loss contained near 1R", "ok": r is None or r >= -1.35,
         "detail": f"{r:.2f}R" if r is not None else "n/a"},
    ]
    process_ok = all(f["ok"] for f in followed)
    lessons: list[str] = []
    if outcome == "loss" and mfe_r is not None and mfe_r >= 1.0:
        lessons.append(f"Trade was +{mfe_r}R at best before reversing: review whether the breakeven/trailing rule engaged as designed.")
    if outcome == "win" and mae_r is not None and mae_r <= -0.8:
        lessons.append(f"Trade went {mae_r}R against before working: the stop was nearly hit; entry timing may be early.")
    if exit_rule == "time_stop":
        lessons.append("Exited on the time stop: the expected momentum did not appear within the planned window.")
    if exit_rule == "stop" and mfe_r is not None and mfe_r < 0.3:
        lessons.append("Stopped out with little favourable movement: the setup failed quickly. Compare with the objections raised at entry.")
    if r is not None and r < -1.35:
        lessons.append(f"Loss of {r:.2f}R exceeded 1R: likely a gap through the stop. Overnight/event gap risk is real even with stops.")
    if exit_rule == "target":
        lessons.append("Target reached: the thesis played out as planned.")
    objections = []
    if decision_record:
        objections = [f"[{o['severity']}] {o['issue']}: {o['detail']}"
                      for o in decision_record["steps"]["5_challenge"]["objections"] if o["severity"] != "info"]
    thesis_status = {
        "target": "Thesis played out (target reached)",
        "stop": "Thesis invalidated by price (stop hit)",
        "thesis_broken": "Thesis invalidated by a predefined condition",
        "time_stop": "Thesis not confirmed within the time window",
        "trail": "Trend leg ended (trailing exit)",
        "earnings": "Closed ahead of earnings (event risk rule)",
        "eod": "Intraday position closed before the bell",
    }.get(exit_rule, "Exited outside the plan (manual/emergency)")
    return {
        "outcome": outcome,
        "net_pnl": trade.net_pnl, "r_multiple": r, "mae_r": mae_r, "mfe_r": mfe_r,
        "exit_rule": exit_rule, "thesis_status": thesis_status,
        "execution": {"slippage_note": slippage_note, "fees": trade.fees},
        "process_checks": followed,
        "decision_quality": "Plan followed" if process_ok else "Plan deviation",
        "objections_at_entry": objections,
        "lessons": lessons or ["No specific pattern flagged. Judge the strategy on the aggregate of many trades, not this one."],
        "caveat": "A single trade's outcome is mostly noise; evaluate decisions by process and strategies by large samples.",
    }
