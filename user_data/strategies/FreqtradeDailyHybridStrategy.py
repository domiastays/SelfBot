"""
FreqtradeDailyHybridStrategy
============================

Daily (1d) long-only trend-following strategy for SelfBot.

Logic
-----
Entry (all must be true):
  * Market-health gate: close above the slow SMA (default 100 days)
  * Trend: fast EMA above slow EMA
  * Trigger: fast EMA crosses above slow EMA, OR price reclaims the fast EMA
    while the trend is already up
  * Not overbought: RSI below `rsi_buy_max`
  * Optional Claude gate (live / dry-run only, see selfbot/claude_gate.py)

Exit (any):
  * Fast EMA crosses below slow EMA (trend over)
  * RSI above `rsi_sell_min` AND close drops back under the fast EMA
    (momentum fading after an overbought run)
  * ATR trailing stop (custom_stoploss), capped by the hard `stoploss`

Every tunable value is a hyperopt parameter, so the tuning order from
docs/tuning.md (EMA -> RSI -> ATR -> ROI -> exposure) can be run with
`freqtrade hyperopt --spaces buy sell` once the baseline backtest is done.
Indicators are computed with pandas only (no TA-Lib dependency).
"""

from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.strategy import (
    DecimalParameter,
    IStrategy,
    IntParameter,
    stoploss_from_absolute,
)

try:  # Claude gate is optional; the strategy must work without it.
    from selfbot.claude_gate import ClaudeGate
except Exception:  # pragma: no cover - import path depends on how bot is launched
    ClaudeGate = None  # type: ignore


# ---------------------------------------------------------------- indicators
def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(100)


def atr(df: DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def crossed_above(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a > b) & (a.shift(1) <= b.shift(1))


def crossed_below(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a < b) & (a.shift(1) >= b.shift(1))


# ------------------------------------------------------------------ strategy
class FreqtradeDailyHybridStrategy(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    can_short = False
    process_only_new_candles = True
    startup_candle_count = 200  # slow SMA + EMA warm-up

    # Hard floor. The ATR stop below normally sits tighter than this.
    stoploss = -0.10
    use_custom_stoploss = True
    trailing_stop = False  # the ATR stop already trails upward

    # Trend-follower: let winners run, ROI only trims very large / stale trades.
    # (Minutes. 43200 = 30 days.)
    minimal_roi = {"0": 0.40, "43200": 0.15}

    use_exit_signal = True
    exit_profit_only = False

    # ---- hyperopt-able parameters (defaults = agreed starting point)
    ema_short = IntParameter(5, 15, default=9, space="buy", optimize=True)
    ema_long = IntParameter(20, 50, default=21, space="buy", optimize=True)
    rsi_buy_max = IntParameter(50, 70, default=65, space="buy", optimize=True)
    trend_sma = IntParameter(50, 200, default=100, space="buy", optimize=False)

    rsi_sell_min = IntParameter(55, 75, default=70, space="sell", optimize=True)
    atr_multiplier = DecimalParameter(2.0, 4.0, default=3.0, decimals=1, space="sell", optimize=True)

    # ---- risk protections (stop trading after bad streaks / drawdown)
    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 1},
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 10,
                "trade_limit": 2,
                "stop_duration_candles": 5,
                "only_per_pair": False,
            },
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 30,
                "trade_limit": 3,
                "stop_duration_candles": 10,
                "max_allowed_drawdown": 0.20,
            },
        ]

    def bot_start(self, **kwargs) -> None:
        self.claude_gate = ClaudeGate.from_env() if ClaudeGate else None

    # ------------------------------------------------------------ indicators
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Compute every EMA length in the hyperopt range once, so hyperopt is fast.
        for p in set(range(5, 16)) | set(range(20, 51)):
            dataframe[f"ema_{p}"] = ema(dataframe["close"], p)
        dataframe["sma_trend"] = dataframe["close"].rolling(self.trend_sma.value).mean()
        dataframe["rsi"] = rsi(dataframe["close"], 14)
        dataframe["atr"] = atr(dataframe, 14)
        return dataframe

    # ----------------------------------------------------------------- entry
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        fast = dataframe[f"ema_{self.ema_short.value}"]
        slow = dataframe[f"ema_{self.ema_long.value}"]

        healthy = dataframe["close"] > dataframe["sma_trend"]
        uptrend = fast > slow
        trigger = crossed_above(fast, slow) | (uptrend & crossed_above(dataframe["close"], fast))
        not_overbought = dataframe["rsi"] < self.rsi_buy_max.value

        dataframe.loc[
            healthy & uptrend & trigger & not_overbought & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "ema_trend")
        return dataframe

    # ------------------------------------------------------------------ exit
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        fast = dataframe[f"ema_{self.ema_short.value}"]
        slow = dataframe[f"ema_{self.ema_long.value}"]

        trend_over = crossed_below(fast, slow)
        fading = (dataframe["rsi"].shift(1) > self.rsi_sell_min.value) & (dataframe["close"] < fast)

        dataframe.loc[trend_over, ["exit_long", "exit_tag"]] = (1, "ema_cross_down")
        dataframe.loc[fading & ~trend_over, ["exit_long", "exit_tag"]] = (1, "rsi_fade")
        return dataframe

    # ------------------------------------------------------ ATR trailing stop
    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        after_fill: bool,
        **kwargs,
    ) -> Optional[float]:
        df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if df is None or df.empty:
            return None
        last = df.iloc[-1]
        stop_price = last["close"] - self.atr_multiplier.value * last["atr"]
        # Freqtrade only ever moves the stop up, so this trails winners.
        return stoploss_from_absolute(stop_price, current_rate, is_short=trade.is_short)

    # ------------------------------------------------------------ Claude gate
    def confirm_trade_entry(
        self,
        pair: str,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        current_time: datetime,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> bool:
        gate = getattr(self, "claude_gate", None)
        # Never call Claude during backtest/hyperopt: keeps tests fast, free and reproducible.
        if gate is None or self.dp.runmode.value not in ("dry_run", "live"):
            return True
        df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        snapshot = df.tail(30)[["date", "open", "high", "low", "close", "volume", "rsi", "atr", "sma_trend",
                                f"ema_{self.ema_short.value}", f"ema_{self.ema_long.value}"]]
        return gate.review_entry(pair=pair, rate=rate, entry_tag=entry_tag, snapshot=snapshot)
