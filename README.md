# QXNet Pull — Daily Data Digestion for QuantXT / QXGraph

A Python script that automatically fetches, processes, and archives fiscal, index, and market data from FRED and Yahoo Finance into 8.3-compliant `.TXT` files for use with QuantXT platform.

---

## Overview

**QXNet Pull** aggregates daily financial data into standardized snapshots and rolling 30-day histories:

| File Type | Description | Format | Source |
|-----------|-------------|--------|--------|
| **QX** | FRED fiscal snapshot | `QXYYMMDD.TXT` | Federal Reserve (FRED) |
| **QM** | FRED index snapshot | `QMYYMMDD.TXT` | Federal Reserve (FRED) |
| **TT** | Market OHLCV + TA | `TTTYYMM.TXT` | Yahoo Finance |
| **US** | 30-day fiscal history | `USMMDDYY.TXT` | Federal Reserve (FRED) |

Data is automatically pruned and archived to keep storage efficient.

---

# 📦 Setup Program Enhancements (v1.0)

The `setup_qxnet.py` installer has been upgraded to provide a smoother, more robust, and fully cross‑platform setup experience. These improvements apply to both **local** (`~/.qxnet`) and **production** (`/var/qxnet`) deployments.

### **1. Cross‑Platform Masked API Key Input**
Entering your FRED API key now uses a secure, masked input method:

- **Windows:** Uses `msvcrt` for raw key capture  
- **Linux/macOS:** Uses `tty` + `termios`  
- Characters appear as `*` while typing  
- Backspace and Ctrl‑C behave correctly  
- Terminal state is always restored safely  

This replaces the previous `getpass()` behavior that showed no feedback while typing.

---

### **2. Automatic Dependency Detection**
Before creating directories or writing configuration files, the setup program now checks for required Python packages:

- `pandas`  
- `yfinance`  
- `requests`  

Each dependency is displayed with color‑coded status:

- **✓ Dependency OK**  
- **✗ Missing**  

---

### **3. Optional Auto‑Install of Missing Packages**
If any dependencies are missing, the installer now offers:



## Function Reference

### Data Fetching Functions

#### `fetch_fred(series_id, scale, fallback)`
Fetches the latest value for a FRED series.

**Parameters:**
- `series_id` (str): FRED series identifier (e.g., `"UNRATE"`)
- `scale` (float): Multiplier for the value
- `fallback` (float): Default value if fetch fails

**Returns:** `float` — Latest value × scale, or fallback

**Example:**
```python
unemployment = fetch_fred("UNRATE", 1.0, 4.0)  # Latest unemployment rate
```

---

#### `fetch_fred_history(series_id, scale, fallback, start_date, end_date)`
Fetches historical values for a FRED series over a date range.

**Parameters:**
- `series_id` (str): FRED series ID
- `scale` (float): Multiplier for values
- `fallback` (float): Default if series is empty
- `start_date` (datetime): Start of range
- `end_date` (datetime): End of range

**Returns:** `pd.Series` — Indexed by date, values are scaled FRED observations

**Example:**
```python
gdp_history = fetch_fred_history("A191RL1Q225SBEA", 1.0, 2.5, 
                                  start_date, end_date)
```

---

#### `fetch_yahoo_ohlcv(symbol, start_date, end_date)`
Fetches raw daily OHLCV (Open, High, Low, Close, Volume) data from Yahoo Finance.

**Parameters:**
- `symbol` (str): Yahoo ticker (e.g., `"^GSPC"`, `"^NDX"`)
- `start_date` (datetime): Start date
- `end_date` (datetime): End date

**Returns:** `pd.DataFrame` — Columns: Open, High, Low, Close, Volume, Adj Close

**Handles:**
- Multi-level column indices from yfinance
- Auto-fallback to `Ticker.history()` if download fails
- Corrupted responses with malformed data

---

### Data Processing Functions

#### `compute_indicators(df)`
Computes 13 technical indicators on OHLCV data.

**Input:** DataFrame with columns: `Open`, `High`, `Low`, `Close`, `Volume`

**Output Indicators:**
- **VWAP** — Volume Weighted Average Price
- **RSI(14)** — Relative Strength Index
- **MACD** — Moving Average Convergence Divergence + Signal + Histogram
- **SMA20, SMA50** — Simple Moving Averages
- **BB Upper/Lower** — Bollinger Bands (20, 2)
- **ATR(14)** — Average True Range
- **OBV** — On-Balance Volume
- **Stoch K, Stoch D** — Stochastic Oscillator

**Example:**
```python
df_with_indicators = compute_indicators(raw_ohlcv_df)
# Adds 13 new columns to the DataFrame
```

---

#### `build_fiscal_history_dataset(today)`
Builds a 30-day rolling daily fiscal dataset from FRED series.

**Parameters:**
- `today` (datetime): Reference date

**Returns:** `pd.DataFrame` — 30 rows × 19 columns (all HISTORY_FIELDS)

**Fields included:**
- Fiscal: int_rev, debt_gdp, usd_reserve_share, cbo_deficit
- Rates: xdate, sahm, tail_risk, liq_gap, ofr, hy_spread
- Market: dxy_mom, oil_price, ai_capex, geopolitical_risk
- Economics: infl, unemp, gdp, investor_sentiment

---

#### `build_graph_dataset(ticker_label, yahoo_symbol, today)`
Builds a 30-day rolling OHLCV + 13 indicators dataset for a single ticker.

**Parameters:**
- `ticker_label` (str): Friendly name (e.g., `"SPX"`)
- `yahoo_symbol` (str): Yahoo ticker (e.g., `"^GSPC"`)
- `today` (datetime): Reference date

**Returns:** `pd.DataFrame` — 30 rows × 19 columns (OHLCV + indicators)

---

### File Writing Functions

#### `write_fiscal_file(date, values)`
Writes a snapshot of fiscal data to `QXYYMMDD.TXT`.

**Format:**
```
QXNET FISCAL DATA 2026-05-31
VERSION 1
FIELDS 19
INT_REV 1.234567
DEBT_GDP 125.456789
...
END
```

---

#### `write_index_file(date, values)`
Writes a snapshot of index data to `QMYYMMDD.TXT`.

**Format:**
```
QXNET INDEX DATA 2026-05-31
VERSION 1
FIELDS 3
SP500 5432.10
DJIA 42567.89
NASDAQ 17234.56
END
```

---

#### `write_fiscal_history_file(date, df)`
Writes 30-day rolling fiscal history to `USMMDDYY.TXT`.

**Format:**
```
# name int_rev debt_gdp ... investor_sentiment
day_01 1.234 125.456 ... 0.789
day_02 1.235 125.457 ... 0.790
...
day_30 1.245 125.567 ... 0.799
END
```

---

#### `write_graph_file(date, ticker_label, df)`
Writes 30-day rolling OHLCV + indicators to `TTTYYMM.TXT`.

**Format:**
```
# ticker SPX
# name open high low close volume vwap rsi macd ... stoch_d
day_01 5400.00 5420.50 5395.00 5410.25 1234567 5408.58 55.23 0.45 ... 45.67
...
day_30 5500.00 5520.50 5495.00 5510.25 1567890 5508.58 62.34 1.23 ... 52.34
END
```

---

#### `update_manifest(filename)`
Appends a newly written filename to `MANIFEST.TXT` for XT client retrieval.

---

### Utility Functions

#### `prune_and_archive()`
Manages file lifecycle:
1. Moves files older than `RETAIN_DAYS` from `DATA_DIR` → `ARCHIVE_DIR`
2. Deletes files in `ARCHIVE_DIR` older than `ARCHIVE_DAYS`

Handles all 4 file types: QX, QM, TT, US

---

#### `load_prev_ai_capex()` / `save_ai_capex(value)`
Persists AI CapEx values across runs for lagged indicator computation.

**File:** `/var/qxnet/qxlag.txt`

---

#### `make_filename(prefix, date)`
Generates 8.3-compliant filename.

**Example:**
```python
make_filename("QX", datetime(2026, 5, 31))  # → "QX260531.TXT"
make_filename("US", datetime(2026, 5, 31))  # → "US053126.TXT"
```

---

### Main Execution

#### `main()`
Orchestrates the entire data pull:

1. **Fiscal Snapshot (QX)** — Fetch latest values for 16 FRED series
2. **Fiscal History (US)** — Build 30-day rolling history
3. **Index Snapshot (QM)** — Fetch latest index values
4. **Graph Data (TT)** — Fetch and compute 30-day rolling OHLCV + indicators for each ticker
5. **Maintenance** — Prune old files and archive

Logs all operations to `LOG_FILE`.

---

## FRED Series Mapping

The script monitors 16 fiscal/economic indicators. Each series has:
- **FRED ID** — Official series identifier
- **Scale** — Multiplier applied
- **Fallback** — Default if fetch fails

```python
FISCAL_SERIES = {
    "int_rev":            ("FYOIGDA188S",      1.0,    20.0),  # Interest Revenue
    "debt_gdp":           ("GFDEGDQ188S",      1.0,   125.0),  # Debt-to-GDP
    "usd_reserve_share":  ("TRESEGUS",         1.0,    57.0),  # USD Reserve Share %
    "cbo_deficit":        ("FYFSGDA188S",     -1.0,     6.0),  # CBO Deficit
    "sahm":               ("SAHMREALTIME",     1.0,     0.3),  # Sahm Rule
    "hy_spread":          ("BAMLH0A0HYM2",     1.0,   450.0),  # High-Yield Spread (bps)
    "ofr":                ("NFCI",             1.0,     0.1),  # OFR Financial Conditions
    "dxy_mom":            ("DTWEXBGS",         1.0,   104.0),  # Dollar Index Momentum
    "oil_price":          ("DCOILWTICO",       1.0,    80.0),  # WTI Crude Oil ($/bbl)
    "infl":               ("CPIAUCSL",         1.0,     3.5),  # CPI (Inflation)
    "unemp":              ("UNRATE",           1.0,     4.0),  # Unemployment Rate
    "gdp":                ("A191RL1Q225SBEA",  1.0,     2.5),  # Real GDP Growth
    "tail_risk":          ("VIXCLS",           0.05,    1.0),  # VIX (scaled)
    "liq_gap":            ("TEDRATE",          1.0,     0.5),  # TED Spread (Liquidity)
    "ai_capex":           ("B009RC1Q027SBEA",  0.001,   2.5),  # AI CapEx Spending
    "geopolitical_risk":  ("GPR",              0.02,    0.5),  # Geopolitical Risk Index
}
```

---

## Market Tickers (QXGraph)

```python
GRAPH_SERIES = {
    "SPX": "^GSPC",   # S&P 500
    "NDX": "^NDX",    # Nasdaq 100
}
```

Add more tickers by extending `GRAPH_SERIES`:
```python
GRAPH_SERIES = {
    "SPX": "^GSPC",
    "NDX": "^NDX",
    "DJI": "^DJI",    # Dow Jones
    "RUT": "^RUT",    # Russell 2000
}
```

---

## Deployment: Cron Schedule

### Linux/macOS Cron

Edit crontab:
```bash
crontab -e
```

Add entry (runs daily at 6:00 AM):
```cron
0 6 * * * /usr/bin/python3 /opt/qxnet/qxpull.py >> /var/qxnet/qxpull.log 2>&1
```

### Windows Task Scheduler

1. Open **Task Scheduler**
2. Create Basic Task
3. **Trigger:** Daily at 6:00 AM
4. **Action:** 
   - Program: `C:\Python\python.exe`
   - Arguments: `C:\var\qxnet\qxpull.py`
   - Start in: `C:\var\qxnet`

---

## Output Files

### Daily Generated Files

```
/var/qxnet/data/
├── QX260531.TXT          # Fiscal snapshot
├── QM260531.TXT          # Index snapshot
├── SPX26060.TXT          # S&P 500 (30d rolling)
├── NDX26060.TXT          # Nasdaq 100 (30d rolling)
└── US053126.TXT          # Fiscal history (30d rolling)
```

### Archived Files (30+ days old)

```
/var/qxnet/archive/
├── QX260501.TXT
├── QM260501.TXT
├── SPX26060.TXT
└── US050126.TXT
```

### Manifest

```
/var/qxnet/data/MANIFEST.TXT
QX260531.TXT
QM260531.TXT
SPX26060.TXT
NDX26060.TXT 
US053126.TXT
```

---

## Logging

All operations are logged to `LOG_FILE` (`/var/qxnet/qxpull.log`):

```
2026-05-31 06:00:15 INFO === QXNet pull starting 2026-05-31 ===
2026-05-31 06:00:18 INFO Written: QX260531.TXT
2026-05-31 06:00:25 INFO Written US history file: US053126.TXT
2026-05-31 06:00:27 INFO Written: QM260531.TXT
2026-05-31 06:00:35 INFO Written QXGraph file: SPX26060.TXT
2026-05-31 06:00:42 INFO Written QXGraph file: NDX26060.TXT
2026-05-31 06:00:45 INFO Archived: QX260501.TXT (age 30d)
2026-05-31 06:00:45 INFO === QXNet pull complete — 16 fiscal fields, 3 index fields, 2 graph tickers, 30-day US history generated ===
```

---

## Troubleshooting

### Issue: "cannot reindex on an axis with duplicate labels"

**Cause:** yfinance returned malformed MultiIndex columns

**Solution:**
```bash
pip install --upgrade yfinance
```

The fixed script auto-drops 'Adj Close' to avoid duplicate 'Close' columns.

---

### Issue: "Yahoo Finance did not return a close price column"

**Cause:** Yahoo API returned unexpected data format

**Solution:** Check:
1. Ticker symbol is correct (e.g., `^GSPC` not `GSPC`)
2. Update yfinance: `pip install --upgrade yfinance`
3. Check internet connection
4. Try manually: `python -c "import yfinance as yf; print(yf.download('^GSPC')[:5])"`

---

### Issue: "FRED API key invalid"

**Cause:** API key expired or incorrect

**Solution:**
1. Verify key at [https://fredaccount.stlouisfed.org](https://fredaccount.stlouisfed.org)
2. Copy exact key into `FRED_API_KEY`
3. Restart script

---

### Issue: "Permission denied" creating files

**Cause:** DATA_DIR or ARCHIVE_DIR not writable

**Solution:**
```bash
sudo mkdir -p /var/qxnet/{data,archive}
sudo chmod 755 /var/qxnet
sudo chmod 755 /var/qxnet/{data,archive}
```

---

## Performance Notes

- **Fetch time:** ~10-15 seconds (FRED: ~5s, Yahoo: ~10s)
- **Processing:** ~2-5 seconds (indicators, file writes)
- **Total:** ~15-20 seconds per run
- **Memory:** ~50-100 MB per run

---

## File Format Reference

### 8.3 Filename Convention

| Type | Format | Example | Max Age |
|------|--------|---------|---------|
| QX | `QXYYMMDD.TXT` | `QX260531.TXT` | 30 days |
| QM | `QMYYMMDD.TXT` | `QM260531.TXT` | 30 days |
| TT | `TTTYYMM.TXT` | `SPX26060.TXT` | 30 days |
| US | `USMMDDYY.TXT` | `US053126.TXT` | 30 days |

---

## API Rate Limits

- **FRED:** 120 requests/minute (we make ~20/run)
- **Yahoo:** No official limit; auto-backoff if throttled

---

## Support & Updates

For issues or feature requests, check:
- Script logs: `/var/qxnet/qxpull.log`
- FRED status: [https://research.stlouisfed.org/fred/](https://research.stlouisfed.org/fred/)
- Yahoo Finance status: [https://finance.yahoo.com/](https://finance.yahoo.com/)

---

**Last Updated:** May 31, 2026  
**Version:** 1.2  
**Python:** 3.8+
