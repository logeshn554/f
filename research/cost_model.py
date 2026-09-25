"""
Realistic trading cost model with Delta Exchange fee structure and 2x stress testing.

contract_unit: ETH per lot (Delta ETHUSD = 0.01 ETH / lot).
max_notional:  Maximum fraction of equity that can be deployed per position (≤ 1.0).
"""
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR


def round_tick(price: float, tick_size: float, up: bool) -> float:
    """Round price to the nearest tick according to execution direction."""
    if tick_size <= 0:
        return price
    p_dec = Decimal(str(price))
    t_dec = Decimal(str(tick_size))
    units = (p_dec / t_dec).to_integral_value(
        rounding=ROUND_CEILING if up else ROUND_FLOOR
    )
    return float(units * t_dec)


@dataclass(frozen=True)
class CostModel:
    """
    Realistic trading cost parameters matching Delta Exchange public specs.

    Frictions modelled:
      - Taker commission (5 bps default)
      - 18% GST tax applied to exchange fees
      - Half bid-ask spread (2 bps default, applied each side)
      - Adverse slippage (2 bps default, applied each side)
      - Continuous funding reserve debit (3 bps / 8 h, applied both long & short)
      - Tick-size quantisation for entry and exit prices

    Integer lot contract model (Delta ETHUSD perpetual):
      - contract_unit = 0.01 ETH per lot
      - max_notional  = 1.0  (no leverage; position ≤ 100% of available cash)
    """

    taker_fee_rate: float = 0.0005           # 5 bps standard taker commission
    gst_rate: float = 0.18                    # 18% GST on exchange fees
    slippage_rate: float = 0.0002            # 2 bps adverse slippage per side
    spread_rate: float = 0.0002              # 2 bps half-spread per side
    funding_reserve_per_8h: float = 0.0003  # 3 bps continuous funding debit / 8 h
    tick_size: float = 0.01                  # Minimum price movement (USD)
    contract_unit: float = 0.01             # ETH per lot (Delta ETHUSD standard)
    max_notional: float = 1.0               # Max notional as fraction of available equity

    # ── Derived rates ─────────────────────────────────────────────────────────

    @property
    def total_taker_fee_rate(self) -> float:
        """Effective fee rate including GST: taker_fee_rate × (1 + gst_rate)."""
        return self.taker_fee_rate * (1.0 + self.gst_rate)

    # ── Price adjustments ────────────────────────────────────────────────────

    def calculate_entry_price(self, raw_price: float, side: int) -> float:
        """
        Entry price with half-spread + adverse slippage in direction of position,
        then quantised to tick_size.
        """
        friction = raw_price * (self.spread_rate / 2.0 + self.slippage_rate)
        slipped = raw_price + friction * side
        return round_tick(slipped, self.tick_size, up=(side == 1))

    def calculate_exit_price(self, raw_price: float, side: int) -> float:
        """
        Exit price with half-spread + adverse slippage against position direction,
        then quantised to tick_size.
        """
        friction = raw_price * (self.spread_rate / 2.0 + self.slippage_rate)
        slipped = raw_price - friction * side
        return round_tick(slipped, self.tick_size, up=(side == -1))

    # ── Cost calculations ─────────────────────────────────────────────────────

    def calculate_fee(self, notional: float) -> float:
        """Taker commission × (1 + GST) on the given notional value."""
        return notional * self.total_taker_fee_rate

    def calculate_funding_debit(self, notional: float, holding_seconds: float) -> float:
        """Conservative continuous funding debit for both long and short positions."""
        if holding_seconds <= 0:
            return 0.0
        return notional * self.funding_reserve_per_8h * (holding_seconds / 28800.0)

    # ── 2× cost stress model ──────────────────────────────────────────────────

    def create_2x_stress_model(self) -> "CostModel":
        """
        Double all variable cost components (fees, spread, slippage, funding).
        GST rate, tick size, contract unit, and max_notional are unchanged.
        """
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
