"""Baseline strategies for comparative benchmark evaluation."""
import hashlib
import statistics
from typing import Any, Dict, List


class BuyAndHoldStrategy:
    """Benchmark buy-and-hold strategy entering on bar 1 and holding throughout."""

    def __init__(self):
        self.name = "buy_and_hold"
        self.version = "v1.0"
        self.entered = False

    def get_source_hash(self) -> str:
        return hashlib.sha256(f"{self.name}:{self.version}".encode("utf-8")).hexdigest()[:16]

    def generate_signal(self, candle_history: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not self.entered and len(candle_history) >= 10:
            self.entered = True
            return {"side": 1, "atr": 10.0, "stop_distance": 1e6, "target_distance": 1e6, "label": "LONG"}
        return {"side": 0, "atr": 0.0, "stop_distance": 0.0, "target_distance": 0.0, "label": "WAIT"}


class MovingAverageCrossoverStrategy:
    """Benchmark SMA crossover strategy (Fast SMA vs Slow SMA)."""

    def __init__(self, fast: int = 10, slow: int = 50):
        self.name = "ma_crossover"
        self.version = "v1.0"
        self.fast = fast
        self.slow = slow

    def get_source_hash(self) -> str:
        return hashlib.sha256(f"{self.name}:{self.version}:{self.fast}:{self.slow}".encode("utf-8")).hexdigest()[:16]

    def generate_signal(self, candle_history: List[Dict[str, Any]]) -> Dict[str, Any]:
        if len(candle_history) < self.slow + 1:
            return {"side": 0, "atr": 0.0, "label": "WAIT"}

        closes = [c["close"] for c in candle_history[-(self.slow + 1):]]
        fast_curr = statistics.mean(closes[-self.fast:])
        slow_curr = statistics.mean(closes[-self.slow:])
        fast_prev = statistics.mean(closes[-self.fast - 1:-1])
        slow_prev = statistics.mean(closes[-self.slow - 1:-1])

        ranges = [max(c["high"] - c["low"], 0.01) for c in candle_history[-14:]]
        atr = statistics.mean(ranges)

        side = 0
        if fast_prev <= slow_prev and fast_curr > slow_curr:
            side = 1
        elif fast_prev >= slow_prev and fast_curr < slow_curr:
            side = -1

        return {
            "side": side,
            "atr": atr,
            "stop_distance": 2.0 * atr,
            "target_distance": 3.0 * atr,
            "label": {1: "LONG", -1: "SHORT", 0: "WAIT"}[side],
        }
