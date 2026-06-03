#!/usr/bin/env python3
# =============================================================
# QXNet Pull — Daily data digestion for QuantXT / QXMarket / QXGraph
#
# - QX: FRED fiscal snapshot → QXYYMMDD.TXT
# - QM: FRED index snapshot  → QMYYMMDD.TXT
# - TT: Yahoo OHLCV+TA, 30d per ticker → TTTYYMM.TXT
# - US: FRED fiscal history, 30d rolling → USMMDDYY.TXT
#
# Environment-aware: Supports both local (~/qxnet) and production (/var/qxnet)
# Set QXNET_ENV=production to use /var/qxnet, otherwise defaults to ~/qxnet
# =============================================================
# Cron (production): 0 6 * * * QXNET_ENV=production /usr/bin/python3 /opt/qxnet/qxpull.py
# Dev (local): python3 ~/qxnet/qxpull.py
# =============================================================

import os
import re
import shutil
import logging
import requests
from datetime import datetime, timedelta
from pathlib import Path

import yfinance as yf
import pandas as pd
import numpy as np

# =============================================================
# ENVIRONMENT DETECTION & CONFIG INITIALIZATION
# =============================================================

DEBUG = os.getenv("QXNET_DEBUG", "").lower() in ("1", "true", "yes")
ENVIRONMENT = os.getenv("QXNET_ENV", "local").lower()

def notify(msg):
    """Print real-time progress messages with timestamps."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")
    # Also log to file
    logging.getLogger("qxpull").info(msg)

def init_environment():
    """
    Initialize directories and config based on deployment environment.
    
    Local (default): ~/qxnet/
    Production: /var/qxnet/
    
    Returns: dict with BASE_DIR, DATA_DIR, ARCHIVE_DIR, LOG_FILE, LAG_FILE, FRED_API_KEY
    """
    config = {}
    
    if ENVIRONMENT == "production":
        config["BASE_DIR"] = Path("/var/qxnet")
        config["DATA_DIR"] = config["BASE_DIR"] / "data"
        config["ARCHIVE_DIR"] = config["BASE_DIR"] / "archive"
        config["LOG_FILE"] = config["BASE_DIR"] / "qxpull.log"
        config["LAG_FILE"] = config["BASE_DIR"] / "qxlag.txt"
        config["MANIFEST_FILE"] = config["BASE_DIR"] / "MANIFEST.TXT"
        api_key_file = config["BASE_DIR"] / "fred_api_key.txt"
        config_file = config["BASE_DIR"] / "config.txt"
        
        if config_file.exists():
            try:
                with open(config_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            key, value = line.split("=", 1)
                            config[key.strip()] = value.strip()
            except Exception as e:
                print(f"Warning: Could not parse {config_file}: {e}")
        
        if "FRED_API_KEY" not in config:
            if api_key_file.exists():
                try:
                    with open(api_key_file, "r") as f:
                        config["FRED_API_KEY"] = f.read().strip()
                except Exception as e:
                    raise FileNotFoundError(f"Cannot read FRED API key from {api_key_file}: {e}")
            else:
                raise FileNotFoundError(
                    f"Production mode requires FRED API key at {api_key_file} or in {config_file}"
                )
    
    else:
        config["BASE_DIR"] = Path.home() / "qxnet"
        config["DATA_DIR"] = config["BASE_DIR"] / "data"
        config["ARCHIVE_DIR"] = config["BASE_DIR"] / "archive"
        config["LOG_FILE"] = config["BASE_DIR"] / "qxpull.log"
        config["LAG_FILE"] = config["BASE_DIR"] / "qxlag.txt"
        config["MANIFEST_FILE"] = config["BASE_DIR"] / "MANIFEST.TXT"
        api_key_file = config["BASE_DIR"] / "fred_api_key.txt"
        
        if api_key_file.exists():
            try:
                with open(api_key_file, "r") as f:
                    api_key = f.read().strip()
                    if api_key and api_key != "YOUR_FRED_API_KEY_HERE":
                        config["FRED_API_KEY"] = api_key
                    else:
                        raise ValueError("API key file is empty or contains placeholder")
            except Exception as e:
                raise FileNotFoundError(
                    f"Local mode: Create {api_key_file} with your FRED API key.\n{e}"
                )
        else:
            raise FileNotFoundError(
                f"Local mode: API key file not found at {api_key_file}\n"
                f"Create it with: echo 'YOUR_FRED_API_KEY' > {api_key_file}"
            )
    
    config["BASE_DIR"].mkdir(parents=True, exist_ok=True)
    config["DATA_DIR"].mkdir(parents=True, exist_ok=True)
    config["ARCHIVE_DIR"].mkdir(parents=True, exist_ok=True)
    
    config.setdefault("RETAIN_DAYS", "30")
    config.setdefault("ARCHIVE_DAYS", "365")
    
    return config

CONFIG = init_environment()

BASE_DIR = CONFIG["BASE_DIR"]
DATA_DIR = CONFIG["DATA_DIR"]
ARCHIVE_DIR = CONFIG["ARCHIVE_DIR"]
LOG_FILE = CONFIG["LOG_FILE"]
LAG_FILE = CONFIG["LAG_FILE"]
MANIFEST_FILE = CONFIG["MANIFEST_FILE"]
FRED_API_KEY = CONFIG["FRED_API_KEY"]
RETAIN_DAYS = int(CONFIG.get("RETAIN_DAYS", 30))
ARCHIVE_DAYS = int(CONFIG.get("ARCHIVE_DAYS", 365))
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# =============================================================
# LOGGING
# =============================================================

logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("qxpull")

if DEBUG:
    print(f"[DEBUG] QXNET_ENV={ENVIRONMENT}")
    print(f"[DEBUG] BASE_DIR={BASE_DIR}")
    print(f"[DEBUG] DATA_DIR={DATA_DIR}")
    print(f"[DEBUG] Log file: {LOG_FILE}")

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

    "infl":               ("CPIAUCSL",         1.0,     3.5),
    "unemp":              ("UNRATE",           1.0,     4.0),
    "gdp":                ("A191RL1Q225SBEA",  1.0,     2.5),

    "tail_risk":          ("VIXCLS",           0.05,    1.0),
    "liq_gap":            ("TEDRATE",          1.0,     0.5),
    "ai_capex":           ("B009RC1Q027SBEA",  0.001,   2.5),
    "investor_sentiment": ("UMCSENT",          0.01,    0.7),

    # PATCHED: Correct geopolitical risk series
    "geopolitical_risk":  ("GPRC1",            0.02,    0.5),

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
# 8.3 FILENAME GENERATION (PATCHED)
# =============================================================

def make_filename(prefix, date):
    """
    Generate 8.3 compliant filename for MSDOS.
    Format: PREFIXYYMMDD.TXT (12 chars total)
    Prefix must be 2 chars.
    """
    if len(prefix) != 2:
        raise ValueError("Prefix must be exactly 2 characters")
    
    filename = f"{prefix}{date.strftime('%y%m%d')}.TXT"
    
    # PATCHED: Allow up to 12 chars (8.3 format)
    if len(filename) > 12:
        raise ValueError(f"Filename {filename} exceeds 8.3 limit")
    
    return filename

def make_us_history_filename(date):
    """Generate 8.3 filename for US history: USMMDDYY.TXT"""
    filename = f"US{date.strftime('%m%d%y')}.TXT"
    if len(filename) > 12:   # PATCHED
        raise ValueError(f"US filename {filename} exceeds 8.3 limit")
    return filename

def make_graph_filename(ticker, date):
    """
    Generate 8.3 filename for QXGraph per-ticker files.
    Format: TTTYYMM.TXT (<=12 chars)
    """
    ticker = re.sub(r'[^A-Z0-9]', '', ticker.upper())[:3]
    if len(ticker) < 3:
        ticker = ticker.ljust(3, '0')
    
    date_str = date.strftime('%y%m%d')
    filename = f"{ticker}{date_str[:5]}.TXT"
    if len(filename) > 12:   # PATCHED
        raise ValueError(f"Graph filename {filename} exceeds 8.3 limit")
    return filename

# =============================================================
# FRED FETCH (LATEST)
# =============================================================

def fetch_fred(series_id, scale, fallback):
    """Fetch latest value for a FRED series."""
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
    except Exception as e:
        log.warning(f"fetch_fred({series_id}): {e}, using fallback {fallback}")
        return fallback

# =============================================================
# FRED FETCH (HISTORICAL)
# =============================================================

def fetch_fred_history(series_id, scale, fallback, start_date, end_date):
    """Fetch historical data for a FRED series over date range."""
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
    except Exception as e:
        log.warning(f"fetch_fred_history({series_id}): {e}")
        return pd.Series(dtype=float)

# =============================================================
# DERIVED FIELDS
# =============================================================

def compute_derived(values, prev_ai_capex=None):
    """Compute lagged_ai from previous run's ai_capex."""
    values["lagged_ai"] = prev_ai_capex if prev_ai_capex is not None else values.get("ai_capex", 2.5)
    return values

# =============================================================
# LAGGED AI CAPEX — persist previous value across runs
# =============================================================

def load_prev_ai_capex():
    """Load previous ai_capex value for lagged_ai computation."""
    try:
        if LAG_FILE.exists():
            with open(LAG_FILE, "r") as f:
                val = f.read().strip()
                if val:
                    return float(val)
    except Exception as e:
        log.warning(f"Failed to load lag file: {e}")
    return None

def save_ai_capex(value):
    """Persist current ai_capex for next run's lagged_ai."""
    try:
        with open(LAG_FILE, "w") as f:
            f.write(f"{value:.6f}\n")
    except Exception as e:
        log.error(f"Failed to save lag file: {e}")

# =============================================================
# WRITE QUANTXT FISCAL DATA FILE (SNAPSHOT)
# =============================================================

def write_fiscal_file(date, values):
    """Write fiscal snapshot to QXYYMMDD.TXT"""
    filename = make_filename("QX", date)
    filepath = DATA_DIR / filename

    lines = [
        f"QXNET FISCAL DATA {date.strftime('%Y-%m-%d')}",
        "VERSION 1",
        f"FIELDS {len(values)}",
    ]
    for key, val in values.items():
        lines.append(f"{key} {val:.6f}")
    lines.append("END")

    with open(filepath, "w") as f:
        f.write("\r\n".join(lines) + "\r\n")

    log.info(f"Written fiscal file: {filename}")
    return filename

# =============================================================
# WRITE QXMARKET INDEX FILE (SNAPSHOT)
# =============================================================

def write_index_file(date, values):
    """Write index snapshot to QMYYMMDD.TXT"""
    filename = make_filename("QM", date)
    filepath = DATA_DIR / filename

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

    log.info(f"Written index file: {filename}")
    return filename

# =============================================================
# BUILD & WRITE 30-DAY FISCAL HISTORY (USMMDDYY.TXT)
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

        s = s.reindex(date_index, method="ffill")
        s = s.fillna(fallback)
        df[field] = s

    if "ai_capex" in df.columns:
        lag = df["ai_capex"].shift(1)
        lag.iloc[0] = df["ai_capex"].iloc[0]
        df["lagged_ai"] = lag
    else:
        df["lagged_ai"] = 2.5

    for col in HISTORY_FIELDS:
        if col not in df.columns:
            df[col] = 0.0

    return df[HISTORY_FIELDS].copy()

def write_fiscal_history_file(date, df):
    """Write 30-day rolling fiscal history to USMMDDYY.TXT"""
    filename = make_us_history_filename(date)
    filepath = DATA_DIR / filename

    header = "# name " + " ".join(HISTORY_FIELDS)
    lines = [header]

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
    """Compute technical indicators on raw OHLCV data."""
    df = df.copy()
    
    # VWAP
    df['vwap'] = (df['Close'] * df['Volume']).rolling(20).sum() / df['Volume'].rolling(20).sum()
    
    # RSI
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # MACD
    ema12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['macd'] = ema12 - ema26
    df['macd_sig'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['macd_sig']
    
    # SMA
    df['sma20'] = df['Close'].rolling(20).mean()
    df['sma50'] = df['Close'].rolling(50).mean()
    
    # Bollinger Bands
    bb_mid = df['Close'].rolling(20).mean()
    bb_std = df['Close'].rolling(20).std()
    df['bb_upper'] = bb_mid + (bb_std * 2)
    df['bb_lower'] = bb_mid - (bb_std * 2)
    
    # ATR
    df['tr'] = np.maximum(
        df['High'] - df['Low'],
        np.maximum(abs(df['High'] - df['Close'].shift()), abs(df['Low'] - df['Close'].shift()))
    )
    df['atr'] = df['tr'].rolling(14).mean()
    
    # OBV
    df['obv'] = (np.sign(df['Close'].diff()) * df['Volume']).fillna(0).cumsum()
    
    # Stochastic
    low14 = df['Low'].rolling(14).min()
    high14 = df['High'].rolling(14).max()
    df['stoch_k'] = 100 * (df['Close'] - low14) / (high14 - low14)
    df['stoch_d'] = df['stoch_k'].rolling(3).mean()
    
    return df

def fetch_yahoo_ohlcv(symbol, start_date, end_date):
    """Fetch OHLCV data from Yahoo Finance with fallback."""
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(
            start=start_date.strftime("%Y-%m-%d"),
            end=(end_date + timedelta(days=1)).strftime("%Y-%m-%d"),
        )
        
        if DEBUG:
            print(f"[DEBUG] Yahoo fetch for {symbol}:")
            print(f"  COLUMNS: {list(df.columns)}")
            print(f"  SHAPE: {df.shape}")
            print(f"  DTYPES:\n{df.dtypes}")

        if df.empty:
            log.warning(f"Yahoo: no data for {symbol}")
            return None

        if DEBUG:
            print(f"[DEBUG] ✓ Successfully fetched {len(df)} rows for {symbol}")
        return df

    except Exception as e:
        log.error(f"Yahoo fetch failed for {symbol}: {e}")
        if DEBUG:
            import traceback
            traceback.print_exc()
        return None

def build_graph_dataset(ticker_label, yahoo_symbol, today):
    """
    Build a 30-day rolling OHLCV + indicator dataset for a given ticker.
    Returns a DataFrame with the final 30 rows, oldest first.
    """

    # PATCHED: Pull ~150 days to warm up indicators
    end = today
    start = end - timedelta(days=150)

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
    One file per ticker, 8.3 name: TTTYYMM.TXT
    """
    ticker_label = re.sub(r'[^A-Z0-9]', '', ticker_label.upper())[:3]
    if len(ticker_label) < 3:
        ticker_label = ticker_label.ljust(3, '0')
    
    filename = make_graph_filename(ticker_label, date)
    filepath = DATA_DIR / filename

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
    """Append filename and timestamp to manifest."""
    try:
        with open(MANIFEST_FILE, "a") as f:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"{ts} {filename}\n")
    except Exception as e:
        log.warning(f"Failed to update manifest: {e}")

# =============================================================
# PRUNING & ARCHIVING
# =============================================================

def prune_and_archive():
    """
    Move files older than RETAIN_DAYS to archive.
    Delete archive files older than ARCHIVE_DAYS.
    Handles QX, QM, TT, and US files.
    """
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    now = datetime.now()

    pattern = re.compile(r'^(QX|QM|US|TT[A-Z0-9]{3})(\d{6})\.TXT$')

    # Move old files to archive
    for fname in os.listdir(DATA_DIR):
        m = pattern.match(fname)
        if not m:
            continue
        prefix = m.group(1)
        datestr = m.group(2)
        try:
            if prefix in ("QX", "QM") or prefix.startswith("TT"):
                fdate = datetime.strptime(datestr, "%y%m%d")
            elif prefix == "US":
                fdate = datetime.strptime(datestr, "%m%d%y")
            else:
                continue
            age = (now - fdate).days
            if age > RETAIN_DAYS:
                src = DATA_DIR / fname
                dst = ARCHIVE_DIR / fname
                shutil.move(str(src), str(dst))
                log.info(f"Archived: {fname} (age {age}d)")
        except ValueError:
            continue

    # Delete archive files older than ARCHIVE_DAYS
    for fname in os.listdir(ARCHIVE_DIR):
        m = pattern.match(fname)
        if not m:
            continue
        prefix = m.group(1)
        datestr = m.group(2)
        try:
            if prefix in ("QX", "QM") or prefix.startswith("TT"):
                fdate = datetime.strptime(datestr, "%y%m%d")
            elif prefix == "US":
                fdate = datetime.strptime(datestr, "%m%d%y")
            else:
                continue
            age = (now - fdate).days
            if age > ARCHIVE_DAYS:
                os.remove(ARCHIVE_DIR / fname)
                log.info(f"Deleted from archive: {fname} (age {age}d)")
        except ValueError:
            continue

# =============================================================
# MAIN (PATCHED WITH PROGRESS NOTIFICATIONS)
# =============================================================

def main():
    """Orchestrate complete data pull: fiscal, index, history, graph."""
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(ARCHIVE_DIR, exist_ok=True)

    today = datetime.now()
    notify(f"=== QXNet pull starting {today.strftime('%Y-%m-%d')} (env={ENVIRONMENT}) ===")

    try:
        # ------------------------------------------------------------
        # 1. Fiscal snapshot (QX)
        # ------------------------------------------------------------
        notify("Fetching fiscal snapshot (QX)...")

        fiscal_values = {}
        for field, (series_id, scale, fallback) in FISCAL_SERIES.items():
            notify(f"  • FRED {field} ({series_id})")
            fiscal_values[field] = fetch_fred(series_id, scale, fallback)

        prev_ai = load_prev_ai_capex()
        fiscal_values = compute_derived(fiscal_values, prev_ai)
        save_ai_capex(fiscal_values["ai_capex"])

        fiscal_file = write_fiscal_file(today, fiscal_values)
        update_manifest(fiscal_file)

        notify(f"Fiscal snapshot complete → {fiscal_file}")

        # ------------------------------------------------------------
        # 2. 30‑day fiscal history (US)
        # ------------------------------------------------------------
        notify("Building 30‑day fiscal history (US)...")

        hist_df = build_fiscal_history_dataset(today)
        if hist_df is not None and not hist_df.empty:
            us_file = write_fiscal_history_file(today, hist_df)
            update_manifest(us_file)
            notify(f"Fiscal history complete → {us_file}")
        else:
            notify("WARNING: Fiscal history dataset empty — skipping.")

        # ------------------------------------------------------------
        # 3. Index snapshot (QM)
        # ------------------------------------------------------------
        notify("Fetching index snapshot (QM)...")

        index_values = {}
        for field, (series_id, scale, fallback) in INDEX_SERIES.items():
            notify(f"  • FRED index {field} ({series_id})")
            index_values[field] = fetch_fred(series_id, scale, fallback)

        index_file = write_index_file(today, index_values)
        update_manifest(index_file)

        notify(f"Index snapshot complete → {index_file}")

        # ------------------------------------------------------------
        # 4. QXGraph Yahoo pull
        # ------------------------------------------------------------
        notify("Pulling Yahoo OHLCV + indicators (QXGraph)...")

        graph_count = 0
        for ticker_label, yahoo_symbol in GRAPH_SERIES.items():
            notify(f"  • Processing {ticker_label} ({yahoo_symbol})...")

            try:
                df_graph = build_graph_dataset(ticker_label, yahoo_symbol, today)
                if df_graph is None or df_graph.empty:
                    notify(f"    → No data for {ticker_label}, skipping.")
                    continue

                graph_file = write_graph_file(today, ticker_label, df_graph)
                update_manifest(graph_file)
                notify(f"    → Completed {ticker_label}: {graph_file}")
                graph_count += 1

            except Exception as e:
                notify(f"    ERROR: QXGraph {ticker_label} failed: {e}")
                log.error(f"QXGraph {ticker_label} failed", exc_info=True)

        # ------------------------------------------------------------
        # 5. Prune & archive
        # ------------------------------------------------------------
        notify("Pruning and archiving old files...")
        prune_and_archive()
        notify("Pruning complete.")

        # ------------------------------------------------------------
        # DONE
        # ------------------------------------------------------------
        notify(
            f"=== QXNet pull complete — "
            f"{len(fiscal_values)} fiscal fields, "
            f"{len(index_values)} index fields, "
            f"{graph_count}/{len(GRAPH_SERIES)} graph tickers, "
            f"30‑day US history generated ==="
        )

    except Exception as e:
        notify(f"FATAL ERROR: {e}")
        log.error("FATAL", exc_info=True)
        raise

if __name__ == "__main__":
    main()
