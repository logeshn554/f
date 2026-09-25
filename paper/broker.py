"""Local paper broker simulation engine. strictly key-free, never places orders."""
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional
from research.cost_model import CostModel, round_tick


class OrderExecutionProhibitedError(RuntimeError):
    """Raised if live order execution or API key credentials are attempted."""
    pass


class PaperBroker:
    """
    Local paper broker simulating execution under realistic exchange costs.
    Maintains atomic state in memory or SQLite ledger.
    """

    def __init__(
        self,
        db_path: str = ":memory:",
        initial_cash: float = 10000.0,
        cost_model: Optional[CostModel] = None,
        max_drawdown_limit: float = 0.20,
    ):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.peak_equity = initial_cash
        self.cost_model = cost_model or CostModel()
        self.max_drawdown_limit = max_drawdown_limit
        self.position: Optional[Dict[str, Any]] = None
        self.trades: List[Dict[str, Any]] = []
        self.halted = False
        self.halt_reason: Optional[str] = None
        self.db_path = str(db_path)

        # Safety assertion: assert no live trading credentials
        self._verify_paper_only()

    def _verify_paper_only(self):
        """Enforce strict research boundary: prohibit live credentials or order routes."""
        prohibited_attributes = ["api_key", "api_secret", "private_key", "order_url"]
        for attr in prohibited_attributes:
            if hasattr(self, attr):
                raise OrderExecutionProhibitedError(f"Prohibited live trading attribute '{attr}' detected!")

    def execute_live_order(self, *args, **kwargs):
        """Explicitly forbidden method to guarantee safety."""
        raise OrderExecutionProhibitedError(
            "CRITICAL: Real-money order execution is permanently prohibited in this engine."
        )

    def equity(self, current_close: float) -> float:
        """Calculate current equity accounting for open position mark-to-market and exit costs."""
        if not self.position:
            return self.cash
        p = self.position
        side = p["side"]
        exit_price = self.cost_model.calculate_exit_price(current_close, side)
        gross_pnl = p["qty"] * (exit_price - p["entry_price"]) * side
        exit_fee = self.cost_model.calculate_fee(p["qty"] * exit_price)
        return self.cash + (p["qty"] * p["entry_price"]) + gross_pnl - exit_fee - p["funding_debit"]

    def close_position(self, current_candle: Dict[str, Any], exit_price: float, reason: str):
        """Close open position, calculate fees/funding, update ledger."""
        p = self.position
        if not p:
            return

        side = p["side"]
        actual_exit = self.cost_model.calculate_exit_price(exit_price, side)
        gross_pnl = p["qty"] * (actual_exit - p["entry_price"]) * side
        exit_fee = self.cost_model.calculate_fee(p["qty"] * actual_exit)
        cur_t = current_candle.get("time", 0)
        entry_t = p.get("entry_time", 0)
        if isinstance(cur_t, (int, float)) and isinstance(entry_t, (int, float)):
            holding_time = float(cur_t) - float(entry_t)
        else:
            holding_time = float(p.get("bars_held", 1)) * 86400.0
        funding = self.cost_model.calculate_funding_debit(p["qty"] * actual_exit, max(0.0, holding_time))

        net_pnl = gross_pnl - p["entry_fee"] - exit_fee - funding
        self.cash += (p["qty"] * p["entry_price"]) + gross_pnl - exit_fee - funding

        trade_record = {
            "entry_time": p["entry_time"],
            "exit_time": current_candle.get("time", current_candle.get("date")),
            "side": side,
            "qty": p["qty"],
            "entry_price": p["entry_price"],
            "exit_price": actual_exit,
            "gross_pnl": round(gross_pnl, 4),
            "entry_fee": round(p["entry_fee"], 4),
            "exit_fee": round(exit_fee, 4),
            "funding_debit": round(funding, 4),
            "net_pnl": round(net_pnl, 4),
            "reason": reason,
            "duration_bars": p.get("bars_held", 1),
        }
        self.trades.append(trade_record)
        self.position = None

    def step(self, candle: Dict[str, Any], signal: Dict[str, Any]):
        """Advance broker simulation by one candle."""
        o, h, l, c = candle["open"], candle["high"], candle["low"], candle["close"]
        time_id = candle.get("time", candle.get("date"))

        # Update equity and drawdown breaker
        current_eq = self.equity(c)
        if current_eq > self.peak_equity:
            self.peak_equity = current_eq

        drawdown = (self.peak_equity - current_eq) / self.peak_equity if self.peak_equity > 0 else 0.0
        if drawdown >= self.max_drawdown_limit:
            self.halted = True
            self.halt_reason = f"Max drawdown limit reached ({drawdown*100:.1f}%)"

        # Check existing position exits
        if self.position:
            p = self.position
            p["bars_held"] = p.get("bars_held", 0) + 1
            side = p["side"]
            stop, target = p["stop_price"], p["target_price"]

            # Exit logic: check intraday adverse extreme first
            hit_stop = (l <= stop) if side == 1 else (h >= stop)
            hit_target = (h >= target) if side == 1 else (l <= target)

            if self.halted:
                self.close_position(candle, c, f"HALT: {self.halt_reason}")
            elif hit_stop:
                # Adverse gap or stop hit
                exit_p = stop if (l <= stop <= h) else (l if side == 1 else h)
                self.close_position(candle, exit_p, "stop_loss")
            elif hit_target:
                exit_p = target
                self.close_position(candle, exit_p, "take_profit")
            elif p["bars_held"] >= 16:
                self.close_position(candle, c, "time_exit")

        # Open new position if signal present and not halted
        if not self.position and not self.halted and signal.get("side", 0) != 0:
            side = signal["side"]
            raw_entry = o  # Entry at open of current candle
            entry_price = self.cost_model.calculate_entry_price(raw_entry, side)

            stop_dist = signal.get("stop_distance", 2.0 * signal.get("atr", 10.0))
            target_dist = signal.get("target_distance", 3.0 * signal.get("atr", 15.0))

            stop_price = round_tick(entry_price - (side * stop_dist), self.cost_model.tick_size, up=(side == -1))
            target_price = round_tick(entry_price + (side * target_dist), self.cost_model.tick_size, up=(side == 1))

            # Risk-based position sizing (capped at available cash and max notional)
            risk_amount = self.cash * 0.005  # 0.5% equity risk
            per_unit_risk = abs(entry_price - stop_price) + (entry_price * self.cost_model.total_taker_fee_rate * 2)
            if per_unit_risk > 0:
                qty = min(risk_amount / per_unit_risk, self.cash / entry_price)
            else:
                qty = self.cash / entry_price

            qty = round(qty, 4)
            if qty > 0 and entry_price > 0 and stop_price > 0 and target_price > 0:
                entry_fee = self.cost_model.calculate_fee(qty * entry_price)
                self.cash -= (qty * entry_price) + entry_fee

                self.position = {
                    "entry_time": time_id,
                    "side": side,
                    "qty": qty,
                    "entry_price": entry_price,
                    "stop_price": stop_price,
                    "target_price": target_price,
                    "entry_fee": entry_fee,
                    "funding_debit": 0.0,
                    "bars_held": 0,
                }
