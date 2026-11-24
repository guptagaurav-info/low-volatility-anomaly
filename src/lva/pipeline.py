"""Run the pre-registered low-volatility test and write reports/metrics.json, monthly returns and figures."""
import json, os, pickle
import numpy as np
import pandas as pd
import yaml
from lva.core import month_ends, eligible, signals, groups, hold_return, nw_t, stats

CFG = yaml.safe_load(open("configs/default.yaml"))


def load():
    if os.path.exists("data/panel.pkl"):
        ret, dv, close, ind, spy = pickle.load(open("data/panel.pkl", "rb"))
    else:
        from lva.data import panel, spy_returns
        ret, dv, close, ind = panel(); spy = spy_returns(ret.index)
        pickle.dump((ret, dv, close, ind, spy), open("data/panel.pkl", "wb"), protocol=4)
    prof = pd.read_parquet("data/universe.parquet").set_index("symbol")["sector"] if os.path.exists("data/universe.parquet") else None
    t = pd.read_parquet("data/tsy.parquet") if os.path.exists("data/tsy.parquet") else None
    return ret, dv, close, prof, spy, t


def run():
    ret, dv, close, sector, spy, tsy = load()
    idx = ret.index; me = [d for d in month_ends(idx) if pd.Timestamp(CFG["first_month"]) <= d <= pd.Timestamp(CFG["last_month"])]
    pos = {d: idx.get_loc(d) for d in me}
    rf3 = tsy.set_index("d")["bc_3month"].astype(float).reindex(idx).ffill() if tsy is not None else pd.Series(0.0, idx)
    n = CFG["n_groups"]; L = CFG["lookback_days"]; c = CFG["cost_bps_per_side"] / 1e4
    rows = []; prev = {}; sector_mix = []
    for a, b in zip(me[:-1], me[1:]):
        ta, tb = pos[a], pos[b]
        names = eligible(ret, dv, close, ta, CFG)
        w = ret.iloc[ta - L + 1:ta + 1][names]
        vol, beta = signals(w, spy)
        row = {"month": b, "rf": rf3.iloc[ta] / 12, "mkt": float((1 + spy.iloc[ta + 1:tb + 1].fillna(0)).prod() - 1)}
        for key, score, sec in [("vol", vol, None), ("beta", beta, None), ("volsec", vol, sector)]:
            g = groups(score.dropna(), n, sec)
            for q in range(1, n + 1):
                mem = list(g[g == q].index)
                r, _ = hold_return(ret, ta, tb, mem)
                old = prev.get((key, q), set()); turn = 1.0 if not old else len(set(mem) - old) / max(len(mem), 1)
                prev[(key, q)] = set(mem)
                row[f"{key}_q{q}"] = r; row[f"{key}_q{q}_cost"] = 2 * turn * c
                row[f"{key}_q{q}_beta"] = float(beta[mem].mean()); row[f"{key}_q{q}_vol"] = float(vol[mem].mean())
            if key == "vol" and sector is not None:
                low = list(g[g == 1].index); sector_mix.append(sector.reindex(low).value_counts(normalize=True).rename(b))
        rows.append(row)
    m = pd.DataFrame(rows).set_index("month")
    pickle.dump((m, pd.DataFrame(sector_mix).fillna(0)), open("data/monthly.pkl", "wb"))
    return m, pd.DataFrame(sector_mix).fillna(0)


def summarise(m, mix):
    n = CFG["n_groups"]; rf = m["rf"]; out = {"months": len(m), "start": str(m.index[0].date()), "end": str(m.index[-1].date())}
    out["spy"] = stats(m["mkt"], rf)
    for key in ["vol", "beta", "volsec"]:
        d = {}
        for q in range(1, n + 1):
            r = m[f"{key}_q{q}"] - m[f"{key}_q{q}_cost"]
            s = stats(r, rf); a, b, t = nw_t(r - rf, m["mkt"] - rf)
            s.update({"capm_alpha_ann": a * 12, "capm_beta": b, "alpha_t": t, "gross_ann": stats(m[f"{key}_q{q}"])["ann"],
                      "ex_ante_beta": m[f"{key}_q{q}_beta"].mean(), "ex_ante_vol": m[f"{key}_q{q}_vol"].mean(),
                      "cost_ann": m[f"{key}_q{q}_cost"].mean() * 12})
            d[f"q{q}"] = s
        lo = m[f"{key}_q1"] - m[f"{key}_q1_cost"]; hi = m[f"{key}_q{n}"] - m[f"{key}_q{n}_cost"]
        ls = lo - hi
        a, b, t = nw_t(ls, m["mkt"] - rf); _, _, traw = nw_t(ls)
        d["low_minus_high"] = {**stats(ls), "mean_ann": ls.mean() * 12, "t_raw": traw, "capm_alpha_ann": a * 12, "capm_beta": b, "alpha_t": t}
        bl = m[f"{key}_q1_beta"]; bh = m[f"{key}_q{n}_beta"]
        bab = (lo - rf) / bl - (hi - rf) / bh
        a2, b2, t2 = nw_t(bab, m["mkt"] - rf); _, _, tb = nw_t(bab)
        d["beta_neutral"] = {**stats(bab), "mean_ann": bab.mean() * 12, "t_raw": tb, "capm_alpha_ann": a2 * 12, "capm_beta": b2, "alpha_t": t2,
                             "avg_long_leverage": float((1 / bl).mean()), "avg_short_scale": float((1 / bh).mean())}
        out[key] = d
        if key == "vol":
            m["ls"] = ls; m["bab"] = bab; m["lo_net"] = lo; m["hi_net"] = hi
    # eras
    out["eras"] = {}
    for name, (s, e) in CFG["periods"].items():
        x = m.loc[s:e]
        out["eras"][name] = {"low": stats(x["lo_net"], x["rf"]), "high": stats(x["hi_net"], x["rf"]), "spy": stats(x["mkt"], x["rf"]),
                             "low_minus_high_ann": x["ls"].mean() * 12, "beta_neutral_ann": x["bab"].mean() * 12,
                             "lmh_alpha_ann": nw_t(x["ls"], x["mkt"] - x["rf"])[0] * 12}
    # crash months and up/down markets
    worst = m["mkt"].nsmallest(CFG["crash_months"]).index
    out["crash"] = {"spy": m.loc[worst, "mkt"].mean(), "low": m.loc[worst, "lo_net"].mean(), "high": m.loc[worst, "hi_net"].mean()}
    up = m["mkt"] > m["rf"]
    out["capture"] = {"low_up": m.loc[up, "lo_net"].mean() / m.loc[up, "mkt"].mean(), "low_down": m.loc[~up, "lo_net"].mean() / m.loc[~up, "mkt"].mean(),
                      "high_up": m.loc[up, "hi_net"].mean() / m.loc[up, "mkt"].mean(), "high_down": m.loc[~up, "hi_net"].mean() / m.loc[~up, "mkt"].mean()}
    # sector tilt of the low-volatility quintile
    out["low_sector_avg"] = mix.mean().sort_values(ascending=False).head(6).round(3).to_dict()
    out["low_sector_last"] = mix.iloc[-1].sort_values(ascending=False).head(6).round(3).to_dict()
    # dollar translation
    N = CFG["notional_usd"]
    out["dollars"] = {"low_vs_spy_maxdd_saved": (out["vol"]["q1"]["maxdd"] - out["spy"]["maxdd"]) * N,
                      "beta_neutral_alpha_usd": out["vol"]["beta_neutral"]["capm_alpha_ann"] * N}
    m.to_csv("reports/monthly_returns.csv")
    return out, m


def figures(m, out):
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    n = CFG["n_groups"]
    plt.rcParams.update({"font.size": 11, "axes.spines.top": False, "axes.spines.right": False})
    # 1 return vs risk by quintile
    fig, ax = plt.subplots(figsize=(8, 4.5))
    q = out["vol"]
    xs = [q[f"q{i}"]["vol"] * 100 for i in range(1, n + 1)]; ys = [q[f"q{i}"]["ann"] * 100 for i in range(1, n + 1)]
    ax.plot(xs, ys, "o-", color="#1f4e79")
    for i, (x, y) in enumerate(zip(xs, ys)): ax.annotate(f"Q{i+1}", (x, y), textcoords="offset points", xytext=(6, 6))
    ax.plot(out["spy"]["vol"] * 100, out["spy"]["ann"] * 100, "s", color="#c0504d"); ax.annotate("S&P 500 (SPY)", (out["spy"]["vol"] * 100, out["spy"]["ann"] * 100), textcoords="offset points", xytext=(6, -14))
    ax.set_xlabel("Volatility, % a year"); ax.set_ylabel("Return after costs, % a year")
    ax.set_title("Return barely rose with risk, and the riskiest fifth earned least (2002–2026)")
    fig.tight_layout(); fig.savefig("reports/figures/risk_return.png", dpi=150); plt.close(fig)
    # 2 cumulative
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for col, lab, colr in [("lo_net", "Lowest-volatility fifth", "#1f4e79"), ("hi_net", "Highest-volatility fifth", "#c0504d"), ("mkt", "S&P 500 (SPY)", "#7f7f7f")]:
        ax.plot((1 + m[col]).cumprod(), label=lab, color=colr)
    ax.set_yscale("log"); ax.set_ylabel("Growth of $1 (log scale)")
    from matplotlib.ticker import FuncFormatter; ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:g}"))
    ax.set_title("Growth of $1, after costs"); ax.legend(frameon=False); fig.tight_layout(); fig.savefig("reports/figures/cumulative.png", dpi=150); plt.close(fig)
    # 3 rolling 36m alpha of beta-neutral
    fig, ax = plt.subplots(figsize=(8, 4.5))
    roll = m["bab"].rolling(36).mean() * 12 * 100; roll2 = m["ls"].rolling(36).mean() * 12 * 100
    ax.plot(roll, color="#1f4e79", label="Beta-neutral (low levered up, high scaled down)"); ax.plot(roll2, color="#c0504d", label="Dollar-neutral (low minus high)")
    ax.axhline(0, color="k", lw=0.7); ax.set_ylabel("% a year, trailing 36 months"); ax.legend(frameon=False, fontsize=9)
    ax.set_title("The two ways to trade it disagree"); fig.tight_layout(); fig.savefig("reports/figures/rolling.png", dpi=150); plt.close(fig)


if __name__ == "__main__":
    os.makedirs("reports/figures", exist_ok=True)
    if os.path.exists("data/monthly.pkl"):
        m, mix = pickle.load(open("data/monthly.pkl", "rb"))
    else:
        m, mix = run()
    out, m = summarise(m, mix)
    json.dump(out, open("reports/metrics.json", "w"), indent=1, default=float)
    figures(m, out)
    print(json.dumps(out, indent=1, default=lambda v: round(float(v), 4))[:6000])
