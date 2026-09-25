"""
Local paper broker simulation engine.
Strictly key-free — never places orders.

Fixes applied (v2):
  - Integer lot sizing: Delta ETHUSD 1 lot = 0.01 ETH (contract_unit from CostModel).
  - Entry cash cap uses entry_price * (1 + total_fee_rate) to avoid going negative.
  - Gap stop execution: if the bar opens beyond the stop level, fill at the adverse open,
    not at the planned stop price.
  - max_notional enforced in position sizing.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from research.cost_model import CostModel, round_tick


class OrderExecutionProhibitedError(RuntimeError):
    """Raised if live order execution or API key credentials are attempted."""
    pass


class PaperBroker:
    """
    Local paper broker simulating execution under realistic exchange costs.
    Uses integer lot sizing (contract_unit from CostModel).
    """

    def __init__(
        self,
        db_path: str = ":memory:",
        initial_cash: float = 10000.0,
        cost_model: Optional[CostModel] = None,
        max_drawdown_limit: float = 0.20,
        max_holding_bars: int = 16,
    ):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.peak_equity = initial_cash
        self.cost_model = cost_model or CostModel()
        self.max_drawdown_limit = max_drawdown_limit
        self.max_holding_bars = max_holding_bars
        self.position: Optional[Dict[str, Any]] = None
        self.trades: List[Dict[str, Any]] = []
        self.halted = False
        self.halt_reason: Optional[str] = None
        self.db_path = str(db_path)

        self._verify_paper_only()

    # ── Safety ────────────────────────────────────────────────────────────────

    def _verify_paper_only(self) -> None:
        """Enforce strict research boundary: prohibit live credentials or order routes."""
        prohibited = ["api_key", "api_secret", "private_key", "order_url"]
        for attr in prohibited:
            if hasattr(self, attr):
                raise OrderExecutionProhibitedError(
                    f"Prohibited live trading attribute '{attr}' detected!"
                )

    def execute_live_order(self, *args: Any, **kwargs: Any) -> None:
        """Explicitly forbidden method to guarantee safety."""
        raise OrderExecutionProhibitedError(
            "CRITICAL: Real-money order execution is permanently prohibited in this engine."
        )

    # ── Mark-to-market equity ─────────────────────────────────────────────────

    def equity(self, current_close: float) -> float:
        """Mark-to-market equity: cash + unrealised P&L less estimated exit costs."""
        if not self.position:
            return self.cash
        p = self.position
        side = p["side"]
        exit_px = self.cost_model.calculate_exit_price(current_close, side)
        gross_pnl = p["qty"] * (exit_px - p["entry_price"]) * side
        exit_fee = self.cost_model.calculate_fee(p["qty"] * exit_px)
        return self.cash + (p["qty"] * p["entry_price"]) + gross_pnl - exit_fee - p["funding_debit"]

    # ── Position close ────────────────────────────────────────────────────────

    def close_position(
        self, current_candle: Dict[str, Any], exit_price: float, reason: str
    ) -> None:
        """Close open position, record all costs, update cash ledger."""
        p = self.position
        if not p:
            return

        side = p["side"]
        actual_exit = self.cost_model.calculate_exit_price(exit_price, side)
        gross_pnl = p["qty"] * (actual_exit - p["entry_price"]) * side
        exit_fee = self.cost_model.calculate_fee(p["qty"] * actual_exit)

        # Funding: use numeric timestamps when available, else bars_held * bar_seconds
        cur_t = current_candle.get("time", 0)
        entry_t = p.get("entry_time", 0)
        if isinstance(cur_t, (int, float)) and isinstance(entry_t, (int, float)):
            holding_sec = max(0.0, float(cur_t) - float(entry_t))
        else:
            holding_sec = float(p.get("bars_held", 1)) * 86400.0

        funding = self.cost_model.calculate_funding_debit(
            p["qty"] * actual_exit, holding_sec
        )

        net_pnl = gross_pnl - p["entry_fee"] - exit_fee - funding
        self.cash += (p["qty"] * p["entry_price"]) + gross_pnl - exit_fee - funding

        self.trades.append({
            "entry_time": p["entry_time"],
            "exit_time": current_candle.get("time", current_candle.get("date")),
            "side": side,
            "contracts": p["contracts"],
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
        })
        self.position = None

    # ── Per-bar simulation step ────────────────────────────────────────────────

    def step(self, candle: Dict[str, Any], signal: Dict[str, Any]) -> None:
        """
        Advance the broker one bar forward.

        Signal is assumed to have been generated from candles BEFORE this bar
        opened (causality is enforced in walk_forward.py).  Execution uses this
        bar's OPEN for entry; HIGH/LOW are used only for stop/target detection.
        """
        o = candle["open"]
        h = candle["high"]
        l = candle["low"]
        c = candle["close"]
        time_id = candle.get("time", candle.get("date"))

        # ── Drawdown breaker ──────────────────────────────────────────────────
        current_eq = self.equity(c)
        if current_eq > self.peak_equity:
            self.peak_equity = current_eq
        if self.peak_equity > 0:
            dd = (self.peak_equity - current_eq) / self.peak_equity
            if dd >= self.max_drawdown_limit:
                self.halted = True
                self.halt_reason = f"Max drawdown limit reached ({dd*100:.1f}%)"

        # ── Manage open position exits ────────────────────────────────────────
        if self.position:
            p = self.position
            p["bars_held"] = p.get("bars_held", 0) + 1
            side = p["side"]
            stop = p["stop_price"]
            target = p["target_price"]

            if self.halted:
                # Emergency close at open (adverse gap already reflected in open price)
                self.close_position(candle, o, f"HALT: {self.halt_reason}")

            else:
                # GAP STOP: bar opens beyond stop → fill at the adverse open price
                # (not at the planned stop level, which was never touched)
                gap_stop_long = (side == 1 and o <= stop)
                gap_stop_short = (side == -1 and o >= stop)

                if gap_stop_long or gap_stop_short:
                    self.close_position(candle, o, "stop_gap_open")

                elif self.position:
                    # Normal intrabar: check low/high (adverse extreme before favourable)
                    hit_stop = (l <= stop) if side == 1 else (h >= stop)
                    hit_target = (h >= target) if side == 1 else (l <= target)

                    if hit_stop and hit_target:
                        # Both barriers hit in same bar: assume stop first (conservative)
                        self.close_position(candle, stop, "stop_loss")
                    elif hit_stop:
                        self.close_position(candle, stop, "stop_loss")
                    elif hit_target:
                        self.close_position(candle, target, "take_profit")
                    elif p["bars_held"] >= self.max_holding_bars:
                        self.close_position(candle, c, "time_exit")

        # ── Open new position (signal from previous bar close) ────────────────
        if (
            not self.position
            and not self.halted
            and signal.get("side", 0) != 0
        ):
            side = signal["side"]

            # Entry at this bar's OPEN with adverse slippage + spread
            entry_price = self.cost_model.calculate_entry_price(o, side)

            stop_dist = signal.get("stop_distance", 2.0 * signal.get("atr", 10.0))
            target_dist = signal.get("target_distance", 3.0 * signal.get("atr", 15.0))

            stop_price = round_tick(
                entry_price - side * stop_dist,
                self.cost_model.tick_size,
                up=(side == -1),
            )
            target_price = round_tick(
                entry_price + side * target_dist,
                self.cost_model.tick_size,
                up=(side == 1),
            )

            if stop_price <= 0 or target_price <= 0 or entry_price <= 0:
                return

            # ── INTEGER LOT SIZING ────────────────────────────────────────────
            # Delta ETHUSD: 1 lot = contract_unit ETH (default 0.01 ETH).
            # Risk: 0.5% of available cash per trade.
            # Cap at max_notional fraction of equity and available liquidity.
            cm = self.cost_model
            per_lot_dist = abs(entry_price - stop_price) * cm.contract_unit
            per_lot_friction = (
                entry_price * cm.contract_unit
                * (2 * cm.total_taker_fee_rate + 2 * cm.slippage_rate + cm.funding_reserve_per_8h)
            )
            per_lot_cost_to_open = (
                entry_price * cm.contract_unit * (1 + cm.total_taker_fee_rate)
            )

            # Available cash with a conservative buffer for the entry commission
            available = self.cash

            risk_budget = available * 0.005  # 0.5% equity risk
            if per_lot_dist + per_lot_friction > 0:
                lots_by_risk = risk_budget / (per_lot_dist + per_lot_friction)
            else:
                lots_by_risk = 0.0

            # Notional cap: at most max_notional * available
            if per_lot_cost_to_open > 0:
                lots_by_notional = (available * cm.max_notional) / per_lot_cost_to_open
            else:
                lots_by_notional = 0.0

            contracts = math.floor(min(lots_by_risk, lots_by_notional))
            if contracts < 1:
                return

            qty = contracts * cm.contract_unit  # ETH quantity
            entry_cost = qty * entry_price
            entry_fee = cm.calculate_fee(entry_cost)
            total_outlay = entry_cost + entry_fee

            # Final cash-adequacy check
            if total_outlay > available or total_outlay <= 0:
                return

            self.cash -= total_outlay

            self.position = {
                "entry_time": time_id,
                "side": side,
                "contracts": contracts,
                "qty": qty,
                "entry_price": entry_price,
                "stop_price": stop_price,
                "target_price": target_price,
                "entry_fee": entry_fee,
                "funding_debit": 0.0,
                "bars_held": 0,
            }
