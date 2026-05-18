-- marketdata cache schema (DuckDB)
-- All timestamps are UTC. Daemon is the sole writer; other processes open read-only.

CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT current_timestamp
);

-- Bars: unified historical + live. PK guarantees idempotent upserts.
CREATE TABLE IF NOT EXISTS bars (
    symbol      VARCHAR    NOT NULL,
    interval    VARCHAR    NOT NULL,   -- '1m', '5m', '1h', '1d'
    ts          TIMESTAMP  NOT NULL,   -- bar start (Alpaca convention), UTC
    open        DOUBLE,
    high        DOUBLE,
    low         DOUBLE,
    close       DOUBLE,
    volume      BIGINT,
    source      VARCHAR    NOT NULL,   -- 'alpaca_rest', 'alpaca_stream', 'yfinance', etc.
    ingested_at TIMESTAMP  DEFAULT current_timestamp,
    PRIMARY KEY (symbol, interval, ts)
);

CREATE INDEX IF NOT EXISTS idx_bars_symbol_ts ON bars(symbol, ts DESC);

-- Top-of-book quotes (tick-level; rolled to parquet at 30d).
CREATE TABLE IF NOT EXISTS quotes (
    symbol     VARCHAR    NOT NULL,
    ts         TIMESTAMP  NOT NULL,
    bid        DOUBLE,
    ask        DOUBLE,
    bid_size   INTEGER,
    ask_size   INTEGER,
    source     VARCHAR    NOT NULL,
    PRIMARY KEY (symbol, ts)
);

-- Option contract enumeration (no quotes here; see option_quotes).
CREATE TABLE IF NOT EXISTS options_chains (
    contract_symbol VARCHAR    PRIMARY KEY,   -- e.g. 'AAPL250620C00200000'
    underlying      VARCHAR    NOT NULL,
    expiry          DATE       NOT NULL,
    strike          DOUBLE     NOT NULL,
    option_type     VARCHAR    NOT NULL,      -- 'call' | 'put'
    exercise_style  VARCHAR,
    last_seen       TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_chains_underlying_expiry
    ON options_chains(underlying, expiry);

-- Option quotes (best-effort; may be 'alpaca_quote' / 'alpaca_delayed' / 'bs_synth').
CREATE TABLE IF NOT EXISTS option_quotes (
    contract_symbol VARCHAR    NOT NULL,
    ts              TIMESTAMP  NOT NULL,
    bid             DOUBLE,
    ask             DOUBLE,
    last            DOUBLE,
    iv              DOUBLE,
    delta           DOUBLE,
    gamma           DOUBLE,
    theta           DOUBLE,
    vega            DOUBLE,
    source          VARCHAR    NOT NULL,
    PRIMARY KEY (contract_symbol, ts)
);

-- Account state snapshots.
CREATE TABLE IF NOT EXISTS accounts (
    account_id      VARCHAR    NOT NULL,
    ts              TIMESTAMP  NOT NULL,
    cash            DOUBLE,
    equity          DOUBLE,
    buying_power    DOUBLE,
    portfolio_value DOUBLE,
    currency        VARCHAR,
    status          VARCHAR,
    PRIMARY KEY (account_id, ts)
);

-- Position snapshots.
CREATE TABLE IF NOT EXISTS positions (
    account_id     VARCHAR    NOT NULL,
    ts             TIMESTAMP  NOT NULL,
    symbol         VARCHAR    NOT NULL,
    asset_class    VARCHAR,
    qty            DOUBLE,
    avg_entry      DOUBLE,
    market_price   DOUBLE,
    market_value   DOUBLE,
    unrealized_pl  DOUBLE,
    PRIMARY KEY (account_id, ts, symbol)
);

-- Orders (ingested from broker; we do not write trades here).
CREATE TABLE IF NOT EXISTS orders (
    order_id      VARCHAR    PRIMARY KEY,
    account_id    VARCHAR    NOT NULL,
    symbol        VARCHAR,
    side          VARCHAR,
    qty           DOUBLE,
    filled_qty    DOUBLE,
    order_type    VARCHAR,
    limit_price   DOUBLE,
    stop_price    DOUBLE,
    status        VARCHAR,
    submitted_at  TIMESTAMP,
    updated_at    TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_orders_account ON orders(account_id, updated_at DESC);

-- Audit trail: every backfill or stream write records its range here so
-- gap detection on restart is cheap.
CREATE TABLE IF NOT EXISTS ingestion_log (
    symbol       VARCHAR,
    interval     VARCHAR,
    range_start  TIMESTAMP,
    range_end    TIMESTAMP,
    source       VARCHAR,
    rows         BIGINT,
    ingested_at  TIMESTAMP   DEFAULT current_timestamp
);

CREATE INDEX IF NOT EXISTS idx_ingestion_log_symbol_interval
    ON ingestion_log(symbol, interval, range_end DESC);
