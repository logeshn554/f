"""Uncertainty quantification module including Wilson score CI and Block-Bootstrap CI."""
import math
import random
from typing import Dict, List, Optional, Tuple


def wilson_score_interval(wins: int, total: int, confidence: float = 0.95) -> Tuple[float, float]:
    """
    Compute Wilson score 95% confidence interval for a binomial win rate.
    Returns (lower_pct, upper_pct) bounded between 0 and 100.
    """
    if total <= 0:
        return (0.0, 0.0)

    p = wins / total
    # z for 95% two-sided confidence level is ~1.95996
    z = 1.95996 if math.isclose(confidence, 0.95) else 1.95996

    denom = 1.0 + (z * z) / total
    center = (p + (z * z) / (2.0 * total)) / denom
    margin = (z * math.sqrt((p * (1.0 - p) / total) + ((z * z) / (4.0 * total * total)))) / denom

    lower = max(0.0, (center - margin) * 100.0)
    upper = min(100.0, (center + margin) * 100.0)
    return (round(lower, 4), round(upper, 4))


def block_bootstrap_ci(
    trade_pnls: List[float],
    num_resamples: int = 1000,
    block_size: int = 5,
    confidence: float = 0.95,
    seed: int = 42,
) -> Dict[str, Optional[Tuple[float, float]]]:
    """
    Perform overlapping block bootstrapping on a sequence of trade P&Ls
    to compute confidence intervals robust to temporal dependency / auto-correlation.

    Returns dict with win_rate_ci_pct and net_pnl_ci.
    """
    n = len(trade_pnls)
    if n == 0:
        return {"win_rate_ci_pct": (0.0, 0.0), "net_pnl_ci": (0.0, 0.0)}

    rng = random.Random(seed)
    actual_block_size = max(1, min(block_size, n))
    num_blocks = math.ceil(n / actual_block_size)

    # Generate overlapping blocks
    blocks = [trade_pnls[i : i + actual_block_size] for i in range(n - actual_block_size + 1)]
    if not blocks:
        blocks = [trade_pnls]

    boot_win_rates = []
    boot_net_pnls = []

    for _ in range(num_resamples):
        resampled_trades = []
        for _ in range(num_blocks):
            resampled_trades.extend(rng.choice(blocks))
        resampled_trades = resampled_trades[:n]

        wins = sum(1 for pnl in resampled_trades if pnl > 0)
        win_rate = (wins / n) * 100.0
        net_pnl = sum(resampled_trades)

        boot_win_rates.append(win_rate)
        boot_net_pnls.append(net_pnl)

    boot_win_rates.sort()
    boot_net_pnls.sort()

    alpha = 1.0 - confidence
    lower_idx = int((alpha / 2.0) * num_resamples)
    upper_idx = int((1.0 - (alpha / 2.0)) * num_resamples) - 1

    lower_idx = max(0, min(lower_idx, num_resamples - 1))
    upper_idx = max(0, min(upper_idx, num_resamples - 1))

    return {
        "win_rate_ci_pct": (round(boot_win_rates[lower_idx], 4), round(boot_win_rates[upper_idx], 4)),
        "net_pnl_ci": (round(boot_net_pnls[lower_idx], 4), round(boot_net_pnls[upper_idx], 4)),
    }
