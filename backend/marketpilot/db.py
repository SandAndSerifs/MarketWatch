"""Database engine, session handling and ORM models.

SQLite works with zero configuration for local development (including Windows).
Set DATABASE_URL=postgresql+psycopg://user:pass@host/db to use PostgreSQL.

Every record that explains a decision (signals, decisions, orders, fills, trades)
is append-only in spirit: rows are created once and later only annotated
(status, outcome, post-trade review). Nothing rewrites the original rationale.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from .config import get_settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Stores naive UTC, always returns timezone-aware UTC datetimes."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Naive datetimes are not allowed; use timezone-aware UTC")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


# ---------------------------------------------------------------------------
# Watchlists
# ---------------------------------------------------------------------------
class Watchlist(Base):
    __tablename__ = "watchlists"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    items: Mapped[list["WatchlistItem"]] = relationship(
        back_populates="watchlist", cascade="all, delete-orphan", order_by="WatchlistItem.id"
    )


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("watchlist_id", "symbol"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    watchlist_id: Mapped[int] = mapped_column(ForeignKey("watchlists.id", ondelete="CASCADE"))
    symbol: Mapped[str] = mapped_column(String(12))
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    added_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    watchlist: Mapped[Watchlist] = relationship(back_populates="items")


# ---------------------------------------------------------------------------
# Decisions, signals, alerts
# ---------------------------------------------------------------------------
class Decision(Base):
    """The full 8-step checklist record for one evaluated opportunity."""

    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    experiment_id: Mapped[int | None] = mapped_column(ForeignKey("experiments.id"), nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(12), index=True)
    strategy_key: Mapped[str] = mapped_column(String(40))
    strategy_version: Mapped[str] = mapped_column(String(20))
    category: Mapped[str] = mapped_column(String(24))  # BUY_CANDIDATE, WATCH, NO_TRADE ...
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    record: Mapped[dict[str, Any]] = mapped_column(JSON)
    context: Mapped[str] = mapped_column(String(16), default="scanner")  # scanner | paper | backtest


class Signal(Base):
    __tablename__ = "signals"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    symbol: Mapped[str] = mapped_column(String(12), index=True)
    category: Mapped[str] = mapped_column(String(24), index=True)
    strategy_key: Mapped[str] = mapped_column(String(40))
    strategy_version: Mapped[str] = mapped_column(String(20))
    price: Mapped[float] = mapped_column(Float)
    price_ts: Mapped[datetime] = mapped_column(UTCDateTime)
    data_feed: Mapped[str] = mapped_column(String(40))
    entry: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop: Mapped[float | None] = mapped_column(Float, nullable=True)
    target: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_reward: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary: Mapped[str] = mapped_column(Text)
    decision_id: Mapped[int | None] = mapped_column(ForeignKey("decisions.id"), nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(160), index=True)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    kind: Mapped[str] = mapped_column(String(32))  # signal, summary, risk, system, event, trade
    severity: Mapped[str] = mapped_column(String(12), default="info")  # info, notice, warning, critical
    symbol: Mapped[str | None] = mapped_column(String(12), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(String(160), index=True)
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id"), nullable=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    channels: Mapped[list[Any]] = mapped_column(JSON, default=list)


# ---------------------------------------------------------------------------
# Paper trading
# ---------------------------------------------------------------------------
class Experiment(Base):
    """An isolated hypothetical-money account running one strategy version."""

    __tablename__ = "experiments"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    strategy_key: Mapped[str] = mapped_column(String(40))
    strategy_version: Mapped[str] = mapped_column(String(20))
    strategy_params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    risk_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    universe: Mapped[list[Any]] = mapped_column(JSON, default=list)
    starting_capital: Mapped[float] = mapped_column(Float, default=10_000.0)
    cash: Mapped[float] = mapped_column(Float, default=10_000.0)
    status: Mapped[str] = mapped_column(String(16), default="stopped")  # running|paused|stopped|halted
    halted_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    competition_group: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    day_start_equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    day_start_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("experiment_id", "client_order_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id"), index=True)
    client_order_id: Mapped[str] = mapped_column(String(120))  # idempotency key
    symbol: Mapped[str] = mapped_column(String(12))
    side: Mapped[str] = mapped_column(String(4))  # buy | sell
    order_type: Mapped[str] = mapped_column(String(12))  # market | limit | stop
    qty: Mapped[float] = mapped_column(Float)
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    purpose: Mapped[str] = mapped_column(String(16))  # entry | stop | target | exit
    status: Mapped[str] = mapped_column(String(20), default="new")
    filled_qty: Mapped[float] = mapped_column(Float, default=0.0)
    avg_fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    fees: Mapped[float] = mapped_column(Float, default=0.0)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_id: Mapped[int | None] = mapped_column(ForeignKey("decisions.id"), nullable=True)
    trade_id: Mapped[int | None] = mapped_column(ForeignKey("trades.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Fill(Base):
    __tablename__ = "fills"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    qty: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    reference_price: Mapped[float] = mapped_column(Float)  # quote mid / last at decision time
    fees: Mapped[float] = mapped_column(Float, default=0.0)
    model: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # spread, slippage, latency used


class Trade(Base):
    """A round trip (entry -> exit) with the full decision context attached."""

    __tablename__ = "trades"
    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(12), index=True)
    strategy_key: Mapped[str] = mapped_column(String(40))
    strategy_version: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(10), default="open")  # open | closed
    qty: Mapped[float] = mapped_column(Float)
    entry_ts: Mapped[datetime] = mapped_column(UTCDateTime)
    entry_price: Mapped[float] = mapped_column(Float)
    stop_initial: Mapped[float] = mapped_column(Float)
    target_initial: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_current: Mapped[float] = mapped_column(Float)
    exit_ts: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    fees: Mapped[float] = mapped_column(Float, default=0.0)
    gross_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    r_multiple: Mapped[float | None] = mapped_column(Float, nullable=True)
    mae: Mapped[float | None] = mapped_column(Float, nullable=True)  # max adverse excursion (price)
    mfe: Mapped[float | None] = mapped_column(Float, nullable=True)  # max favourable excursion (price)
    max_hold_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decision_id: Mapped[int | None] = mapped_column(ForeignKey("decisions.id"), nullable=True)
    review: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    exit_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (UniqueConstraint("experiment_id", "symbol"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(12))
    qty: Mapped[float] = mapped_column(Float)
    avg_cost: Mapped[float] = mapped_column(Float)
    trade_id: Mapped[int] = mapped_column(ForeignKey("trades.id"))
    last_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_price_ts: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class PendingSetup(Base):
    """A setup approved by the checklist that waits for its entry trigger."""

    __tablename__ = "pending_setups"
    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(12))
    decision_id: Mapped[int] = mapped_column(ForeignKey("decisions.id"))
    trigger_price: Mapped[float] = mapped_column(Float)
    stop: Mapped[float] = mapped_column(Float)
    target: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(16), default="armed")  # armed|triggered|expired|cancelled


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"
    __table_args__ = (Index("ix_equity_exp_ts", "experiment_id", "ts"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id"))
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    equity: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)
    positions_value: Mapped[float] = mapped_column(Float)
    benchmark_price: Mapped[float | None] = mapped_column(Float, nullable=True)  # SPY at same moment


# ---------------------------------------------------------------------------
# Strategy research
# ---------------------------------------------------------------------------
class StrategyVersion(Base):
    __tablename__ = "strategy_versions"
    __table_args__ = (UniqueConstraint("strategy_key", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_key: Mapped[str] = mapped_column(String(40))
    version: Mapped[str] = mapped_column(String(20))
    params: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|testing|approved|retired
    parent_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(20), default="user")  # user | ai-proposal | system
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # backtest ids, forward stats


class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    strategy_key: Mapped[str] = mapped_column(String(40))
    strategy_version: Mapped[str] = mapped_column(String(20))
    params: Mapped[dict[str, Any]] = mapped_column(JSON)
    universe: Mapped[list[Any]] = mapped_column(JSON)
    start: Mapped[str] = mapped_column(String(10))
    end: Mapped[str] = mapped_column(String(10))
    scenario: Mapped[str | None] = mapped_column(String(60), nullable=True)
    data_source: Mapped[str] = mapped_column(String(60))
    assumptions: Mapped[dict[str, Any]] = mapped_column(JSON)
    segments: Mapped[dict[str, Any]] = mapped_column(JSON)  # train/validation/test metrics
    trades: Mapped[list[Any]] = mapped_column(JSON)
    equity_curve: Mapped[list[Any]] = mapped_column(JSON)
    warnings: Mapped[list[Any]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="complete")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# Events, knowledge, audit
# ---------------------------------------------------------------------------
class MarketEvent(Base):
    __tablename__ = "market_events"
    __table_args__ = (UniqueConstraint("kind", "symbol", "name", "date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))  # earnings | macro
    symbol: Mapped[str] = mapped_column(String(12), default="*")  # "*" for macro
    name: Mapped[str] = mapped_column(String(120))
    date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD (US/Eastern date)
    time_et: Mapped[str | None] = mapped_column(String(10), nullable=True)  # "08:30", "bmo", "amc"
    importance: Mapped[str] = mapped_column(String(8), default="high")
    source: Mapped[str] = mapped_column(String(120))
    source_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    verified_at: Mapped[str | None] = mapped_column(String(10), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class KnowledgeDoc(Base):
    __tablename__ = "knowledge_docs"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(60), index=True)
    summary: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    sources: Mapped[list[Any]] = mapped_column(JSON, default=list)
    tags: Mapped[list[Any]] = mapped_column(JSON, default=list)
    updated_at: Mapped[str] = mapped_column(String(10))
    origin: Mapped[str] = mapped_column(String(20), default="curated")  # curated | user


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(40))  # user | engine | risk_manager | system
    action: Mapped[str] = mapped_column(String(80))
    experiment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON)


class AiMessage(Base):
    __tablename__ = "ai_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(64), index=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    role: Mapped[str] = mapped_column(String(12))
    content: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


# ---------------------------------------------------------------------------
# Engine / session
# ---------------------------------------------------------------------------
_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _make_engine(url: str) -> Engine:
    kwargs: dict[str, Any] = {"future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    eng = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(eng, "connect")
        def _sqlite_pragmas(dbapi_conn: Any, _rec: Any) -> None:  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return eng


def init_engine(url: str | None = None) -> Engine:
    global _engine, _SessionLocal
    url = url or get_settings().database_url
    _engine = _make_engine(url)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    Base.metadata.create_all(_engine)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        init_engine()
    assert _engine is not None
    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    if _SessionLocal is None:
        init_engine()
    assert _SessionLocal is not None
    s = _SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def audit(s: Session, actor: str, action: str, experiment_id: int | None = None, **details: Any) -> None:
    s.add(AuditLog(actor=actor, action=action, experiment_id=experiment_id, details=details))
