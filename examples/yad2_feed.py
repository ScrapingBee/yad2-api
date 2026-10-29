"""Yad2 real estate feed reader: Hebrew in, English schema out.

Fetches a public yad2.co.il real estate feed page through ScrapingBee,
reads the listings from the page's __NEXT_DATA__ JSON, and maps the Hebrew
values onto English field names. When a render arrives without
__NEXT_DATA__ (it happens, see the README), the rendered ad cards are parsed
instead, using their data-testid attributes.

Verified live on 2026-10-29 against
https://www.yad2.co.il/realestate/rent/tel-aviv-area

Usage:
    export SCRAPINGBEE_API_KEY=...
    python yad2_feed.py --deal rent --region tel-aviv-area --pages 2 --json out.json --csv out.csv

Public, logged out feed pages only. Phone numbers and seller contact details
sit behind a click and an account on Yad2 and are not touched here.
"""

from __future__ import annotations

import argparse
import csv
import html as htmllib
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Iterable

import requests

API = "https://app.scrapingbee.com/api/v1/"
SITE = "https://www.yad2.co.il"

# --------------------------------------------------------------------------
# Hebrew text hygiene
# --------------------------------------------------------------------------

# Bidi control characters found in Yad2 strings. The feed JSON alone carried
# 386 RIGHT-TO-LEFT MARKs (U+200F) on the page we tested, and the rendered
# floor line reads "קומה \u200e2\u200f", an LRM and RLM wrapped around the digit.
BIDI_CONTROLS = dict.fromkeys(
    map(ord, "\u200e\u200f\u061c\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"),
    None,
)
# Dashes and Hebrew punctuation folded to ASCII, so CSV consumers and
# spreadsheets that are not bidi aware see stable text.
FOLD = {
    ord("\u05be"): "-",   # HEBREW PUNCTUATION MAQAF
    ord("\u2010"): "-",
    ord("\u2011"): "-",
    ord("\u2012"): "-",
    ord("\u2013"): "-",   # EN DASH, used in Yad2 project blurbs
    ord("\u2014"): "-",   # EM DASH
    ord("\u2212"): "-",
    ord("\u05f3"): "'",   # HEBREW PUNCTUATION GERESH
    ord("\u05f4"): '"',   # HEBREW PUNCTUATION GERSHAYIM, as in the m"r unit
    ord("\u00a0"): " ",   # NO-BREAK SPACE
}


def clean_he(text: str | None) -> str | None:
    """Strip bidi marks, fold Hebrew dashes and quotes, squeeze spaces."""
    if text is None:
        return None
    text = htmllib.unescape(str(text)).translate(BIDI_CONTROLS).translate(FOLD)
    return re.sub(r"\s+", " ", text).strip()


# --------------------------------------------------------------------------
# Hebrew value -> English label maps
# --------------------------------------------------------------------------
# Keys are the exact Hebrew strings Yad2 returned (after clean_he). The
# English is our translation. Unknown values pass through as None in the
# *_en field and keep their Hebrew in the *_he field, so nothing is lost.

PROPERTY_TYPES = {
    "דירה": "apartment",
    "דירת גן": "garden apartment",
    "בית פרטי/ קוטג'": "private house / cottage",
    "גג/ פנטהאוז": "rooftop / penthouse",
    "מגרשים": "plots",
    "דופלקס": "duplex",
    "תיירות ונופש": "tourism and vacation",
    "דו משפחתי": "semi-detached house",
    "מרתף/ פרטר": "basement / parterre",
    "טריפלקס": "triplex",
    "יחידת דיור": "housing unit",
    "משק חקלאי/ נחלה": "farm / agricultural estate",
    "משק עזר": "auxiliary farm",
    "סאבלט": "sublet",
}

TAGS = {
    "חניה": "parking",
    'ממ"ד': "safe room (mamad)",
    "3 כיווני אוויר": "3 air directions",
    "נוף פתוח לעיר": "open city view",
    "נוף פתוח לפארק": "open park view",
    "נוף פתוח לים": "open sea view",
    "בהזדמנות": "bargain",
    "חבל לפספס": "do not miss",
    "ייחודי": "unique",
    "נכס חדש": "new property",
    "חדש מקבלן": "new from developer",
    "נכס עורפי": "rear facing property",
    "מומלץ": "recommended",
    "2 מרפסות": "2 balconies",
    "3 מרפסות": "3 balconies",
}

# Yad2 city id -> (Hebrew as returned, English). Ids are Yad2's own.
CITY_TABLE = {
    5000: ("תל אביב יפו", "Tel Aviv-Yafo"),
    6200: ("בת ים", "Bat Yam"),
    8600: ("רמת גן", "Ramat Gan"),
    6600: ("חולון", "Holon"),
    6300: ("גבעתיים", "Givatayim"),
    565: ("אזור", "Azor"),
}
CITIES = {cid: en for cid, (_, en) in CITY_TABLE.items()}
CITIES_BY_HE = {he: en for he, en in CITY_TABLE.values()}

AD_TYPES = {"private": "private owner", "commercial": "agency", "platinum": "promoted"}

# --------------------------------------------------------------------------
# Record
# --------------------------------------------------------------------------


@dataclass
class Listing:
    token: str
    url: str
    feed_slot: str              # which feed bucket it came from: yad2, platinum
    ad_type: str | None
    ad_type_en: str | None
    property_type_he: str | None
    property_type_en: str | None
    rooms: float | None
    size_m2: int | None
    floor: int | None
    price_ils: int | None
    price_before_ils: int | None
    price_drop_ils: int | None
    region_id: int | None
    city_id: int | None
    city_he: str | None
    city_en: str | None
    neighborhood_he: str | None
    street_he: str | None
    house_number: int | None
    lat: float | None
    lon: float | None
    agency_he: str | None
    condition_id: int | None
    tags_he: list[str] = field(default_factory=list)
    tags_en: list[str | None] = field(default_factory=list)
    image_count: int = 0
    cover_image: str | None = None
    source: str = "next_data"   # or "dom"


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------


class Yad2Blocked(RuntimeError):
    """Raised when no attempt returned a page with listings in it."""


def _key() -> str:
    try:
        return os.environ["SCRAPINGBEE_API_KEY"]
    except KeyError:
        sys.exit("Set SCRAPINGBEE_API_KEY first.")


def feed_url(deal: str, region: str, page: int = 1) -> str:
    url = f"{SITE}/realestate/{deal}/{region}"
    return url if page == 1 else f"{url}?page={page}"


def is_radware(html: str) -> bool:
    # The challenge page is a normal HTTP 200 with this title. ScrapingBee
    # bills it like any successful render, so it has to be caught here.
    return "<title>Radware Page</title>" in html[:3000] or (
        len(html) < 130_000 and "perfdrive" in html and "__NEXT_DATA__" not in html
    )


def fetch(url: str, max_attempts: int = 3, session: requests.Session | None = None) -> tuple[str, int]:
    """Render a Yad2 page with premium proxies. Returns (html, credits spent).

    HTTP 500 from ScrapingBee is free and retried. A Radware page is NOT
    free (25 credits each) and is retried only up to max_attempts.
    """
    s = session or requests.Session()
    spent = 0
    for attempt in range(1, max_attempts + 1):
        r = s.get(
            API,
            headers={"Authorization": f"Bearer {_key()}"},
            params={
                "url": url,
                "render_js": "true",
                "premium_proxy": "true",
                "wait": "3000",
            },
            timeout=180,
        )
        if r.status_code == 500:
            time.sleep(2 * attempt)
            continue
        r.raise_for_status()
        spent += int(r.headers.get("spb-cost", 0) or 0)
        body = r.content.decode("utf-8", errors="replace")
        if is_radware(body):
            print(f"  attempt {attempt}: Radware challenge page, {r.headers.get('spb-cost')} credits", file=sys.stderr)
        elif "__NEXT_DATA__" in body or 'data-testid="item-basic"' in body:
            return body, spent
        else:
            # Third outcome seen in testing: the real page, filters and all,
            # but the feed list never rendered. Billed, and useless.
            print(f"  attempt {attempt}: page rendered without a feed, {r.headers.get('spb-cost')} credits", file=sys.stderr)
        time.sleep(3)
    raise Yad2Blocked(f"{url}: no usable render in {max_attempts} attempts ({spent} credits)")


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def next_data(html: str) -> dict | None:
    m = NEXT_DATA.search(html)
    return json.loads(m.group(1)) if m else None


def feed_query(nd: dict) -> tuple[list, dict]:
    """Return (queryKey, data) of the realestate-*-feed react-query entry."""
    for q in nd["props"]["pageProps"]["dehydratedState"]["queries"]:
        key = q.get("queryKey") or []
        if key and isinstance(key[0], str) and re.fullmatch(r"realestate-\w+-feed", key[0]):
            return key, q["state"]["data"]
    raise KeyError("no realestate feed query in __NEXT_DATA__")


def _region_slug(url: str) -> str:
    m = re.search(r"/realestate/\w+/([a-z-]+)", url)
    return m.group(1) if m else "tel-aviv-area"


def from_json(ad: dict, slot: str, region_slug: str) -> Listing:
    addr = ad.get("address") or {}
    det = ad.get("additionalDetails") or {}
    city = addr.get("city") or {}
    house = addr.get("house") or {}
    coords = addr.get("coords") or {}
    ptype = clean_he((det.get("property") or {}).get("text"))
    tags = [clean_he(t.get("name")) for t in ad.get("tags") or []]
    price, before = ad.get("price"), ad.get("priceBeforeTag")
    images = (ad.get("metaData") or {}).get("images") or []
    return Listing(
        token=ad["token"],
        url=f"{SITE}/realestate/item/{region_slug}/{ad['token']}",
        feed_slot=slot,
        ad_type=ad.get("adType"),
        ad_type_en=AD_TYPES.get(ad.get("adType")),
        property_type_he=ptype,
        property_type_en=PROPERTY_TYPES.get(ptype),
        rooms=det.get("roomsCount"),
        size_m2=det.get("squareMeter"),
        floor=house.get("floor"),
        price_ils=price,
        price_before_ils=before,
        price_drop_ils=(before - price) if isinstance(before, int) and isinstance(price, int) else None,
        region_id=(addr.get("region") or {}).get("id"),
        city_id=city.get("id"),
        city_he=clean_he(city.get("text")),
        city_en=CITIES.get(city.get("id")),
        neighborhood_he=clean_he((addr.get("neighborhood") or {}).get("text")),
        street_he=clean_he((addr.get("street") or {}).get("text")),
        house_number=house.get("number"),
        lat=coords.get("lat"),
        lon=coords.get("lon"),
        agency_he=clean_he((ad.get("customer") or {}).get("agencyName")),
        condition_id=(det.get("propertyCondition") or {}).get("id"),
        tags_he=tags,
        tags_en=[TAGS.get(t) for t in tags],
        image_count=len(images),
        cover_image=(ad.get("metaData") or {}).get("coverImage"),
    )


# DOM fallback. data-testid values copied from the rendered page.
CARD = re.compile(r'<li data-testid="item-basic".*?</li>', re.S)
TESTID = r'data-testid="{}"[^>]*>(.*?)</(?:span|div)>'


def _text(fragment: str) -> str:
    return clean_he(re.sub(r"<[^>]+>", " ", fragment)) or ""


def _num(text: str | None) -> int | None:
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else None


def from_card(card: str, region_slug: str) -> Listing | None:
    href = re.search(r'href="/realestate/item/([a-z-]+)/(\w+)', card)
    if not href:
        return None

    def tid(name: str) -> str | None:
        m = re.search(TESTID.format(name), card, re.S)
        return _text(m.group(1)) if m else None

    line1 = (tid("item-info-line-1st") or "").split(",")
    line2 = tid("item-info-line-2nd") or ""        # "5 חדרים • קומה 2 • 120 מ"ר"
    rooms = re.search(r"([\d.]+)\s*חדרים", line2)
    floor = re.search(r"קומה\s*(-?\d+)", line2)
    size = re.search(r"(\d+)\s*מ\"ר", line2)
    ptype = line1[0].strip() if line1 and line1[0] else None
    tags = [clean_he(t) for t in re.findall(r"<span>([^<]+)</span>", (re.search(r'data-testid="item-tags-box"[^>]*>(.*?)</div>', card, re.S) or [None, ""])[1])]
    return Listing(
        token=href.group(2),
        url=f"{SITE}/realestate/item/{href.group(1)}/{href.group(2)}",
        feed_slot="dom",
        ad_type=None,
        ad_type_en=None,
        property_type_he=ptype,
        property_type_en=PROPERTY_TYPES.get(ptype or ""),
        rooms=float(rooms.group(1)) if rooms else None,
        size_m2=int(size.group(1)) if size else None,
        floor=int(floor.group(1)) if floor else None,
        price_ils=_num(tid("price")),
        price_before_ils=None,
        price_drop_ils=None,
        region_id=None,
        city_id=None,
        city_he=line1[-1].strip() if len(line1) > 1 else None,
        city_en=CITIES_BY_HE.get(line1[-1].strip()) if len(line1) > 1 else None,
        neighborhood_he=line1[1].strip() if len(line1) > 2 else None,
        street_he=tid("street-name"),
        house_number=None,
        lat=None,
        lon=None,
        agency_he=None,
        condition_id=None,
        tags_he=tags,
        tags_en=[TAGS.get(t) for t in tags],
        source="dom",
    )


def parse_feed(html: str, url: str) -> tuple[list[Listing], dict]:
    """Listings plus pagination info ({} when only the DOM was available)."""
    region_slug = _region_slug(url)
    nd = next_data(html)
    if nd:
        _, data = feed_query(nd)
        out = []
        for slot in ("platinum", "yad2"):
            out += [from_json(ad, slot, region_slug) for ad in data.get(slot) or [] if ad.get("token")]
        return out, data.get("pagination") or {}
    cards = [from_card(c, region_slug) for c in CARD.findall(html)]
    return [c for c in cards if c], {}


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------


def write_csv(rows: Iterable[Listing], path: str) -> None:
    rows = list(rows)
    if not rows:
        return
    # utf-8-sig adds a BOM so Excel opens Hebrew columns correctly.
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(rows[0])))
        w.writeheader()
        for r in rows:
            d = asdict(r)
            d["tags_he"] = "|".join(d["tags_he"])
            d["tags_en"] = "|".join(t or "" for t in d["tags_en"])
            w.writerow(d)


def crawl(deal: str, region: str, pages: int, max_attempts: int) -> tuple[list[Listing], dict]:
    session = requests.Session()
    seen, out, info = set(), [], {"credits": 0, "pages": []}
    for page in range(1, pages + 1):
        url = feed_url(deal, region, page)
        html, spent = fetch(url, max_attempts, session)
        info["credits"] += spent
        rows, pagination = parse_feed(html, url)
        fresh = [r for r in rows if r.token not in seen]
        seen.update(r.token for r in fresh)
        out += fresh
        info["pages"].append({"page": page, "rows": len(rows), "new": len(fresh), "credits": spent,
                              "source": rows[0].source if rows else None, **pagination})
        print(f"page {page}: {len(rows)} listings ({len(fresh)} new), {spent} credits, {pagination}", file=sys.stderr)
        if pagination and page >= pagination.get("totalPages", page):
            break
    return out, info


def main() -> None:
    p = argparse.ArgumentParser(description="Yad2 real estate feed to an English schema")
    p.add_argument("--deal", choices=["rent", "forsale"], default="rent")
    p.add_argument("--region", default="tel-aviv-area", help="feed slug, e.g. tel-aviv-area, jerusalem-area")
    p.add_argument("--pages", type=int, default=1)
    p.add_argument("--max-attempts", type=int, default=3, help="Radware retries per page (25 credits each)")
    p.add_argument("--json", help="write listings to this JSON file")
    p.add_argument("--csv", help="write listings to this CSV file")
    a = p.parse_args()

    rows, info = crawl(a.deal, a.region, a.pages, a.max_attempts)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"meta": info, "listings": [asdict(r) for r in rows]}, f, ensure_ascii=False, indent=2)
    if a.csv:
        write_csv(rows, a.csv)
    for r in rows[:5]:
        print(f"{r.token}  {r.price_ils} ILS  {r.rooms} rooms  {r.size_m2} m2  "
              f"{r.property_type_en}  {r.city_en or r.city_he}  tags={[t for t in r.tags_en if t]}")
    print(f"{len(rows)} listings, {info['credits']} credits")


if __name__ == "__main__":
    main()
