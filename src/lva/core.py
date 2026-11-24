"""Low-volatility sorts: month-end signals from trailing daily data, monthly holding returns, statistics."""
import numpy as np
import pandas as pd


def month_ends(index):
    s = pd.Series(index, index=index)
    return s.groupby([index.year, index.month]).max().values


def eligible(ret, dv, close, t_pos, cfg):
    """Symbols eligible at month-end position t_pos, using only data up to and including that day."""
    L = cfg["lookback_days"]
    w = ret.iloc[t_pos - L + 1:t_pos + 1]
    obs = w.notna().sum()
    zero = (w == 0).sum() / L
    px = close.iloc[t_pos]
    ok = (obs >= cfg["min_obs"]) & (zero <= cfg["max_zero_days"]) & (px >= cfg["min_price"])
    adv = dv.iloc[t_pos - L + 1:t_pos + 1].mean()[ok[ok].index]
    return adv.nlargest(cfg["universe_top"]).index


def signals(w, mkt):
    """Annualised volatility and beta against the market over the window w (date x symbol)."""
    vol = w.std() * np.sqrt(252)
    m = mkt.reindex(w.index)
    mm = m - m.mean(); wm = w - w.mean()
    beta = (wm.mul(mm, axis=0)).sum() / (mm ** 2).sum()
    return vol, beta


def groups(score, n, sector=None):
    """Quintile labels 1 (lowest score) .. n. With sector, rank within each sector."""
    if sector is None:
        return pd.qcut(score.rank(method="first"), n, labels=False) + 1
    out = pd.Series(index=score.index, dtype=float)
    for s, idx in score.groupby(sector.reindex(score.index)).groups.items():
        x = score[idx]
        if len(x) >= n:
            out[idx] = pd.qcut(x.rank(method="first"), n, labels=False) + 1
    return out.dropna()


def hold_return(ret, t0, t1, names):
    """Equal-weight buy-and-hold return of names from day after t0 to t1 (missing returns count as 0 after delisting)."""
    r = ret.iloc[t0 + 1:t1 + 1][names].fillna(0.0)
    growth = (1 + r).prod()
    return float(growth.mean() - 1), growth


def nw_t(y, x=None, lags=3):
    """OLS of y on [1, x] with Newey-West standard errors; returns (alpha, beta, t_alpha)."""
    y = np.asarray(y, float)
    X = np.ones((len(y), 1)) if x is None else np.column_stack([np.ones(len(y)), np.asarray(x, float)])
    b = np.linalg.lstsq(X, y, rcond=None)[0]; e = y - X @ b
    Xe = X * e[:, None]; S = Xe.T @ Xe
    for l in range(1, lags + 1):
        g = Xe[l:].T @ Xe[:-l]; S += (1 - l / (lags + 1)) * (g + g.T)
    XX = np.linalg.inv(X.T @ X); V = XX @ S @ XX
    return b[0], (b[1] if x is not None else np.nan), b[0] / np.sqrt(V[0, 0])


def stats(r, rf=None):
    r = pd.Series(r).dropna()
    ex = r - (rf.reindex(r.index).fillna(0) if rf is not None else 0)
    cum = (1 + r).cumprod(); dd = (cum / cum.cummax() - 1).min()
    ann = (1 + r).prod() ** (12 / len(r)) - 1
    vol = r.std() * np.sqrt(12)
    return {"ann": ann, "vol": vol, "sharpe": ex.mean() * 12 / vol if vol > 0 else np.nan, "maxdd": dd, "n": len(r)}
