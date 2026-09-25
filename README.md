# Ethereum mathematical research tool

**Active model: [Candle Paths v4](CANDLE_PATHS.md)** — custom candle geometry and historical scenario analysis, BUY/SELL/WAIT, dynamic take-profit/stop-loss, and the live $100 paper dashboard. No profitable edge or 90% win rate has been established.

**Live $100 dashboard:** see [GUARD_GUIDE.md](GUARD_GUIDE.md) and run `start_guard.ps1`. ETH Guard v3 adds hourly trend confirmation, dynamic volatility exits, a persistent forward paper account, and visual research results. The measured strategy has not established profitability.

For the new Delta Exchange connection and 15-minute long/short paper broker, see [DELTA_PAPER.md](DELTA_PAPER.md). The original daily research tool below remains separate.

Python standard library only. No API key, LLM, packages, or exchange account. No order execution.

Run with Python 3.10+ from this folder:

```powershell
python eth_quant.py --output eth_report.json
python eth_quant.py --csv your_eth_daily.csv --fee-bps 10 --slippage-bps 5
python -m unittest discover -s . -p "test_*.py"
```

The default downloads up to 299 completed UTC daily ETH-USD candles from Coinbase's public endpoint. It saves the input candles beside the report for reproducibility. Offline CSV columns: `date,open,high,low,close`; ISO dates ascending, one row per daily candle, at least 240 rows. Use consistent prices from a single market.

## Fixed strategy

At a completed daily close, require price above the rising 100-day simple moving average, below the 20-day average, 14-day simple RSI between 30 and 48, and 14-day average true range below 8% of price. This tests buying a moderate pullback within an upward trend. RSI uses simple sums, not Wilder smoothing.

Enter at the next open with adverse slippage. Size to approximately 0.5% of equity risk, capped at available cash with no leverage. Stop is two ATR below entry; target is three ATR above entry. Exit after ten bars or at the period end. If both stop and target appear in a candle, assume the stop occurs first. Adverse gaps fill at the open; costs apply to both sides. Gap losses may exceed planned risk.

After indicator warmup, the first 60% is the development period and the final 40% is the holdout. Each starts independently with $10,000; no parameters are selected or optimized from either segment. A buy-and-hold comparison uses the same costs. Win rate counts trades profitable after costs. The Wilson interval illustrates uncertainty, although trades can be dependent. Daily close drawdown can miss intraday losses.

## Interpreting results

90% win rate is a requested target, not a feature or a guarantee. A high win rate can still lose money when losing trades are larger. Evaluate net return, drawdown, trade count, profit factor, and results across longer unseen periods. A few trades cannot establish reliability. A WAIT signal means entry conditions are absent. The latest signal is a research candidate, not proof of profitable execution.

This short single-market history does not establish a durable edge. Fees are illustrative: supply your actual venue/tier costs. Taxes, liquidity impact, and outages are excluded. No synthetic results are presented as market evidence.

Public data documentation: https://docs.cdp.coinbase.com/exchange/reference/exchangerestapi_getproductcandles
Investment tool limitations: https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-alerts/investor-56
"# f" 
