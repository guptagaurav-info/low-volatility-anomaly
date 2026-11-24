"""Daily total-return panel for US operating companies from the defeatbeta Yahoo Finance mirror."""
import numpy as np
import pandas as pd

D = "data/"


def panel():
    """Return (ret, dollar_volume, close, industry) as date x symbol frames.

    Total return = (close_t + dividend_t) / close_{t-1} - 1, using the mirror's split-adjusted close
    and cash dividends on their ex-dates. Daily moves above +100% or below -90% are treated as bad prints.
    """
    p = pd.read_parquet(D + "daily.parquet")
    p["d"] = pd.to_datetime(p["d"])
    close = p.pivot_table(index="d", columns="symbol", values="close").sort_index()
    # market holidays on which only a few over-the-counter names print are not trading days: drop them
    n = close.notna().sum(axis=1); med = n.rolling(21, center=True, min_periods=5).median()
    close = close[n >= 0.5 * med]
    vol = p.pivot_table(index="d", columns="symbol", values="volume").reindex_like(close)
    dv = (close * vol).astype("float32")
    dv_ = pd.read_parquet(D + "divs.parquet"); dv_["d"] = pd.to_datetime(dv_["d"])
    div = dv_.pivot_table(index="d", columns="symbol", values="amount", aggfunc="sum").reindex(index=close.index, columns=close.columns).fillna(0.0)
    ret = (close + div) / close.shift(1) - 1
    ret = ret.mask((ret > 1.0) | (ret < -0.9))
    ind = pd.read_parquet(D + "universe.parquet").set_index("symbol")["industry"]
    return ret.astype("float32"), dv, close.astype("float32"), ind


def spy_returns(index):
    s = pd.read_parquet(D + "spy.parquet"); s["d"] = pd.to_datetime(s["d"])
    c = s.set_index("d")["close"].sort_index()
    v = pd.read_parquet(D + "spy_divs.parquet"); v["d"] = pd.to_datetime(v["d"])
    div = v.groupby("d")["amount"].sum().reindex(c.index).fillna(0.0)
    return ((c + div) / c.shift(1) - 1).reindex(index)
