"""Realistic trading cost model with Delta Exchange fee structure and 2x stress testing."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import math


def round_tick(price: float, tick_size: float, up: bool) -> float:
    """Round price to the nearest tick size according to execution direction."""
    if tick_size <= 0:
        return price
    p_dec = Decimal(str(price))
    t_dec = Decimal(str(tick_size))
    units = (p_dec / t_dec).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR)
    return float(units * t_dec)


@dataclass(frozen=True)
class CostModel:
    """
    Realistic trading cost parameters matching Delta Exchange public specs.
    Frictions include taker fees, GST tax, spread, adverse slippage, and continuous funding debit.
    """
    taker_fee_rate: float = 0.0005      # 5 bps standard taker commission
    gst_rate: float = 0.18               # 18% GST on exchange fees
    slippage_rate: float = 0.0002        # 2 bps adverse slippage per side
    spread_rate: float = 0.0002          # 2 bps bid-ask spread
    funding_reserve_per_8h: float = 0.0003  # Conservative 3 bps continuous funding debit per 8h
    tick_size: float = 0.01              # Minimum price movement
    contract_unit: float = 1.0           # ETH per contract
    max_notional: float = 1.0            # No leverage (> 1.0 prohibited)

    @property
    def total_taker_fee_rate(self) -> float:
        """Effective fee rate including GST tax."""
        return self.taker_fee_rate * (1.0 + self.gst_rate)

    def calculate_entry_price(self, raw_price: float, side: int) -> float:
        """Calculate entry price including spread half-width, adverse slippage, and tick rounding."""
        half_spread = raw_price * (self.spread_rate / 2.0)
        slipped = raw_price + (half_spread + raw_price * self.slippage_rate) * side
        return round_tick(slipped, self.tick_size, up=(side == 1))

    def calculate_exit_price(self, raw_price: float, side: int) -> float:
        """Calculate exit price including spread half-width, adverse slippage, and tick rounding."""
        half_spread = raw_price * (self.spread_rate / 2.0)
        # Exiting LONG (side=1) means selling (adverse move down). Exiting SHORT means buying (adverse move up).
        slipped = raw_price - (half_spread + raw_price * self.slippage_rate) * side
        return round_tick(slipped, self.tick_size, up=(side == -1))

    def calculate_fee(self, notional: float) -> float:
        """Calculate commission fee for a given notional value, including GST."""
        return notional * self.total_taker_fee_rate

    def calculate_funding_debit(self, notional: float, holding_seconds: float) -> float:
        """Calculate continuous funding reserve debit for holding duration."""
        if holding_seconds <= 0:
            return 0.0
        return notional * self.funding_reserve_per_8h * (holding_seconds / 28800.0)

    def create_2x_stress_model(self) -> "CostModel":
        """Generate a 2x cost stress model with doubled fees, spread, slippage, and funding."""
        return CostModel(
            taker_fee_rate=self.taker_fee_rate * 2.0,
            gst_rate=self.gst_rate,
            slippage_rate=self.slippage_rate * 2.0,
            spread_rate=self.spread_rate * 2.0,
            funding_reserve_per_8h=self.funding_reserve_per_8h * 2.0,
            tick_size=self.tick_size,
            contract_unit=self.contract_unit,
            max_notional=self.max_notional,
        )
