#!/usr/bin/env python3
# =============================================================
# QXNet Pull — Daily data digestion for QuantXT / QXMarket / QXGraph
#
# - QX: FRED fiscal snapshot → QXYYMMDD.TXT
# - QM: FRED index snapshot  → QMYYMMDD.TXT
# - QG: Yahoo OHLCV+TA, 30d per ticker → QGTTTYYMMDD.TXT
# - US: FRED fiscal history, 30d rolling → USMMDDYY.TXT
#
# Hosts for XT FTP retrieval. Prunes and archives old files.
# =============================================================
# Cron: 0 6 * * * /usr/bin/python3 /opt/qxnet/qxpull.py
# =============================================================

import os
import re
import shutil
import logging
import requests
from datetime import datetime, timedelta

import yfinance as yf
import pandas as pd
import numpy as np

# =============================================================
# CONFIG
# =============================================================

FRED_API_KEY   = "ADD YOUR KEY HERE"
FRED_BASE      = "https://api.stlouisfed.org/fred/series/observations"

DATA_DIR       = "/var/qxnet/data"
ARCHIVE_DIR    = "/var/qxnet/archive"
LOG_FILE       = "/var/qxnet/qxpull.log"

RETAIN_DAYS    = 30
ARCHIVE_DAYS   = 365

# =============================================================
# FRED SERIES MAP — QuantXT State fields
# =============================================================

FISCAL_SERIES = {
    "int_rev":            ("FYOIGDA188S",      1.0,    20.0),
    "debt_gdp":           ("GFDEGDQ188S",      1.0,   125.0),
    "usd_reserve_share":  ("TRESEGUS",         1.0,    57.0),
    "cbo_deficit":        ("FYFSGDA188S",     -1.0,     6.0),
    "sahm":               ("SAHMREALTIME",     1.0,     0.3),
    "hy_spread":          ("BAMLH0A0HYM2",     1.0,   450.0),
    "ofr":                ("NFCI",             1.0,     0.1),
    "dxy_mom":            ("DTWEXBGS",         1.0,   104.0),
    "oil_price":          ("DCOILWTICO",       1.0,    80.0),

    # Monthly / Quarterly
    "infl":               ("CPIAUCSL",         1.0,     3.5),
    "unemp":              ("UNRATE",           1.0,     4.0),
    "gdp":                ("A191RL1Q225SBEA",  1.0,     2.5),

    # Proxies
    "tail_risk":          ("VIXCLS",           0.05,    1.0),
    "liq_gap":            ("TEDRATE",          1.0,     0.5),
    "ai_capex":           ("B009RC1Q027SBEA",  0.001,   2.5),
    "investor_sentiment": ("UMCSENT",          0.01,    0.7),
    "geopolitical_risk":  ("GPR",              0.02,    0.5),
    "xdate":              ("DGS1",             10.0,  180.0),
}

HISTORY_FIELDS = [
    "int_rev", "debt_gdp", "usd_reserve_share", "cbo_deficit",
    "xdate", "sahm", "tail_risk", "liq_gap", "ofr", "hy_spread",
    "dxy_mom", "oil_price", "ai_capex", "lagged_ai",
    "geopolitical_risk", "investor_sentiment",
    "infl", "unemp", "gdp",
]

# =============================================================
# INDEX SERIES MAP — QXMarket
# =============================================================

INDEX_SERIES = {
    "SP500":   ("SP500",      1.0, 0.0),
    "DJIA":    ("DJIA",       1.0, 0.0),
    "NASDAQ":  ("NASDAQCOM",  1.0, 0.0),
}

# =============================================================
# QXGRAPH MARKET SERIES — Yahoo Finance
# =============================================================

GRAPH_SERIES = {
    "SPX": "^GSPC",
    "NDX": "^NDX",
}

# =============================================================
# LOGGING
# =============================================================

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("qxpull")

# =============================================================
# FRED FETCH (LATEST)
# =============================================================

def fetch_fred(series_id, scale, fallback):
    try:
        params = {
            "series_id": series_id,
            "api_key": FRED_API_KEY,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 1,
            "observation_start": "2020-01-01",
        }
        r = requests.get(FRED_BASE, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        obs = data["observations"]
        if not obs or obs[0]["value"] == ".":
            return fallback
        return float(obs[0]["value"]) * scale
    except:
        return fallback

# =============================================================
# FRED FETCH (HISTORICAL)
# =============================================================

def fetch_fred_history(series_id, scale, fallback, start_date, end_date):
    try:
        params = {
            "series_id": series_id,
            "api_key": FRED_API_KEY,
            "file_type": "json",
            "observation_start": start_date.strftime("%Y-%m-%d"),
            "observation_end": end_date.strftime("%Y-%m-%d"),
            "sort_order": "asc",
        }
        r = requests.get(FRED_BASE, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        obs = data.get("observations", [])
        values = {}
        for o in obs:
            if o.get("value") == ".":
                continue
            d = pd.to_datetime(o["date"])
            values[d] = float(o["value"]) * scale
        if not values:
            return pd.Series(dtype=float)
        return pd.Series(values).sort_index()
    except:
        return pd.Series(dtype=float)

# =============================================================
# DERIVED FIELDS
# =============================================================

def compute_derived(values, prev_ai_capex=None):
    values["lagged_ai"] = prev_ai_capex if prev_ai_capex is not None else values["ai_capex"]
    return values

LAG_FILE = "/var/qxnet/qxlag.txt"

def load_prev_ai_capex():
    try:
        with open(LAG_FILE, "r") as f:
            return float(f.read().strip())
    except:
        return None

def save_ai_capex(value):
    try:
        with open(LAG_FILE, "w") as f:
            f.write(f"{value:.6f}\n")
    except:
        pass

# =============================================================
# BUILD 30-DAY FISCAL HISTORY
# =============================================================

def build_fiscal_history_dataset(today):
    end_date = today.date()
    start_window = end_date - timedelta(days=29)
    fetch_start = end_date - timedelta(days=365)

    date_index = pd.date_range(start_window, end_date, freq="D")
    df = pd.DataFrame(index=date_index)

    for field, (series_id, scale, fallback) in FISCAL_SERIES.items():
        s = fetch_fred_history(series_id, scale, fallback, fetch_start, end_date)

        if s.empty:
            df[field] = fallback
            continue

        s = s.reindex(date_index, method="ffill")
        s = s.fillna(fallback)
        df[field] = s

    # lagged_ai
    df["lagged_ai"] = df["ai_capex"].shift(1).fillna(df["ai_capex"])

    return df[HISTORY_FIELDS]

# =============================================================
# WRITE US HISTORY FILE
# =============================================================

def write_fiscal_history_file(date, df):
    filename = f"US{date.strftime('%m%d%y')}.TXT"
    filepath = os.path.join(DATA_DIR, filename)

    lines = ["# name " + " ".join(HISTORY_FIELDS)]
    df = df.tail(30).reset_index(drop=True)

    for i, row in enumerate(df.itertuples(index=False), start=1):
        vals = " ".join(f"{float(v):.3f}" for v in row)
        lines.append(f"day_{i:02d} {vals}")

    lines.append("END")

    with open(filepath, "w") as f:
        f.write("\r\n".join(lines) + "\r\n")

    return filename

# =============================================================
# LAGGED AI CAPEX — persist previous value across runs
# =============================================================

LAG_FILE = "/var/qxnet/qxlag.txt"

def load_prev_ai_capex():
    """Load previous ai_capex value for lagged_ai computation."""
    try:
        with open(LAG_FILE, "r") as f:
            return float(f.read().strip())
    except Exception:
        return None

def save_ai_capex(value):
    """Persist current ai_capex for next run's lagged_ai."""
    try:
        with open(LAG_FILE, "w") as f:
            f.write(f"{value:.6f}\n")
    except Exception as e:
        log.error(f"Failed to save lag file: {e}")

# =============================================================
# 8.3 FILENAME GENERATION
# =============================================================

def make_filename(prefix, date):
    """
    Generate 8.3 compliant filename.
    Format: QX + YYMMDD.TXT  e.g. QX260524.TXT
    Prefix must be 2 chars.
    """
    return f"{prefix}{date.strftime('%y%m%d')}.TXT"

def make_graph_filename(ticker, date):
    """
    Generate 8.3 filename for QXGraph per-ticker files.
    Format: QG + TTT + YYMMDD.TXT  e.g. QGSPX260524.TXT
    """
    ticker = ticker.upper()[:3]
    return f"QG{ticker}{date.strftime('%y%m%d')}.TXT"

def make_us_history_filename(date):
    """
    Generate 8.3 filename for US 30-day fiscal history.
    Format: USMMDDYY.TXT  e.g. US053026.TXT
    """
    return f"US{date.strftime('%m%d%y')}.TXT"

# =============================================================
# WRITE QUANTXT FISCAL DATA FILE (SNAPSHOT)
# =============================================================

def write_fiscal_file(date, values):
    """Write digested fiscal state to 8.3 .TXT file."""
    filename = make_filename("QX", date)
    filepath = os.path.join(DATA_DIR, filename)

    lines = [
        f"QXNET FISCAL DATA {date.strftime('%Y-%m-%d')}",
        "VERSION 1",
        f"FIELDS {len(values)}",
    ]
    for key, val in values.items():
        lines.append(f"{key.upper()} {val:.6f}")
    lines.append("END")

    with open(filepath, "w") as f:
        f.write("\r\n".join(lines) + "\r\n")   # DOS line endings

    log.info(f"Written: {filename}")
    return filename

# =============================================================
# WRITE QXMARKET INDEX FILE (SNAPSHOT)
# =============================================================

def write_index_file(date, values):
    """Write digested index data to 8.3 .TXT file."""
    filename = make_filename("QM", date)
    filepath = os.path.join(DATA_DIR, filename)

    lines = [
        f"QXNET INDEX DATA {date.strftime('%Y-%m-%d')}",
        "VERSION 1",
        f"FIELDS {len(values)}",
    ]
    for key, val in values.items():
        if val > 0:
            lines.append(f"{key} {val:.2f}")
    lines.append("END")

    with open(filepath, "w") as f:
        f.write("\r\n".join(lines) + "\r\n")

    log.info(f"Written: {filename}")
    return filename

# =============================================================
# BUILD 30-DAY FISCAL HISTORY (USMMDDYY.TXT)
# =============================================================

def build_fiscal_history_dataset(today):
    """
    Build a 30-day rolling daily fiscal dataset from FRED.
    Returns a DataFrame indexed by date with columns HISTORY_FIELDS.
    """
    end_date = today.date()
    start_window = end_date - timedelta(days=29)
    fetch_start = end_date - timedelta(days=365)

    date_index = pd.date_range(start_window, end_date, freq="D")
    df = pd.DataFrame(index=date_index)

    for field, (series_id, scale, fallback) in FISCAL_SERIES.items():
        s = fetch_fred_history(series_id, scale, fallback, fetch_start, end_date)

        if s.empty:
            df[field] = fallback
            continue

        # Align to daily index with forward-fill
        s = s.reindex(date_index, method="ffill")
        s = s.fillna(fallback)
        df[field] = s

    # Derived: lagged_ai
    if "ai_capex" in df.columns:
        lag = df["ai_capex"].shift(1)
        lag.iloc[0] = df["ai_capex"].iloc[0]
        df["lagged_ai"] = lag
    else:
        df["lagged_ai"] = 2.5

    # Ensure all required fields exist
    for col in HISTORY_FIELDS:
        if col not in df.columns:
            df[col] = 0.0

    return df[HISTORY_FIELDS].copy()


def write_fiscal_history_file(date, df):
    """
    Write 30-day rolling fiscal history to USMMDDYY.TXT.
    Format matches USMAY30D.TXT example, with END at bottom.
    """
    filename = make_us_history_filename(date)
    filepath = os.path.join(DATA_DIR, filename)

    header = "# name " + " ".join(HISTORY_FIELDS)
    lines = [header]

    # Ensure exactly 30 rows, oldest → newest
    df = df.sort_index().tail(30)
    df = df.reset_index(drop=True)

    for i, row in enumerate(df.itertuples(index=False), start=1):
        vals = " ".join(f"{float(v):.3f}" for v in row)
        lines.append(f"day_{i:02d} {vals}")

    lines.append("END")

    with open(filepath, "w") as f:
        f.write("\r\n".join(lines) + "\r\n")

    log.info(f"Written US history file: {filename}")
    return filename

# =============================================================
# YAHOO FINANCE — OHLCV + INDICATORS FOR QXGRAPH
# =============================================================

def compute_indicators(df):
    """
    Compute technical indicators on a daily OHLCV DataFrame.
    Expects columns: Open, High, Low, Close, Volume
    Handles multiple data format variants from yfinance.
    """
    df = df.copy()
    
    print(f"\n[compute_indicators] Input shape: {df.shape}")
    print(f"[compute_indicators] Raw columns: {list(df.columns)}")
    print(f"[compute_indicators] Column types: {dict(df.dtypes)}")
    
    # Safety check: if we have duplicate non-OHLCV columns, something is wrong
    if len(df.columns) > 1:
        unique_cols = set(str(c).lower() for c in df.columns)
        if len(unique_cols) == 1:
            raise ValueError(
                f"FATAL: All columns have same name '{df.columns[0]}'. "
                f"This indicates yfinance returned corrupted data. "
                f"DataFrame shape: {df.shape}\n"
                f"Try updating yfinance: pip install --upgrade yfinance"
            )
    
    # Handle multi-level columns from Yahoo Finance
    if isinstance(df.columns, pd.MultiIndex):
        print(f"[compute_indicators] MultiIndex detected, levels: {df.columns.names}")
        # Try to get the OHLCV level (usually level 0 or 1)
        for level_idx in [0, 1, -2, -1]:
            try:
                test_cols = df.columns.get_level_values(level_idx)
                ohlcv_keywords = {'open', 'high', 'low', 'close', 'volume', 'adj'}
                if any(kw in str(c).lower() for c in test_cols for kw in ohlcv_keywords):
                    print(f"[compute_indicators] Found OHLCV at level {level_idx}: {list(test_cols)}")
                    df.columns = test_cols
                    break
            except Exception as e:
                print(f"[compute_indicators] Level {level_idx} failed: {e}")
                pass

    print(f"[compute_indicators] After MultiIndex handling: {list(df.columns)}")
    
    # CRITICAL: Drop 'Adj Close' if present to avoid duplicate Close columns
    # Keep only 'Close' since both map to the same thing
    cols_to_drop = [c for c in df.columns if 'adj' in str(c).lower()]
    if cols_to_drop:
        print(f"[compute_indicators] Dropping duplicate columns: {cols_to_drop}")
        df = df.drop(columns=cols_to_drop)
    
    print(f"[compute_indicators] After dropping Adj Close: {list(df.columns)}")
    
    # Check for numeric columns (convert to numeric first)
    try:
        # Try to convert all columns to numeric
        for col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    except:
        pass
    
    # Normalize column names: lowercase and remove spaces/underscores
    col_map = {}
    for c in df.columns:
        normalized = str(c).lower().replace("_", "").replace(" ", "")
        col_map[c] = normalized
    
    df.columns = [col_map[c] for c in df.columns]
    print(f"[compute_indicators] Normalized columns: {list(df.columns)}")

    # Map all normalized variants to standard names
    rename_map = {
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
        "dividends": "Dividends",
        "stocksplits": "StockSplits",
    }

    df = df.rename(columns=rename_map)
    print(f"[compute_indicators] After rename: {list(df.columns)}")

    # Final check: ensure Close column exists
    if "Close" not in df.columns:
        # Try to find ANY close-like column by substring matching
        close_candidates = [c for c in df.columns if "close" in str(c).lower()]
        if close_candidates:
            print(f"[compute_indicators] ✓ Found close candidate, mapping {close_candidates[0]} → Close")
            df["Close"] = df[close_candidates[0]]
        else:
            raise ValueError(
                f"ERROR: No close price column found!\n"
                f"Available columns: {list(df.columns)}\n"
                f"DataFrame shape: {df.shape}\n"
                f"DataFrame dtypes:\n{df.dtypes}\n"
                f"First row:\n{df.iloc[0] if len(df) > 0 else 'EMPTY'}\n"
                f"Try: pip install --upgrade yfinance"
            )

    # Synthesize missing fields
    if "Close" not in df.columns:
        raise ValueError("Close column missing after all recovery attempts")

    if "High" not in df.columns:
        df["High"] = df["Close"]

    if "Low" not in df.columns:
        df["Low"] = df["Close"]

    if "Open" not in df.columns:
        df["Open"] = df["Close"].shift(1).fillna(df["Close"])

    if "Volume" not in df.columns:
        df["Volume"] = 0.0  # VIX and FX often have no volume

    df["Open"]   = df["Open"].astype(float)
    df["High"]   = df["High"].astype(float)
    df["Low"]    = df["Low"].astype(float)
    df["Close"]  = df["Close"].astype(float)
    df["Volume"] = df["Volume"].astype(float)

    # Extract columns as variables for easier reference in indicator calculations
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    open_ = df["Open"]
    volume = df["Volume"]

    # VWAP (daily approximation)
    df["vwap"] = (high + low + close) / 3.0

    # RSI(14)
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    window_rsi = 14
    avg_gain = gain.rolling(window_rsi).mean()
    avg_loss = loss.rolling(window_rsi).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100.0 - (100.0 / (1.0 + rs))

    # MACD (12,26,9)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_sig"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_sig"]

    # SMA20 / SMA50
    df["sma20"] = close.rolling(20).mean()
    df["sma50"] = close.rolling(50).mean()

    # Bollinger Bands (20, 2)
    std20 = close.rolling(20).std()
    df["bb_upper"] = df["sma20"] + 2.0 * std20
    df["bb_lower"] = df["sma20"] - 2.0 * std20

    # ATR(14)
    prev_close = close.shift(1)
    tr1 = (high - low).abs()
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14).mean()

    # OBV
    obv = []
    prev_obv = 0
    for i in range(len(df)):
        if i == 0:
            obv.append(0)
        else:
            if close.iat[i] > close.iat[i-1]:
                prev_obv += volume.iat[i]
            elif close.iat[i] < close.iat[i-1]:
                prev_obv -= volume.iat[i]
            obv.append(prev_obv)
    df["obv"] = obv

    # Stochastic Oscillator (14, 3)
    low14 = low.rolling(14).min()
    high14 = high.rolling(14).max()
    stoch_k = 100.0 * (close - low14) / (high14 - low14)
    df["stoch_k"] = stoch_k
    df["stoch_d"] = df["stoch_k"].rolling(3).mean()

    return df

def fetch_yahoo_ohlcv(symbol, start_date, end_date):
    """
    Fetch raw daily data from Yahoo Finance.
    Handles multiple data format variants and corrupted responses from yfinance.
    """
    try:
        print(f"\n[DEBUG] Fetching {symbol} from {start_date.date()} to {end_date.date()}")
        
        # Try the standard yfinance download
        df = yf.download(
            symbol,
            start=start_date.strftime("%Y-%m-%d"),
            end=(end_date + timedelta(days=1)).strftime("%Y-%m-%d"),
            interval="1d",
            auto_adjust=False,
            progress=False,
        )

        print(f"[DEBUG] Standard yf.download result:")
        print(f"  COLUMNS: {list(df.columns)}")
        print(f"  SHAPE: {df.shape}")
        print(f"  DTYPES:\n{df.dtypes}")
        print(f"  INDEX NAME: {df.index.name}")
        if isinstance(df.columns, pd.MultiIndex):
            print(f"  MultiIndex levels: {df.columns.names}")

        if df.empty:
            log.warning(f"Yahoo: no data for {symbol}")
            return None

        # CHECK: Are columns duplicate ticker symbols? (corrupted response)
        unique_cols = set(str(c).lower() for c in df.columns)
        if len(unique_cols) == 1 and any(sym in str(list(unique_cols)[0]).lower() for sym in [symbol.lower(), symbol.replace('^', '')]):
            print(f"[DEBUG] ⚠️  CORRUPTED RESPONSE: All columns are '{list(unique_cols)[0]}', using fallback...")
            df = None

        # If standard download failed or was corrupted, use Ticker.history()
        if df is None or df.empty:
            print(f"[DEBUG] Trying yf.Ticker({symbol}).history()...")
            ticker_obj = yf.Ticker(symbol)
            df = ticker_obj.history(
                start=start_date.strftime("%Y-%m-%d"),
                end=(end_date + timedelta(days=1)).strftime("%Y-%m-%d"),
            )
            print(f"[DEBUG] Ticker.history() result:")
            print(f"  COLUMNS: {list(df.columns)}")
            print(f"  SHAPE: {df.shape}")
            print(f"  DTYPES:\n{df.dtypes}")

        if df.empty:
            log.warning(f"Yahoo: no data for {symbol} even with fallback")
            return None

        print(f"[DEBUG] ✓ Successfully fetched {len(df)} rows for {symbol}")
        return df

    except Exception as e:
        log.error(f"Yahoo fetch failed for {symbol}: {e}")
        import traceback
        traceback.print_exc()
        return None


def build_graph_dataset(ticker_label, yahoo_symbol, today):
    """
    Build a 30-day rolling OHLCV + indicator dataset for a given ticker.
    Returns a DataFrame with the final 30 rows, oldest first.
    """
    # Pull ~90 days to warm up indicators
    end = today
    start = end - timedelta(days=90)
    raw = fetch_yahoo_ohlcv(yahoo_symbol, start, end)

    if raw is None or raw.empty:
        raise ValueError(f"Yahoo returned no data for {yahoo_symbol}")
    
    df = compute_indicators(raw)
    df = df.dropna(subset=[
        "vwap", "rsi", "macd", "macd_sig", "macd_hist",
        "sma20", "sma50", "bb_upper", "bb_lower",
        "atr", "obv", "stoch_k", "stoch_d"
    ])

    if df.empty:
        log.warning(f"Indicators: no valid rows for {ticker_label}")
        return None

    df = df.sort_index().tail(30)
    if len(df) < 30:
        log.warning(f"{ticker_label}: only {len(df)} rows available for 30-day window")

    return df

def write_graph_file(date, ticker_label, df):
    """
    Write QXGraph-compatible 30-day rolling dataset for a single ticker.
    One file per ticker, 8.3 name: QGTTTYYMMDD.TXT
    """
    filename = make_graph_filename(ticker_label, date)
    filepath = os.path.join(DATA_DIR, filename)

    lines = []
    lines.append(f"# ticker {ticker_label}")
    lines.append("# name open high low close volume vwap rsi macd macd_sig macd_hist sma20 sma50 bb_upper bb_lower atr obv stoch_k stoch_d")

    df = df.sort_index()
    rows = list(df.itertuples())

    for idx, row in enumerate(rows, start=1):
        lines.append(
            "day_{:02d} {:.2f} {:.2f} {:.2f} {:.2f} {} {:.2f} {:.2f} {:.2f} {:.2f} {:.2f} {:.2f} {:.2f} {:.2f} {:.2f} {:.2f} {} {:.2f} {:.2f}".format(
                idx,
                row.Open,
                row.High,
                row.Low,
                row.Close,
                int(row.Volume),
                row.vwap,
                row.rsi,
                row.macd,
                row.macd_sig,
                row.macd_hist,
                row.sma20,
                row.sma50,
                row.bb_upper,
                row.bb_lower,
                row.atr,
                int(row.obv),
                row.stoch_k,
                row.stoch_d,
            )
        )

    lines.append("END")

    with open(filepath, "w") as f:
        f.write("\r\n".join(lines) + "\r\n")

    log.info(f"Written QXGraph file: {filename}")
    return filename

# =============================================================
# MANIFEST UPDATE
# =============================================================

def update_manifest(filename):
    """Append new filename to MANIFEST.TXT for XT client."""
    manifest = os.path.join(DATA_DIR, "MANIFEST.TXT")
    with open(manifest, "a") as f:
        f.write(filename + "\r\n")

# =============================================================
# PRUNE AND ARCHIVE
# =============================================================

def prune_and_archive():
    """
    Move files older than RETAIN_DAYS to archive.
    Delete archive files older than ARCHIVE_DAYS.
    Handles QX, QM, QGTTT, and USMMDDYY files.
    """
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    now = datetime.now()

    # QXYYMMDD.TXT, QMYYMMDD.TXT, QGTTTYYMMDD.TXT, USMMDDYY.TXT
    pattern = re.compile(r'^(QX|QM|US|QG[A-Z0-9]{3})(\d{6})\.TXT$')

    # prune data dir to archive
    for fname in os.listdir(DATA_DIR):
        m = pattern.match(fname)
        if not m:
            continue
        prefix = m.group(1)
        datestr = m.group(2)
        try:
            if prefix in ("QX", "QM") or prefix.startswith("QG"):
                fdate = datetime.strptime(datestr, "%y%m%d")
            elif prefix == "US":
                fdate = datetime.strptime(datestr, "%m%d%y")
            else:
                continue
            age = (now - fdate).days
            if age > RETAIN_DAYS:
                src = os.path.join(DATA_DIR, fname)
                dst = os.path.join(ARCHIVE_DIR, fname)
                shutil.move(src, dst)
                log.info(f"Archived: {fname} (age {age}d)")
        except ValueError:
            continue

    # prune archive beyond ARCHIVE_DAYS
    for fname in os.listdir(ARCHIVE_DIR):
        m = pattern.match(fname)
        if not m:
            continue
        prefix = m.group(1)
        datestr = m.group(2)
        try:
            if prefix in ("QX", "QM") or prefix.startswith("QG"):
                fdate = datetime.strptime(datestr, "%y%m%d")
            elif prefix == "US":
                fdate = datetime.strptime(datestr, "%m%d%y")
            else:
                continue
            age = (now - fdate).days
            if age > ARCHIVE_DAYS:
                os.remove(os.path.join(ARCHIVE_DIR, fname))
                log.info(f"Deleted from archive: {fname} (age {age}d)")
        except ValueError:
            continue

# =============================================================
# MAIN
# =============================================================

def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(ARCHIVE_DIR, exist_ok=True)

    today = datetime.now()
    log.info(f"=== QXNet pull starting {today.strftime('%Y-%m-%d')} ===")

    # --- fiscal snapshot (QX) ---
    fiscal_values = {}
    for field, (series_id, scale, fallback) in FISCAL_SERIES.items():
        fiscal_values[field] = fetch_fred(series_id, scale, fallback)

    prev_ai = load_prev_ai_capex()
    fiscal_values = compute_derived(fiscal_values, prev_ai)
    save_ai_capex(fiscal_values["ai_capex"])

    fiscal_file = write_fiscal_file(today, fiscal_values)
    update_manifest(fiscal_file)

    # --- 30-day fiscal history (USMMDDYY.TXT) ---
    hist_df = build_fiscal_history_dataset(today)
    if hist_df is not None and not hist_df.empty:
        us_file = write_fiscal_history_file(today, hist_df)
        update_manifest(us_file)
    else:
        log.warning("US history: no data generated")

    # --- index snapshot (QM) ---
    index_values = {}
    for field, (series_id, scale, fallback) in INDEX_SERIES.items():
        index_values[field] = fetch_fred(series_id, scale, fallback)

    index_file = write_index_file(today, index_values)
    update_manifest(index_file)

    # --- QXGraph market pull (30-day rolling, one file per ticker) ---
    for ticker_label, yahoo_symbol in GRAPH_SERIES.items():
        df_graph = build_graph_dataset(ticker_label, yahoo_symbol, today)
        if df_graph is None or df_graph.empty:
            log.warning(f"QXGraph: skipping {ticker_label}, no data")
            continue
        graph_file = write_graph_file(today, ticker_label, df_graph)
        update_manifest(graph_file)

    # --- prune and archive ---
    prune_and_archive()

    log.info(
        f"=== QXNet pull complete — {len(fiscal_values)} fiscal fields, "
        f"{len(index_values)} index fields, {len(GRAPH_SERIES)} graph tickers, "
        f"30-day US history generated ==="
    )

if __name__ == "__main__":
    main()