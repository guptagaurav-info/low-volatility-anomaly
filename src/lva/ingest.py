"""Download the public mirror files (sha256-pinned) and write the extracts the pipeline reads."""
import hashlib, os, urllib.request, yaml, duckdb

RAW = "data/raw/"


def fetch(cfg, local=None):
    os.makedirs(RAW, exist_ok=True)
    for f, s in cfg["sources"].items():
        p = RAW + f
        if not os.path.exists(p):
            if local and os.path.exists(os.path.join(local, f)):
                os.symlink(os.path.abspath(os.path.join(local, f)), p)
            else:
                urllib.request.urlretrieve(s["url"], p)
        h = hashlib.sha256(open(p, "rb").read()).hexdigest()
        print(f, h[:12], "OK" if h == s["sha256"] else "MISMATCH (mirror updated; results may differ)")


def extract():
    """US operating companies (profile has a sector and industry; ETFs and funds have none), prices from 2000."""
    c = duckdb.connect()
    c.sql(f"""create table u as select symbol, industry, sector from '{RAW}stock_profile.parquet'
              where country = 'United States' and sector is not null and industry is not null
              and symbol not like '%-%' and symbol not like '%.%'""")
    c.sql("copy (select * from u) to 'data/universe.parquet'")
    c.sql(f"""copy (select p.symbol, cast(p.report_date as date) d, cast(p.close as double) close, p.volume
              from '{RAW}stock_prices.parquet' p join u using(symbol) where p.report_date >= '2000-01-01' and p.close > 0) to 'data/daily.parquet'""")
    c.sql(f"copy (select v.symbol, cast(v.report_date as date) d, cast(v.amount as double) amount from '{RAW}stock_dividend_events.parquet' v join u using(symbol)) to 'data/divs.parquet'")
    c.sql(f"copy (select symbol, cast(report_date as date) d, cast(close as double) close from '{RAW}stock_prices.parquet' where symbol = 'SPY' and report_date >= '2000-01-01') to 'data/spy.parquet'")
    c.sql(f"copy (select symbol, cast(report_date as date) d, cast(amount as double) amount from '{RAW}stock_dividend_events.parquet' where symbol = 'SPY') to 'data/spy_divs.parquet'")
    c.sql(f"copy (select cast(report_date as date) d, cast(bc_3month as double) bc_3month from '{RAW}daily_treasury_yield.parquet' where report_date >= '2000-01-01') to 'data/tsy.parquet'")


if __name__ == "__main__":
    cfg = yaml.safe_load(open("configs/default.yaml")); fetch(cfg, os.environ.get("LOCAL_MIRROR")); extract()
