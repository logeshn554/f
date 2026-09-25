"""Metrics module for detailed trade performance calculation and reporting."""
import math
from typing import Any, Dict, List, Optional
from research.uncertainty import wilson_score_interval, block_bootstrap_ci


def calculate_metrics(
    trades: List[Dict[str, Any]],
    initial_cash: float = 10000.0,
    ending_cash: Optional[float] = None,
    total_bars: int = 1,
) -> Dict[str, Any]:
    """Calculate comprehensive performance metrics from closed trade logs."""
    n_trades = len(trades)

    if n_trades == 0:
        return {
            "closed_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_pct": None,
            "win_rate_95_ci": None,
            "block_bootstrap_95_ci": None,
            "net_return_pct": 0.0,
            "net_pnl": 0.0,
            "profit_factor": None,
            "max_drawdown_pct": 0.0,
            "mean_trade_pnl": None,
            "long_short": {"long_trades": 0, "long_wins": 0, "short_trades": 0, "short_wins": 0},
            "exposure_pct": 0.0,
            "turnover": 0.0,
        }

    pnls = [float(t["net_pnl"]) for t in trades]
    wins = sum(1 for pnl in pnls if pnl > 0)
    losses = sum(1 for pnl in pnls if pnl < 0)

    win_rate_pct = (wins / n_trades) * 100.0
    wilson_ci = wilson_score_interval(wins, n_trades)
    boot_ci = block_bootstrap_ci(pnls)

    gross_profit = sum(pnl for pnl in pnls if pnl > 0)
    gross_loss = sum(abs(pnl) for pnl in pnls if pnl < 0)

    if gross_loss > 0:
        profit_factor = round(gross_profit / gross_loss, 4)
    else:
        profit_factor = round(gross_profit, 4) if gross_profit > 0 else None

    total_net_pnl = sum(pnls)
    final_cash = ending_cash if ending_cash is not None else (initial_cash + total_net_pnl)
    net_return_pct = ((final_cash / initial_cash) - 1.0) * 100.0

    # Calculate equity curve peak and drawdown
    equity = initial_cash
    peak = initial_cash
    max_dd = 0.0

    for pnl in pnls:
        equity += pnl
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    long_trades = sum(1 for t in trades if t.get("side", 1) == 1)
    long_wins = sum(1 for t in trades if t.get("side", 1) == 1 and t["net_pnl"] > 0)
    short_trades = sum(1 for t in trades if t.get("side", 1) == -1)
    short_wins = sum(1 for t in trades if t.get("side", 1) == -1 and t["net_pnl"] > 0)

    total_bars_in_trades = sum(t.get("duration_bars", 1) for t in trades)
    exposure_pct = (total_bars_in_trades / max(1, total_bars)) * 100.0
    total_notional_traded = sum(t.get("qty", 1.0) * t.get("entry_price", 1.0) for t in trades)
    turnover = total_notional_traded / initial_cash

    return {
        "closed_trades": n_trades,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(win_rate_pct, 4),
        "win_rate_95_ci": list(wilson_ci),
        "block_bootstrap_95_ci": {
            "win_rate_pct": list(boot_ci["win_rate_ci_pct"]) if boot_ci["win_rate_ci_pct"] else None,
            "net_pnl": list(boot_ci["net_pnl_ci"]) if boot_ci["net_pnl_ci"] else None,
        },
        "net_return_pct": round(net_return_pct, 4),
        "net_pnl": round(total_net_pnl, 4),
        "profit_factor": profit_factor,
        "max_drawdown_pct": round(max_dd * 100.0, 4),
        "mean_trade_pnl": round(total_net_pnl / n_trades, 4),
        "long_short": {
            "long_trades": long_trades,
            "long_wins": long_wins,
            "short_trades": short_trades,
            "short_wins": short_wins,
        },
        "exposure_pct": round(exposure_pct, 4),
        "turnover": round(turnover, 4),
    }
