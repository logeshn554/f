"""Prospective forward paper evidence module for live prospective tracking."""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from paper.broker import PaperBroker
from research.cost_model import CostModel


class ForwardEvidenceTracker:
    """Tracks prospective forward paper trades independently from historical backtest folds."""

    def __init__(self, log_path: str = "reports/forward_evidence.json"):
        self.log_path = Path(log_path)
        self.broker = PaperBroker(initial_cash=100.0, cost_model=CostModel())
        self.history: List[Dict[str, Any]] = []

    def record_step(self, candle: Dict[str, Any], signal: Dict[str, Any]):
        """Record a prospective forward paper step."""
        self.broker.step(candle, signal)
        entry = {
            "time": candle.get("time", candle.get("date")),
            "close": candle["close"],
            "signal": signal,
            "equity": self.broker.equity(candle["close"]),
            "trades_count": len(self.broker.trades),
        }
        self.history.append(entry)
        self.save()

    def save(self):
        """Save prospective forward evidence log to disk."""
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "type": "PROSPECTIVE_FORWARD_PAPER_EVIDENCE",
            "initial_cash": self.broker.initial_cash,
            "current_equity": self.broker.equity(self.history[-1]["close"]) if self.history else 100.0,
            "total_steps": len(self.history),
            "closed_trades_count": len(self.broker.trades),
            "trades": self.broker.trades,
        }
        self.log_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
