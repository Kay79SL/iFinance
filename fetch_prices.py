#!/usr/bin/env python3
"""
Daily price fetcher for the family financial tracker.

Reads tickers.json (list of symbols), fetches latest prices via yfinance,
writes results to prices.json. Designed to run in GitHub Actions on a
daily schedule so the HTML tracker can pull fresh data from the repo's
raw content URL — which has permissive CORS and works from file://.

Usage (local):
    pip install yfinance
    python fetch_prices.py

In GitHub Actions, see .github/workflows/update-prices.yml.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import yfinance as yf
except ImportError:
    print("yfinance not installed. Run: pip install yfinance", file=sys.stderr)
    sys.exit(1)

BASE = Path(__file__).resolve().parent
TICKERS_FILE = BASE / "tickers.json"
OUTPUT_FILE = BASE / "prices.json"
DEFAULT_TICKERS = ["ABBV", "LLY", "ABT"]


def load_tickers() -> list[str]:
    """Load ticker list from tickers.json. Accepts a plain array or {'tickers': [...]}."""
    if not TICKERS_FILE.exists():
        print(f"No {TICKERS_FILE.name}, using defaults: {DEFAULT_TICKERS}")
        return DEFAULT_TICKERS
    try:
        data = json.loads(TICKERS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            tickers = data
        elif isinstance(data, dict) and "tickers" in data:
            tickers = data["tickers"]
        else:
            print(f"Unrecognised format in {TICKERS_FILE.name}, using defaults")
            return DEFAULT_TICKERS
        cleaned = [str(t).strip().upper() for t in tickers if str(t).strip()]
        return cleaned or DEFAULT_TICKERS
    except Exception as e:
        print(f"Error reading {TICKERS_FILE.name}: {e}, using defaults")
        return DEFAULT_TICKERS


def fetch_one(ticker: str) -> dict | None:
    """Fetch the latest available price for a single ticker.

    Uses yfinance's fast_info when available, falls back to history().
    Handles weekends/holidays automatically: history(period='5d') returns
    the last trading day's close.
    """
    try:
        t = yf.Ticker(ticker)
        price = None
        prev_close = None
        currency = "USD"

        # Try fast_info first (much faster than .info)
        try:
            fi = t.fast_info
            price = _safe_float(fi.get("last_price"))
            prev_close = _safe_float(fi.get("previous_close"))
            currency = fi.get("currency") or "USD"
        except Exception:
            pass

        # Fallback: use recent history
        if not price or price <= 0:
            hist = t.history(period="5d", auto_adjust=False)
            if not hist.empty and "Close" in hist.columns:
                closes = hist["Close"].dropna()
                if len(closes) >= 1:
                    price = float(closes.iloc[-1])
                if len(closes) >= 2 and not prev_close:
                    prev_close = float(closes.iloc[-2])

        if not price or price <= 0:
            return None

        change = None
        change_pct = None
        if prev_close and prev_close > 0:
            change = price - prev_close
            change_pct = (change / prev_close) * 100.0

        return {
            "ticker": ticker,
            "price": round(price, 4),
            "previous_close": round(prev_close, 4) if prev_close else None,
            "change": round(change, 4) if change is not None else None,
            "change_pct": round(change_pct, 4) if change_pct is not None else None,
            "currency": currency,
        }
    except Exception as e:
        print(f"  Error fetching {ticker}: {e}", file=sys.stderr)
        return None


def _safe_float(v):
    try:
        f = float(v)
        return f if f == f else None  # filter NaN
    except (TypeError, ValueError):
        return None


def main() -> int:
    tickers = load_tickers()
    print(f"Fetching prices for {len(tickers)} tickers: {', '.join(tickers)}")

    now = datetime.now(timezone.utc)
    prices: dict[str, dict] = {}
    ok = 0
    fail = 0

    for ticker in tickers:
        result = fetch_one(ticker)
        if result:
            prices[ticker] = result
            ok += 1
            chg = ""
            if result.get("change_pct") is not None:
                sign = "+" if result["change_pct"] >= 0 else ""
                chg = f" ({sign}{result['change_pct']:.2f}%)"
            print(f"  {ticker}: ${result['price']}{chg}")
        else:
            fail += 1
            print(f"  {ticker}: FAILED")

    output = {
        "updated_at": now.isoformat(),
        "updated_date": now.strftime("%Y-%m-%d"),
        "source": "Yahoo Finance via yfinance",
        "prices": prices,
    }

    OUTPUT_FILE.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {OUTPUT_FILE.name}")
    print(f"Success: {ok}, Failed: {fail}")

    # Only fail the workflow if everything failed
    if fail > 0 and ok == 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())