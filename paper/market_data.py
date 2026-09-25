"""Market data module for reading, fetching, and validating candle data."""
import csv
import datetime as dt
import json
import math
from pathlib import Path
import urllib.request


class DataError(ValueError):
    """Raised when market data is invalid, corrupt, or out of sequence."""
    pass


def validate_candles(rows, min_candles=100):
    """
    Validate OHLC candle records.
    Requires strictly increasing dates/timestamps and valid OHLC bounds.
    """
    if len(rows) < min_candles:
        raise DataError(f"At least {min_candles} candles required, got {len(rows)}")

    previous_time = None
    validated = []

    for idx, row in enumerate(rows):
        timestamp = row.get("time") or row.get("date")
        if not timestamp:
            raise DataError(f"Missing timestamp/date at row {idx}")

        if previous_time is not None and timestamp <= previous_time:
            raise DataError(f"Timestamps must be strictly increasing: {timestamp} <= {previous_time}")
        previous_time = timestamp

        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        if not (math.isfinite(o) and math.isfinite(h) and math.isfinite(l) and math.isfinite(c)):
            raise DataError(f"Non-finite price at row {idx}")
        if min(o, h, l, c) <= 0:
            raise DataError(f"Non-positive price at row {idx}")
        if not (l <= min(o, c) <= max(o, c) <= h):
            raise DataError(f"Invalid OHLC structure at row {idx}: O={o}, H={h}, L={l}, C={c}")

        item = dict(date=str(timestamp), time=timestamp, open=o, high=h, low=l, close=c)
        if "volume" in row:
            item["volume"] = float(row["volume"])
        validated.append(item)

    return validated


def load_csv_candles(path, min_candles=100):
    """Load and validate candles from a CSV file."""
    path = Path(path)
    if not path.exists():
        raise DataError(f"Candle file not found: {path}")

    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    return validate_candles(rows, min_candles=min_candles)


def fetch_coinbase_candles(days=299):
    """Fetch public daily candles from Coinbase REST API (key-free, public)."""
    end = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - dt.timedelta(days=days)
    url = (
        "https://api.exchange.coinbase.com/products/ETH-USD/candles?granularity=86400"
        f"&start={start.isoformat()}&end={end.isoformat()}"
    )
    request = urllib.request.Request(url, headers={"User-Agent": "ETHPaperValidationEngine/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        candles = json.load(response)

    rows = [
        {
            "date": dt.datetime.fromtimestamp(x[0], dt.timezone.utc).date().isoformat(),
            "time": x[0],
            "open": float(x[3]),
            "high": float(x[2]),
            "low": float(x[1]),
            "close": float(x[4]),
        }
        for x in sorted(candles)
        if x[0] < end.timestamp()
    ]

    return validate_candles(rows, min_candles=100)
