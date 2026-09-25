"""
Candle Paths v4 strategy module for candle geometry and historical scenario analysis.

Source hash is computed from the ACTUAL BYTECODE of this file plus canonical
parameters so that any logic change — even without bumping version strings —
produces a new hash and fails manifest matching.
"""
import hashlib
import inspect
import statistics
from typing import Any, Dict, List


def _file_bytes() -> bytes:
    """Return the raw UTF-8 bytes of this source file (stable across platforms)."""
    import pathlib
    return pathlib.Path(__file__).read_bytes()


class CandlePathsStrategy:
    """Strategy based on multi-bar candle geometry path clusters."""

    def __init__(self, atr_period: int = 14, min_path_len: int = 5):
        self.name = "candle_paths"
        self.version = "v4.0"
        self.atr_period = atr_period
        self.min_path_len = min_path_len

    def get_source_hash(self) -> str:
        """
        Deterministic hash of:
          1. The raw bytes of this .py file (detects any logic change)
          2. Canonical parameter values (detects hyper-parameter changes)

        A changed hash means a new experiment; it never overwrites the old one.
        """
        param_str = f"{self.atr_period}:{self.min_path_len}"
        h = hashlib.sha256(_file_bytes())
        h.update(param_str.encode("utf-8"))
        return h.hexdigest()[:16]

    def calculate_atr(self, candles: List[Dict[str, Any]]) -> float:
        """Calculate Average True Range over the last atr_period bars."""
        if len(candles) < self.atr_period + 1:
            return 0.0
        ranges = []
        for i in range(len(candles) - self.atr_period, len(candles)):
            c = candles[i]
            prev_c = candles[i - 1]["close"]
            tr = max(
                c["high"] - c["low"],
                abs(c["high"] - prev_c),
                abs(c["low"] - prev_c),
            )
            ranges.append(tr)
        return statistics.mean(ranges) if ranges else 0.0

    def generate_signal(self, candle_history: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Generate a directional signal from candle path momentum and geometry.

        candle_history must contain only bars whose close is already fully known
        (i.e. the bar preceding the execution bar).  The caller (walk_forward.py)
        guarantees this by passing candles[:absolute_index].
        """
        if len(candle_history) < 100:
            return {"side": 0, "atr": 0.0, "label": "WAIT"}

        recent = candle_history[-100:]
        closes = [c["close"] for c in recent]
        atr = self.calculate_atr(recent)

        if atr == 0.0 or closes[-1] <= 0:
            return {"side": 0, "atr": 0.0, "label": "WAIT"}

        sma20 = statistics.mean(closes[-20:])
        sma60 = statistics.mean(closes[-60:])
        atr_ratio = atr / closes[-1]

        # Directional efficiency over the last 20 bars
        travel = sum(abs(closes[i] - closes[i - 1]) for i in range(len(closes) - 20, len(closes)))
        efficiency = abs(closes[-1] - closes[-21]) / travel if travel > 0 else 0.0

        side = 0
        if 0.001 <= atr_ratio <= 0.05 and efficiency >= 0.25:
            if closes[-1] > max(c["high"] for c in recent[-13:-1]) and closes[-1] > sma20 > sma60:
                side = 1
            elif closes[-1] < min(c["low"] for c in recent[-13:-1]) and closes[-1] < sma20 < sma60:
                side = -1

        label = {1: "LONG", -1: "SHORT", 0: "WAIT"}[side]
        stop_dist = 2.0 * atr if atr > 0 else 10.0
        target_dist = 3.0 * atr if atr > 0 else 15.0

        return {
            "side": side,
            "atr": atr,
            "stop_distance": stop_dist,
            "target_distance": target_dist,
            "label": label,
        }
