import numpy as np
import pandas as pd
from lva import core


def test_groups_lowest_score_is_group_one():
    s = pd.Series(np.arange(10.0), index=list("abcdefghij"))
    g = core.groups(s, 5)
    assert g["a"] == 1 and g["j"] == 5


def test_sector_neutral_ranks_within_sector():
    s = pd.Series([1.0, 2, 3, 4, 5, 10, 20, 30, 40, 50], index=list("abcdefghij"))
    sec = pd.Series(["X"] * 5 + ["Y"] * 5, index=s.index)
    g = core.groups(s, 5, sec)
    assert g["a"] == 1 and g["f"] == 1 and g["e"] == 5 and g["j"] == 5


def test_signals_beta_of_market_is_one():
    rng = np.random.default_rng(0); m = pd.Series(rng.normal(0, 0.01, 300))
    w = pd.DataFrame({"x": m, "y": 2 * m})
    vol, beta = core.signals(w, m)
    assert abs(beta["x"] - 1) < 1e-9 and abs(beta["y"] - 2) < 1e-9 and vol["y"] > vol["x"]


def test_hold_return_uses_only_future_days():
    idx = pd.date_range("2020-01-01", periods=4)
    ret = pd.DataFrame({"a": [0.5, 0.1, 0.1, 9.9]}, index=idx)
    r, _ = core.hold_return(ret, 0, 2, ["a"])
    assert abs(r - 0.21) < 1e-12


def test_eligible_ignores_data_after_signal_date():
    idx = pd.date_range("2020-01-01", periods=300)
    rng = np.random.default_rng(1)
    ret = pd.DataFrame(rng.normal(0, 0.01, (300, 3)), index=idx, columns=list("abc"))
    close = pd.DataFrame(10.0, index=idx, columns=ret.columns); dv = pd.DataFrame(1.0, index=idx, columns=ret.columns)
    cfg = {"lookback_days": 252, "min_obs": 200, "max_zero_days": 0.1, "min_price": 5, "universe_top": 2}
    a = set(core.eligible(ret, dv, close, 260, cfg)); dv2 = dv.copy(); dv2.iloc[261:, 2] = 1e9
    assert a == set(core.eligible(ret, dv2, close, 260, cfg))
