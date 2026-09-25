"""Builds data/olist_seller.sqlite from the Olist CSVs. Standard library only.

    python3 prepare_data.py path/to/olist_csv_folder

Needs: olist_orders_dataset.csv, olist_order_items_dataset.csv, olist_products_dataset.csv,
product_category_name_translation.csv, olist_sellers_dataset.csv  (Kaggle: olistbr/brazilian-ecommerce).
"""
import csv
import sqlite3
import sys
from pathlib import Path


def build(csv_dir, out):
    d = Path(csv_dir)
    orders = {r["order_id"]: (r["order_purchase_timestamp"], r["order_status"]) for r in csv.DictReader(open(d / "olist_orders_dataset.csv", encoding="utf-8"))}
    en = {r["product_category_name"]: r["product_category_name_english"] for r in csv.DictReader(open(d / "product_category_name_translation.csv", encoding="utf-8-sig"))}
    prod = {r["product_id"]: en.get(r["product_category_name"]) for r in csv.DictReader(open(d / "olist_products_dataset.csv", encoding="utf-8"))}
    sellers = list(csv.DictReader(open(d / "olist_sellers_dataset.csv", encoding="utf-8")))
    out = Path(out)
    out.parent.mkdir(exist_ok=True)
    if out.exists():
        out.unlink()
    db = sqlite3.connect(out)
    db.execute("CREATE TABLE items (order_id TEXT, seller_id TEXT, category_english TEXT, price REAL, freight_value REAL, order_status TEXT, purchase_ts TEXT, purchase_date TEXT)")
    db.execute("CREATE TABLE sellers (seller_id TEXT PRIMARY KEY, city TEXT, state TEXT)")
    rows, total = [], 0
    for r in csv.DictReader(open(d / "olist_order_items_dataset.csv", encoding="utf-8")):
        total += 1
        cat = prod.get(r["product_id"])
        if cat and r["order_id"] in orders:
            ts, status = orders[r["order_id"]]
            rows.append((r["order_id"], r["seller_id"], cat, float(r["price"]), float(r["freight_value"]), status, ts, ts[:10]))
    db.executemany("INSERT INTO items VALUES (?,?,?,?,?,?,?,?)", rows)
    db.executemany("INSERT INTO sellers VALUES (?,?,?)", [(s["seller_id"], s["seller_city"], s["seller_state"]) for s in sellers])
    db.execute("CREATE INDEX ix_seller_date ON items(seller_id, purchase_date)")
    db.commit()
    db.close()
    print(f"{len(rows):,} item rows, {len(sellers):,} sellers written to {out} ({total - len(rows):,} of {total:,} order lines dropped: no English category)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    ROOT = Path(__file__).resolve().parent.parent
    build(sys.argv[1], ROOT / "data" / "olist_seller.sqlite")
