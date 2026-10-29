"""Rent per square metre and price drops from Yad2 listings.

Reads the JSON written by yad2_feed.py, or crawls fresh pages when --live is
given, and prints three tables:

  1. median and mean ILS per m2 by city (English name when known)
  2. median ILS per m2 by rooms count
  3. listings whose price is below Yad2's own priceBeforeTag (a cut)

Usage:
    python yad2_feed.py --pages 2 --json rent.json
    python yad2_rent_stats.py rent.json --csv per_city.csv
    python yad2_rent_stats.py --live --region tel-aviv-area --pages 1
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import defaultdict
from dataclasses import asdict


def load(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)["listings"]


def live(region: str, pages: int, deal: str) -> list[dict]:
    import yad2_feed  # same folder

    rows, info = yad2_feed.crawl(deal, region, pages, max_attempts=3)
    print(f"crawled {len(rows)} listings for {info['credits']} credits", file=sys.stderr)
    return [asdict(r) for r in rows]


def per_m2(rows: list[dict]) -> list[tuple[dict, float]]:
    out = []
    for r in rows:
        price, size = r.get("price_ils"), r.get("size_m2")
        # Sublets and listings with no size are skipped, as are prices that
        # are clearly sale prices on a rent feed (Yad2 accepts free text).
        if not price or not size or size < 10 or price > 100_000:
            continue
        out.append((r, price / size))
    return out


def group(pairs, key) -> dict[str, list[float]]:
    g: dict[str, list[float]] = defaultdict(list)
    for r, v in pairs:
        g[key(r)].append(v)
    return g


def table(g: dict[str, list[float]], title: str) -> list[dict]:
    rows = [
        {"group": k, "n": len(v), "median_ils_m2": round(statistics.median(v), 1), "mean_ils_m2": round(statistics.fmean(v), 1)}
        for k, v in g.items()
    ]
    rows.sort(key=lambda x: (-x["n"], x["group"]))
    print(f"\n{title}")
    for x in rows:
        print(f"  {x['group']:<22} n={x['n']:<3} median {x['median_ils_m2']:>6} ILS/m2   mean {x['mean_ils_m2']:>6}")
    return rows


def main() -> None:
    p = argparse.ArgumentParser(description="ILS per m2 and price cuts from Yad2 listings")
    p.add_argument("json_file", nargs="?", help="output of yad2_feed.py --json")
    p.add_argument("--live", action="store_true", help="crawl instead of reading a file")
    p.add_argument("--region", default="tel-aviv-area")
    p.add_argument("--deal", default="rent", choices=["rent", "forsale"])
    p.add_argument("--pages", type=int, default=1)
    p.add_argument("--csv", help="write the per city table to CSV")
    a = p.parse_args()

    if a.live:
        rows = live(a.region, a.pages, a.deal)
    elif a.json_file:
        rows = load(a.json_file)
    else:
        p.error("give a JSON file or --live")

    pairs = per_m2(rows)
    print(f"{len(rows)} listings, {len(pairs)} with a usable price and size")
    by_city = table(group(pairs, lambda r: r.get("city_en") or r.get("city_he") or "?"), "ILS per m2 by city")
    table(group(pairs, lambda r: f"{r.get('rooms')} rooms"), "ILS per m2 by rooms")

    cuts = sorted((r for r in rows if r.get("price_drop_ils")), key=lambda r: -r["price_drop_ils"])
    print(f"\nPrice cuts ({len(cuts)} listings below their previous asking price)")
    for r in cuts[:10]:
        pct = 100 * r["price_drop_ils"] / r["price_before_ils"]
        print(f"  {r['token']}  {r['price_before_ils']} -> {r['price_ils']} ILS  (-{pct:.1f}%)  {r.get('city_en') or r.get('city_he')}")

    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(by_city[0]))
            w.writeheader()
            w.writerows(by_city)


if __name__ == "__main__":
    main()
