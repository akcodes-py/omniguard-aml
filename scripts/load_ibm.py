"""Phase 6 (experiment): ingest an IBM AML subset for a one-shot scale test.

Usage: python scripts/load_ibm.py [--laundry-accounts 400] [--clean-accounts 1500]
Reads data/raw/ibm/HI-Small_Trans.csv (Kaggle: ealtman2019/ibm-transactions-
for-anti-money-laundering-aml), two-pass account-first sample with seed 42:
laundering-touched accounts (capped) + a clean sample, full histories, mapped
to the app schema. No eval alerts are built — training-only experiment.

IBM cols: Timestamp, From Bank, Account, To Bank, Account, Amount Received,
Receiving Currency, Amount Paid, Payment Currency, Payment Format,
Is Laundering. Amount = Amount Paid, kept in its original currency
(multi-currency mixing is a known simplification, stated in the report).
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from collections import Counter
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from omniguard.db import connect, init_db, is_postgres, t  # noqa: E402
from omniguard.db import run as qrun  # noqa: E402

rng = random.Random(42)

# All 11 columns get app-side names (duplicate "Account" headers cannot be
# selected reliably by pandas), then we subset to what we need.
ALL_COLS = ["ts", "from_bank", "from_acct", "to_bank", "to_acct", "amount_received",
            "rcv_currency", "amount", "pay_currency", "format", "is_laundering"]
USE = ["ts", "from_bank", "from_acct", "to_bank", "to_acct", "amount", "format", "is_laundering"]
# Bank + account IDs are zero-padded / hex-looking strings ("010", "8000EBD30") —
# keep them as strings so leading zeros and letters survive.
DTYPES = {"ts": "object", "from_bank": "object", "from_acct": "object", "to_bank": "object",
          "to_acct": "object", "format": "object", "amount": "float64", "is_laundering": "int64"}

PURPOSES = ["trading", "payroll", "treasury", "personal", "merchant settlement"]
OCCS = ["engineer", "nurse", "trader", "cashier", "director"]


def _insert(table_cols: str, table: str, nmarks: int, row: tuple, cur) -> None:
    if is_postgres():
        qrun(cur, f"INSERT INTO {t(table)} ({table_cols}) VALUES ({','.join(['?'] * nmarks)}) "
                  f"ON CONFLICT DO NOTHING", row)
    else:
        qrun(cur, f"INSERT OR IGNORE INTO {table} ({table_cols}) VALUES ({','.join(['?'] * nmarks)})", row)


def _read(src: Path):
    return pd.read_csv(src, names=ALL_COLS, header=0, dtype=DTYPES, chunksize=500_000)


def main(laundry_accounts: int = 400, clean_accounts: int = 1500, min_txs: int = 5,
         max_acct_txs: int = 5000) -> None:
    cands = sorted(Path("data/raw/ibm").glob("*.csv"))
    src = next((f for f in cands if f.name.upper().startswith("HI-SMALL_TRANS")), None)
    if not src:
        raise SystemExit("IBM HI-Small CSV missing: run kaggle download first (data/raw/ibm/)")
    t0 = time.time()
    print("pass 1: account activity census over", src)
    counts: Counter = Counter()
    laundry_touch: set[str] = set()
    for chunk in _read(src):
        sk = chunk["from_bank"].astype(str) + "_" + chunk["from_acct"].astype(str)
        dk = chunk["to_bank"].astype(str) + "_" + chunk["to_acct"].astype(str)
        counts.update(sk)
        counts.update(dk)
        f = chunk[chunk["is_laundering"] == 1]
        if len(f):
            laundry_touch.update(f["from_bank"].astype(str) + "_" + f["from_acct"].astype(str))
            laundry_touch.update(f["to_bank"].astype(str) + "_" + f["to_acct"].astype(str))
    laundry_keep = sorted(a for a in laundry_touch if min_txs <= counts[a] <= max_acct_txs)[:laundry_accounts]
    clean_pool = sorted(a for a, c in counts.items() if min_txs <= c <= max_acct_txs and a not in laundry_touch)
    clean_keep = rng.sample(clean_pool, min(clean_accounts, len(clean_pool)))
    keep = set(laundry_keep) | set(clean_keep)
    print(f"census: {len(counts)} accounts, {len(laundry_touch)} laundering-touched; "
          f"keeping {len(laundry_keep)} laundering + {len(clean_keep)} clean "
          f"(min {min_txs}, max {max_acct_txs} txs/account)")
    print("pass 2: ingest full histories")
    parts = []
    for chunk in _read(src):
        chunk = chunk.copy()
        chunk["src"] = chunk["from_bank"].astype(str) + "_" + chunk["from_acct"].astype(str)
        chunk["dst"] = chunk["to_bank"].astype(str) + "_" + chunk["to_acct"].astype(str)
        hit = chunk[chunk["src"].isin(keep) | chunk["dst"].isin(keep)]
        if len(hit):
            parts.append(hit[["ts", "src", "dst", "amount", "format", "is_laundering"]])
    df = pd.concat(parts).reset_index(drop=True)
    df["ts_iso"] = pd.to_datetime(df["ts"], format="%Y/%m/%d %H:%M").dt.strftime("%Y-%m-%dT%H:%M:%S")
    bad = int(df["ts_iso"].isna().sum())
    if bad:
        print(f"warning: dropping {bad} rows with unparseable timestamps")
        df = df[df["ts_iso"].notna()]
    print(f"ingesting {len(df)} txs, laundering={int(df['is_laundering'].sum())}, "
          f"span {df['ts_iso'].min()} .. {df['ts_iso'].max()}")

    init_db()
    con = connect()
    try:
        cur = con.cursor()
        accts = sorted(set(df["src"]) | set(df["dst"]))
        for aid in accts:
            _insert("account_id, customer_name, account_purpose, occupation_category, "
                    "high_risk_jurisdiction, parent_entity_id", "accounts", 6,
                    (aid, aid, rng.choice(PURPOSES), rng.choice(OCCS), False, None), cur)
        n = 0
        for r in df.itertuples():
            _insert("tx_id, ts, src_account, dst_account, amount, tx_type, channel, memo, "
                    "counterparty_name, is_laundering", "transactions", 10,
                    (f"ibm-{n:06d}", r.ts_iso, r.src, r.dst, round(float(r.amount), 2),
                     str(r.format).lower(), str(r.format).lower(), f"{r.format} payment",
                     r.dst, bool(r.is_laundering)), cur)
            n += 1
            if n % 50_000 == 0:
                print(f"  inserted {n}/{len(df)}")
        if hasattr(con, "commit"):
            con.commit()
        print(f"done: {len(accts)} accounts, {len(df)} txs in {time.time() - t0:.0f}s")
    finally:
        con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--laundry-accounts", type=int, default=400)
    ap.add_argument("--clean-accounts", type=int, default=1500)
    ap.add_argument("--min-txs", type=int, default=5)
    ap.add_argument("--max-acct-txs", type=int, default=5000)
    args = ap.parse_args()
    main(laundry_accounts=args.laundry_accounts, clean_accounts=args.clean_accounts,
         min_txs=args.min_txs, max_acct_txs=args.max_acct_txs)
