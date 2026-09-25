# Delta ETH paper trading

This is a local USD paper broker connected to **Delta Exchange India public ETHUSD data** by default. No keys, LLM, dependencies, exchange login, account connection, or real orders. It is not the Delta demo-account trading service. India and Global can be selected explicitly; only India connectivity was verified.

## Run on this Windows machine

From the workspace root:

```powershell
# One check (safe default)
.\trading\run_delta_paper.ps1

# Run in this terminal for about one hour; Ctrl+C stops it
.\trading\run_delta_paper.ps1 -Cycles 240 -Interval 15

# Inspect last recorded health (check its timestamp)
.\trading\run_delta_paper.ps1 -Mode status

# Download candles and run the historical replay
.\trading\run_delta_paper.ps1 -Mode replay
```

The launcher finds Python on PATH or the bundled runtime used during verification. No installation is required on this machine. The launcher's data directory is `trading/delta_run_india` (or `_global`); direct Python defaults to `trading/delta_run`. Do not confuse separate virtual accounts. The completed three-cycle verification is in `delta_run`.

With any Python 3.10+ installation:

```powershell
python trading/delta_paper.py paper --cycles 240 --interval 15
python trading/delta_paper.py status
python trading/delta_paper.py replay --input trading/delta_run/snapshot.json --directory trading/delta_replay
python -m unittest discover -s trading -p "test_*.py"
```

## Algorithm

Fixed mathematical trend breakout on completed **15-minute ETHUSD perpetual candles**, both long and short. Uses a fixed 100-bar window for repeatable EMA20/EMA60, simple RSI14, ATR14, and 20-bar efficiency ratio. Long: close breaks the previous 12 highs, EMA20 above rising EMA60, RSI 52–78. Short: mirrored breakdown with RSI 22–48. Require efficiency >= 0.25 and ATR/price 0.1%–3%. No fitting, LLM, martingale, or averaging down.

Evaluate each completed candle once. Only enter within 120 seconds after its close; late startup skips the old entry. A wide spread consumes that signal rather than retrying a stale entry. Maximum one position, 0.25% intended risk per trade including friction, no more than 1x notional. Integer contracts and tick sizes come from current public product metadata. Stop 2 ATR, target 4 ATR, timeout 4 hours, and 15-minute cooldown after exit.

## Paper execution and controls

- Fill buys at ask plus 2bp slippage; sells at bid minus 2bp, adversely rounded to tick size. Entry size capped to displayed best-level contracts. Exit liquidity is assumed; actual market depth is not modeled.
- Apply current public taker commission to both sides. The checked product was 0.01 ETH/contract, $0.05 tick, 5bp taker commission. These are read from the API, not assumed constants.
- Charge a conservative **3bp per 8 hours continuous funding reserve** for either direction. This is a research cost assumption, not actual Delta funding settlement. Real funding may be higher or lower.
- Reject ticker age over 30 seconds, clocks more than 5 seconds ahead, stale/gapped/duplicate candles, nonfinite prices, crossed quotes, and nonoperational contracts.
- 2% daily loss gate resets on the next observed UTC day. A 5% observed drawdown or a STOP file creates a persistent halt. Gaps can exceed all thresholds.
- SQLite WAL with full synchronization: state and fill journal commit in one transaction. Repeated/out-of-order quotes do not duplicate fills. Restart preserves positions and halts. Changed configuration/product metadata requires a separate database.
- Three bounded HTTP attempts for transient errors; after three failed polling cycles the runner exits with code 2. Failed snapshots make no fills. Saved last-known equity can be stale while blocked.

To request a stop, create an empty file named `STOP` in the session's data directory. At the next valid quote the virtual position is closed and the session is persistently halted. If public data is unavailable, the runner stops and retains the virtual position; it does not fabricate a close. Removing STOP does not clear a persisted halt—start a separate paper database for a new session. Ctrl+C also preserves the virtual position for a later restart.

## Files and evidence

- `health.json`: latest connectivity, signal, equity, position, and timestamp.
- `run.jsonl`: append-only polling log.
- `paper.sqlite3`: atomic state plus ENTRY/EXIT events (local simulation only).
- `snapshot.json`: raw public input with fetch time and source.
- `delta_replay/replay.json`: separate development and holdout replay results.

Verification on 2026-09-25: three successful live public-data polls, fresh numeric timestamps, WAIT signal, $10,000 paper equity, **zero forward trades**. The ticker's text `time` field differed from its microsecond `timestamp`; freshness uses the latter.

Replay on ~15 days of Delta data: development 18 trades, 27.78% wins, -1.06%; holdout 6 trades, 50% wins, -0.07%, 0.85% observed drawdown. These are historical simulated results, not forward paper returns. The strategy did **not** demonstrate a profitable edge. The 90% target is not achieved.

## Readiness limits

The connector and paper execution paths have been exercised. This is **not certified or validated for production capital**: only a short live smoke test and small replay have run. No background process is left running by the verification. Long-duration forward paper performance remains unmeasured.

Polling can miss price excursions between quotes, including during downtime. Stops execute only at observed quotes. Replay instead assumes adverse-extreme-first intrabar paths, so replay and forward fills will differ. Replay assumes a 2bp spread and unlimited displayed size because historical quotes are unavailable. Chronological 60/40 periods start separately with $10,000 after warmup. INR conversion, taxes, exact funding settlements, slippage depth, liquidation, and exchange-account reconciliation are not modeled. The runner refetches a full 1500-candle window each cycle; this is simple polling, not a low-latency system.

Public routes are allowlisted in the connector, which only makes GET requests. There is no live-order path to enable.

API reference: [Delta Exchange documentation](https://docs.delta.exchange/).
