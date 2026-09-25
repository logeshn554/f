"""ETH Guard strategy module combining trend confirmation, RSI, and volatility controls."""
import hashlib
import statistics
from typing import Any, Dict, List


class ETHGuardStrategy:
    """ETH Guard v3 strategy combining SMA trend, RSI pullback, and ATR volatility limits."""

    def __init__(self, sma_fast: int = 20, sma_slow: int = 100, rsi_min: float = 30.0, rsi_max: float = 48.0):
        self.name = "eth_guard"
        self.version = "v3.0"
        self.sma_fast = sma_fast
        self.sma_slow = sma_slow
        self.rsi_min = rsi_min
        self.rsi_max = rsi_max

    def get_source_hash(self) -> str:
        """Return deterministic hash of strategy code and parameters."""
        raw = f"{self.name}:{self.version}:{self.sma_fast}:{self.sma_slow}:{self.rsi_min}:{self.rsi_max}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def generate_signal(self, candle_history: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate signal for ETH Guard strategy."""
        if len(candle_history) < self.sma_slow + 1:
            return {"side": 0, "atr": 0.0, "label": "WAIT"}

        recent = candle_history[-(self.sma_slow + 1):]
        closes = [c["close"] for c in recent]

        sma20 = statistics.mean(closes[-self.sma_fast:])
        sma100 = statistics.mean(closes[-self.sma_slow:])
        old100 = statistics.mean(closes[-(self.sma_slow + 1):-1])

        changes = [closes[i] - closes[i - 1] for i in range(len(closes) - 14, len(closes))]
        gain = sum(max(v, 0.0) for v in changes)
        loss = sum(max(-v, 0.0) for v in changes)
        rsi = 100.0 * gain / (gain + loss) if (gain + loss) > 0 else 50.0

        ranges = [
            max(c["high"] - c["low"], abs(c["high"] - closes[i - 1]), abs(c["low"] - closes[i - 1]))
            for i, c in enumerate(recent[1:], 1)
        ]
        atr = statistics.mean(ranges[-14:]) if len(ranges) >= 14 else 0.0

        current_close = closes[-1]
        signal = (
            current_close > sma100
            and sma100 > old100
            and current_close < sma20
            and self.rsi_min <= rsi <= self.rsi_max
            and (atr / current_close if current_close > 0 else 0) < 0.08
        )

        side = 1 if signal else 0
        label = "LONG" if side == 1 else "WAIT"
        stop_dist = 2.0 * atr if atr > 0 else 20.0
        target_dist = 3.0 * atr if atr > 0 else 30.0

        return {
            "side": side,
            "atr": atr,
            "rsi": rsi,
            "stop_distance": stop_dist,
            "target_distance": target_dist,
            "label": label,
        }
