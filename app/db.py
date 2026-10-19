import os
from datetime import datetime, timezone
from sqlalchemy import create_engine, String, Integer, Float, Boolean, DateTime, Text, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./coindcx_terminal.db')
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql+psycopg://', 1)
elif DATABASE_URL.startswith('postgresql://') and '+psycopg' not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace('postgresql://', 'postgresql+psycopg://', 1)
connect_args = {'check_same_thread': False} if DATABASE_URL.startswith('sqlite') else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=280, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

def utcnow():
    return datetime.now(timezone.utc)

class ConfigKV(Base):
    __tablename__ = 'config_kv'
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default='')
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

class Event(Base):
    __tablename__ = 'events'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    level: Mapped[str] = mapped_column(String(16), default='INFO')
    category: Mapped[str] = mapped_column(String(60), default='system')
    message: Mapped[str] = mapped_column(String(500))
    details_json: Mapped[str] = mapped_column(Text, default='{}')

class MarketSnapshot(Base):
    __tablename__ = 'market_snapshots'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product: Mapped[str] = mapped_column(String(16), index=True)
    pair: Mapped[str] = mapped_column(String(40), index=True)
    last_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    quote_turnover_usdt: Mapped[float | None] = mapped_column(Float, nullable=True)
    liquidity_source: Mapped[str] = mapped_column(String(40), default='unknown')
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    exit_only: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    raw_json: Mapped[str] = mapped_column(Text, default='{}')
    __table_args__ = (Index('idx_market_product_pair', 'product', 'pair', unique=True),)

class PaperPosition(Base):
    __tablename__ = 'paper_positions'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product: Mapped[str] = mapped_column(String(16), index=True)
    pair: Mapped[str] = mapped_column(String(40), index=True)
    side: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    notional_usdt: Mapped[float] = mapped_column(Float, default=0)
    leverage: Mapped[float] = mapped_column(Float, default=1)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    strategy: Mapped[str] = mapped_column(String(100), default='CSM14D_VOL14D')
    trade_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_mark_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_unrealized_pnl_inr: Mapped[float] = mapped_column(Float, default=0)
    is_open: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

class Trade(Base):
    __tablename__ = 'trades'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    run_mode: Mapped[str] = mapped_column(String(16), default='paper', index=True)
    product: Mapped[str] = mapped_column(String(16), index=True)
    pair: Mapped[str] = mapped_column(String(40), index=True)
    side: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    leverage: Mapped[float] = mapped_column(Float, default=1)
    gross_pnl_inr: Mapped[float] = mapped_column(Float, default=0)
    fees_inr: Mapped[float] = mapped_column(Float, default=0)
    slippage_inr: Mapped[float] = mapped_column(Float, default=0)
    funding_inr: Mapped[float] = mapped_column(Float, default=0)
    net_pnl_inr: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(24), default='open', index=True)
    strategy: Mapped[str] = mapped_column(String(100), default='CSM14D_VOL14D')
    reason: Mapped[str] = mapped_column(String(300), default='')
    external_order_id: Mapped[str] = mapped_column(String(100), default='')
    metadata_json: Mapped[str] = mapped_column(Text, default='{}')

class ScalpTrade(Base):
    """Independent fast-scalping paper ledger; never submits exchange orders."""
    __tablename__ = 'scalp_trades'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    product: Mapped[str] = mapped_column(String(16), index=True)
    pair: Mapped[str] = mapped_column(String(40), index=True)
    side: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    notional_usdt: Mapped[float] = mapped_column(Float, default=100)
    status: Mapped[str] = mapped_column(String(16), default='open', index=True)
    gross_pnl_inr: Mapped[float] = mapped_column(Float, default=0)
    fees_inr: Mapped[float] = mapped_column(Float, default=0)
    slippage_inr: Mapped[float] = mapped_column(Float, default=0)
    tax_reserve_inr: Mapped[float] = mapped_column(Float, default=0)
    tds_estimate_inr: Mapped[float] = mapped_column(Float, default=0)
    net_after_tax_inr: Mapped[float] = mapped_column(Float, default=0)
    unrealized_net_after_tax_inr: Mapped[float] = mapped_column(Float, default=0)
    entry_score: Mapped[float] = mapped_column(Float, default=0)
    cost_hurdle_pct: Mapped[float] = mapped_column(Float, default=0)
    spread_bps: Mapped[float] = mapped_column(Float, default=0)
    best_favorable_pct: Mapped[float] = mapped_column(Float, default=0)
    worst_adverse_pct: Mapped[float] = mapped_column(Float, default=0)
    exit_reason: Mapped[str] = mapped_column(String(300), default='')
    metadata_json: Mapped[str] = mapped_column(Text, default='{}')


class OrderRecord(Base):
    __tablename__ = 'order_records'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    run_mode: Mapped[str] = mapped_column(String(16), index=True)
    product: Mapped[str] = mapped_column(String(16), index=True)
    pair: Mapped[str] = mapped_column(String(40), index=True)
    side: Mapped[str] = mapped_column(String(8))
    order_type: Mapped[str] = mapped_column(String(20), default='market_order')
    quantity: Mapped[float] = mapped_column(Float)
    requested_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default='pending', index=True)
    external_order_id: Mapped[str] = mapped_column(String(100), default='')
    client_order_id: Mapped[str] = mapped_column(String(100), default='')
    details_json: Mapped[str] = mapped_column(Text, default='{}')

class BacktestResult(Base):
    __tablename__ = 'backtest_results'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    experiment: Mapped[str] = mapped_column(String(100), index=True)
    strategy: Mapped[str] = mapped_column(String(150))
    period: Mapped[str] = mapped_column(String(100))
    product: Mapped[str] = mapped_column(String(16), index=True)
    exposure_x: Mapped[float] = mapped_column(Float, default=1)
    cost_case: Mapped[str] = mapped_column(String(20), default='NORMAL')
    return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_pnl_inr: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_drawdown_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    adverse_drawdown_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_daily_pnl_inr: Mapped[float | None] = mapped_column(Float, nullable=True)
    profitable_days_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default='')
    metrics_json: Mapped[str] = mapped_column(Text, default='{}')

# Live execution ledger and operational telemetry. New tables are created by
# Base.metadata.create_all; existing tables do not need destructive migration.
class ExecutionFill(Base):
    __tablename__ = 'execution_fills'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_fill_id: Mapped[str] = mapped_column(String(220), unique=True, index=True)
    order_record_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    run_mode: Mapped[str] = mapped_column(String(20), default='live')
    product: Mapped[str] = mapped_column(String(16), index=True)
    pair: Mapped[str] = mapped_column(String(40), index=True)
    side: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    notional: Mapped[float] = mapped_column(Float, default=0)
    fee_amount: Mapped[float] = mapped_column(Float, default=0)
    fee_currency: Mapped[str] = mapped_column(String(20), default='UNKNOWN')
    strategy_owned: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    source: Mapped[str] = mapped_column(String(32), default='exchange_trade_history')
    raw_json: Mapped[str] = mapped_column(Text, default='{}')

class LedgerEntry(Base):
    __tablename__ = 'ledger_entries'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ledger_key: Mapped[str] = mapped_column(String(250), unique=True, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    run_mode: Mapped[str] = mapped_column(String(20), default='live', index=True)
    product: Mapped[str] = mapped_column(String(16), default='unknown', index=True)
    pair: Mapped[str] = mapped_column(String(40), default='', index=True)
    category: Mapped[str] = mapped_column(String(50), index=True)
    amount: Mapped[float] = mapped_column(Float, default=0)
    currency: Mapped[str] = mapped_column(String(20), default='UNKNOWN')
    cash_effect: Mapped[bool] = mapped_column(Boolean, default=False)
    reconciliation_status: Mapped[str] = mapped_column(String(40), default='reconciled', index=True)
    external_ref: Mapped[str] = mapped_column(String(180), default='', index=True)
    details_json: Mapped[str] = mapped_column(Text, default='{}')

class AccountSnapshot(Base):
    __tablename__ = 'account_snapshots'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    status: Mapped[str] = mapped_column(String(20), default='ok', index=True)
    spot_balances_json: Mapped[str] = mapped_column(Text, default='[]')
    futures_wallets_json: Mapped[str] = mapped_column(Text, default='[]')
    futures_positions_json: Mapped[str] = mapped_column(Text, default='[]')
    warnings_json: Mapped[str] = mapped_column(Text, default='[]')

class TelemetrySnapshot(Base):
    __tablename__ = 'telemetry_snapshots'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    status: Mapped[str] = mapped_column(String(20), default='ok', index=True)
    details_json: Mapped[str] = mapped_column(Text, default='{}')

class StrategyPosition(Base):
    """Bot-owned signed position ledger, reconstructed only from matched exchange fills."""
    __tablename__ = 'strategy_positions'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product: Mapped[str] = mapped_column(String(16), index=True)
    pair: Mapped[str] = mapped_column(String(40), index=True)
    signed_quantity: Mapped[float] = mapped_column(Float, default=0)
    average_entry_price: Mapped[float] = mapped_column(Float, default=0)
    last_mark_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl_inr: Mapped[float] = mapped_column(Float, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (Index('idx_strategy_position_product_pair', 'product', 'pair', unique=True),)


class PaperModePosition(Base):
    """Independent capital-constrained paper ledger; never mixed with research positions."""
    __tablename__ = 'paper_mode_positions'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mode: Mapped[str] = mapped_column(String(24), default='capital_constrained', index=True)
    product: Mapped[str] = mapped_column(String(16), index=True)
    pair: Mapped[str] = mapped_column(String(40), index=True)
    side: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    notional_usdt: Mapped[float] = mapped_column(Float, default=0)
    leverage: Mapped[float] = mapped_column(Float, default=1)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    strategy: Mapped[str] = mapped_column(String(100), default='CSM14D_VOL14D')
    trade_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_mark_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_unrealized_pnl_inr: Mapped[float] = mapped_column(Float, default=0)
    is_open: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class MarketObservation(Base):
    """Append-only, bounded market snapshot history for later audits and backtests."""
    __tablename__ = 'market_observations'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    product: Mapped[str] = mapped_column(String(16), index=True)
    pair: Mapped[str] = mapped_column(String(40), index=True)
    last_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    turnover_usdt: Mapped[float | None] = mapped_column(Float, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (Index('idx_observation_product_pair_time', 'product', 'pair', 'observed_at'),)


class PaperDecisionAudit(Base):
    """Accepted/rejected signal decision plus shadow outcome at fixed horizons."""
    __tablename__ = 'paper_decision_audits'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    product: Mapped[str] = mapped_column(String(16), index=True)
    pair: Mapped[str] = mapped_column(String(40), index=True)
    proposed_side: Mapped[str] = mapped_column(String(8), default='none')
    mode: Mapped[str] = mapped_column(String(24), default='unrestricted', index=True)
    decision: Mapped[str] = mapped_column(String(12), index=True)  # accepted / rejected / watch
    rejection_reason: Mapped[str] = mapped_column(String(300), default='')
    reference_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_move_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_cost_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    momentum_24h_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    momentum_72h_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome_1h_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome_4h_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome_24h_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_outcome_1h_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_outcome_4h_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_outcome_24h_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    evaluated_1h: Mapped[bool] = mapped_column(Boolean, default=False)
    evaluated_4h: Mapped[bool] = mapped_column(Boolean, default=False)
    evaluated_24h: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (Index('idx_decision_audit_pair_time', 'product', 'pair', 'decision_at'),)
