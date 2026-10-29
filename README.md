# Yad2 API

<p align="center">
  <a href="https://www.scrapingbee.com/">
    <img src="REPLACE_WITH_SCREENSHOT_URL" alt="yad2-api" />
  </a>
</p>

[![checks](https://github.com/ScrapingBee/yad2-api/workflows/checks/badge.svg)](https://github.com/ScrapingBee/yad2-api/actions)
[![license](https://img.shields.io/github/license/ScrapingBee/yad2-api.svg)](LICENSE)

Yad2 (yad2.co.il) is Israel's largest classifieds site, and its real estate section is where most of the country's rental market is listed. This repo is a working [Yad2 API](https://www.scrapingbee.com/scrapers/yad2-api/) built on [ScrapingBee](https://www.scrapingbee.com/): it renders a public Yad2 feed page, pulls the listings out of the page's own JSON, and turns Hebrew values into an English schema with prices in Israeli new shekels (ILS). Everything below was measured on 2026-10-29 against the Tel Aviv area rental feed, including the parts that did not work.

Most of the work is not in the request. It is in the Hebrew: bidi control characters hidden inside strings, a Hebrew hyphen that is not a hyphen, a unit written with a Hebrew double quote, and a shekel sign that moves from one side of the number to the other depending on the card.

## The data source: `__NEXT_DATA__` on a feed page

A rendered feed page such as `https://www.yad2.co.il/realestate/rent/tel-aviv-area` is a Next.js page. Its `<script id="__NEXT_DATA__">` block holds a React Query cache, and one entry in `props.pageProps.dehydratedState.queries` is the feed itself. This is one listing from that entry, trimmed (two of its image URLs kept, the `inProperty` flag removed):

```json
{
  "queryKey": ["realestate-rent-feed", { "region": "3" }],
  "state": {
    "data": {
      "yad2": [
        {
          "address": {
            "region": { "text": "תל אביב והסביבה", "id": 3 },
            "city": { "id": 5000, "text": "תל אביב יפו" },
            "area": { "text": "אזור תל אביב יפו" },
            "neighborhood": { "id": 1515, "text": "רמת אביב ג'" },
            "street": { "text": "יעקב וייס" },
            "house": { "number": 4, "floor": 10 },
            "coords": { "lon": 34.802148, "lat": 32.125826 }
          },
          "subcategoryId": 2,
          "categoryId": 2,
          "adType": "private",
          "price": 16000,
          "token": "sha1i8dq",
          "additionalDetails": {
            "property": { "text": "דירה" },
            "roomsCount": 5,
            "squareMeter": 150,
            "propertyCondition": { "id": 2 },
            "promotions": []
          },
          "metaData": {
            "coverImage": "https://img.yad2.co.il/Pic/202610/20/2_2/o/y2_1pa_010903_20261020192423.jpeg",
            "images": ["https://img.yad2.co.il/Pic/202610/20/2_2/o/y2_1pa_010903_20261020192423.jpeg", "..."]
          },
          "tags": [
            { "name": "נוף פתוח לפארק", "id": 1005, "priority": 1 },
            { "name": "3 כיווני אוויר", "id": 1007, "priority": 1 },
            { "name": "חניה", "id": 1003, "priority": 1 }
          ],
          "orderId": 57649934,
          "priority": 3
        }
      ],
      "pagination": { "total": 7891, "totalPages": 198 }
    }
  }
}
```

Things worth knowing about that object:

- **The keys are English, the values are Hebrew.** That is the whole mapping problem in one sentence. `price` is already an integer in shekels, `roomsCount` is a number that can be `3.5`, and `squareMeter` is an integer.
- **`token` is the listing id.** The public listing URL is `/realestate/item/<region-slug>/<token>`, for example `https://www.yad2.co.il/realestate/item/tel-aviv-area/sha1i8dq`.
- **The feed has buckets.** On page 1 we saw `yad2` (40 listings), `platinum` (3 promoted listings), `leadingBroker` (6 agency logos, no listings), `yad1` (new developer projects in a different shape) and empty `kingOfTheHar`, `trio`, `booster` and `lookalike`. `yad2_feed.py` reads `platinum` and `yad2`, which gave 43 listings per page.
- **Price cuts are explicit.** Ten of the 40 listings on page 1 had a `priceBeforeTag`, for example `{"token": "bvel0ol8", "adType": "commercial", "price": 7700, "priceBeforeTag": 8000}`.
- **`adType` tells you who posted it.** `private` is an owner, `commercial` is an agency, and agency listings carry `customer.agencyName`.
- **Pagination is `?page=N`.** The query key becomes `["realestate-rent-feed", {"region": "3", "page": "2"}]` and the page title gains a Hebrew page suffix. `totalPages` was 198 for the Tel Aviv area, so a full pass is 198 renders before retries.

## Hebrew values onto an English schema

`yad2_feed.py` keeps every Hebrew value in a `*_he` field and adds an `*_en` field next to it when the value is in one of its lookup tables. An unknown value keeps its Hebrew and gets `None` in English, so the scraper never drops data it does not understand. The tables cover every value seen in the captured feed pages; the English wording is ours.

| Yad2 JSON path | Hebrew value seen | English field | English value |
|---|---|---|---|
| `additionalDetails.property.text` | `דירה` | `property_type_en` | `apartment` |
| `additionalDetails.property.text` | `דירת גן` | `property_type_en` | `garden apartment` |
| `additionalDetails.property.text` | `גג/ פנטהאוז` | `property_type_en` | `rooftop / penthouse` |
| `additionalDetails.property.text` | `סאבלט` | `property_type_en` | `sublet` |
| `tags[].name` | `חניה` | `tags_en` | `parking` |
| `tags[].name` | `ממ"ד` | `tags_en` | `safe room (mamad)` |
| `tags[].name` | `3 כיווני אוויר` | `tags_en` | `3 air directions` |
| `tags[].name` | `בהזדמנות` | `tags_en` | `bargain` |
| `address.city.id` + `.text` | `5000`, `תל אביב יפו` | `city_en` | `Tel Aviv-Yafo` |
| `address.city.id` + `.text` | `6200`, `בת ים` | `city_en` | `Bat Yam` |
| `adType` | `private` / `commercial` | `ad_type_en` | `private owner` / `agency` |

The property type list is not guessed. The same `__NEXT_DATA__` carries the search form's options under the `base-search-options` query, with ids: `{"id": "1", "title": "דירה"}`, `{"id": "3", "title": "דירת גן"}`, `{"id": "6", "title": "גג/ פנטהאוז"}` and so on. Translate that list once and the mapping covers every listing.

`propertyCondition.id` has no label in the page data we captured, so it is passed through as `condition_id` without a translation. Neighbourhood and street names stay in Hebrew: Yad2 has its own neighbourhood ids (`1515` above) and any English name we added would be our transliteration, not Yad2's data.

The record the script writes for one listing (cover image URL left out here):

```python
Listing(token='7xa5n290', url='https://www.yad2.co.il/realestate/item/tel-aviv-area/7xa5n290',
        feed_slot='platinum', ad_type='commercial', ad_type_en='agency',
        property_type_he='דירת גן', property_type_en='garden apartment', rooms=3, size_m2=100, floor=0,
        price_ils=7500, price_before_ils=None, price_drop_ils=None, region_id=3, city_id=6300,
        city_he='גבעתיים', city_en='Givatayim', neighborhood_he='שינקין', street_he='המרי', house_number=26,
        lat=32.074968, lon=34.814167, agency_he='נכסים street', condition_id=2,
        tags_he=['בהזדמנות', 'חבל לפספס', 'ייחודי'], tags_en=['bargain', 'do not miss', 'unique'],
        image_count=12, source='next_data')
```

## RTL handling: what is hidden inside Yad2 strings

Hebrew is right to left, numbers and Latin text are left to right, and Yad2 inserts Unicode bidi controls to make mixed strings display in the right order. They are invisible on screen and very visible to code: `"קומה 2" == "קומה \u200e2\u200f"` is `False` in Python.

Counted in the `__NEXT_DATA__` of one Tel Aviv rental page:

| Character | Code point | Count | Where it appeared |
|---|---|---|---|
| RIGHT-TO-LEFT MARK | U+200F | 386 | project blurbs and prices, `\u200f6,960 \u200f\u20aa` |
| Hebrew maqaf | U+05BE | 36 | free text, the Hebrew hyphen |
| EN DASH | U+2013 | 97 | project blurbs, `\u2013 החל מ` |
| NO-BREAK SPACE | U+00A0 | 156 | before prices and dashes |
| Hebrew gershayim | U+05F4 | 52 | abbreviations such as `נדל״ן` and the unit `מ״ר` (square metres) |

The rendered cards add their own: the floor line of a card reads `5 חדרים • קומה \u200e2\u200f • 120 מ״ר`, a LEFT-TO-RIGHT MARK and a RIGHT-TO-LEFT MARK wrapped around the single digit `2`. A regex for `קומה (\d+)` does not match that until the marks are gone.

The cleaner every field passes through:

```python
BIDI_CONTROLS = dict.fromkeys(
    map(ord, "\u200e\u200f\u061c\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"), None)
FOLD = {ord("\u05be"): "-", ord("\u2013"): "-", ord("\u2014"): "-",
        ord("\u05f3"): "'", ord("\u05f4"): '"', ord("\u00a0"): " "}

def clean_he(text):
    text = htmllib.unescape(str(text)).translate(BIDI_CONTROLS).translate(FOLD)
    return re.sub(r"\s+", " ", text).strip()
```

Folding the gershayim to an ASCII `"` is a deliberate choice: Yad2 itself is inconsistent and writes the safe room tag as `ממ"ד` with a plain quote while the CMS text uses `ממ״ד` with gershayim. After folding, both match the same lookup key. The CSV export is written as `utf-8-sig` so Excel opens the Hebrew columns without mojibake; the text inside stays logical order, and the spreadsheet handles display direction.

## Shekel prices, two formats

In the JSON, `price` is a plain integer and needs no parsing. In the rendered DOM the shekel sign moves. A regular listing card printed `₪ 2,990,000` with the sign first, a new project card printed `6,767,100 ₪` with the sign last and `החל מ-` ("starting from") in front, and the project blurbs in JSON wrap the sign in RLM marks. The DOM fallback strips everything that is not a digit and keeps the integer. The source page lists no currency field anywhere; ILS is implied by `₪`.

Rental prices on the rent feed are monthly asking rents. `yad2_rent_stats.py` drops anything above 100,000 ILS from rent statistics, since Yad2 is free text at the source and an occasional sale price lands in a rent feed.

## Measured access: premium proxies, Radware, and three outcomes

Yad2 sits behind Radware bot management. Every request below used ScrapingBee's HTML API; the 25 credit figure is premium proxy plus JavaScript rendering, read from the `spb-cost` header.

| Request setup | Attempts | Usable | What came back otherwise | Credits each |
|---|---|---|---|---|
| `mode=auto`, `max_cost=25`, `country_code=il` | 1 | 0 | stopped at premium without JS, on the Radware page | 10 |
| Premium, no JS, `country_code=il` | 1 | 0 | Radware page | 10 |
| Premium + JS, `country_code=il`, feed pages | 4 | 0 | 3 Radware, 1 page with no feed | 25 |
| Premium + JS, `country_code=il`, item pages | 3 | 0 | Radware | 25 |
| Premium + JS, `country_code=il`, rent lobby and cars | 2 | lobby only | cars: Radware | 25 |
| Premium + JS, no country code, feed pages | 11 | 6 | 3 Radware, 2 pages with no feed | 25 |
| Premium + JS, no country code, item page | 1 | 0 | Radware | 25 |
| Premium + JS, no country code, cars | 1 | 0 | real page, no listings in it | 25 |

Three outcomes matter, and two of them are billed:

1. **A usable render.** Real page, listings present. Five of the six carried `__NEXT_DATA__`; one forsale render had the ad cards in the DOM but no `__NEXT_DATA__` script.
2. **The Radware page.** `<title>Radware Page</title>`, about 118 KB, served with HTTP 200 and `spb-initial-status-code: 200`. ScrapingBee counts it as a success and bills it.
3. **A page with no feed.** The real Yad2 page with header, filters and price inputs, but no listing cards and no `__NEXT_DATA__`. Also billed. Both Jerusalem area attempts ended this way.

`mode=auto` is not useful here, because it accepts the first 200, and the Radware page is a 200 at 10 credits. So the scripts request premium proxy with rendering directly and check the body themselves:

```python
def is_radware(html):
    return "<title>Radware Page</title>" in html[:3000] or (
        len(html) < 130_000 and "perfdrive" in html and "__NEXT_DATA__" not in html)

# inside fetch(): retry Radware and feed-less renders, at most max_attempts
if is_radware(body):
    ...                                   # log, sleep, try again
elif "__NEXT_DATA__" in body or 'data-testid="item-basic"' in body:
    return body, spent
```

Budget for that. In our runs a usable feed page cost 25 to 75 credits, with a mean of about 45. Counterintuitively, `country_code=il` did worse than no country code at all. Israeli IPs are what you would pick for an Israeli site, and on this day all of them got the challenge. ScrapingBee does not charge for its own HTTP 500 errors, so those are retried freely and separately from the Radware loop.

## The yad2 scraper fallback: reading the DOM by `data-testid`

When a render arrives without `__NEXT_DATA__` but with cards, `yad2_feed.py` parses the cards. Yad2's CSS class names are hashed per build (`item-data-content-module-scss-module__bupiUG__heading`), so the parser keys on `data-testid`, which is stable test markup. One card from the forsale feed, with class attributes and the two bidi marks around the floor number removed:

```html
<li data-testid="item-basic" data-nagish="feed-item-list-box">
  <a href="/realestate/item/tel-aviv-area/tf6lztsa?opened-from=feed&amp;component-type=main_feed&amp;spot=standard&amp;location=6">
    <div data-testid="ad-card-price">
      <span data-testid="ad-card-above-price"></span>
      <span data-testid="price">₪ 2,990,000</span>
    </div>
    <h2>
      <span data-testid="ad-card-address"><span data-testid="street-name">הביל"ויים 26</span></span>
      <span data-testid="item-info-line-1st">דירה, אזור הבילויים, רמת גן</span>
      <span data-testid="item-info-line-2nd">5 חדרים • קומה 2 • 120 מ״ר</span>
    </h2>
    <div data-testid="item-tags-box"><span>חניה</span><span>נוף פתוח לעיר</span><span>3 כיווני אוויר</span></div>
  </a>
</li>
```

The first info line is `property type, neighbourhood, city`, comma separated. The second is `rooms • floor • size`, and after `clean_he` three patterns read it: `([\d.]+)\s*חדרים`, `קומה\s*(-?\d+)` and `(\d+)\s*מ"ר`. The DOM gives fewer fields than the JSON: no coordinates, no agency, no `priceBeforeTag`, no image list. Records from this path carry `source="dom"` so you can tell them apart.

## Run it

```bash
export SCRAPINGBEE_API_KEY=your_key
pip install requests
python examples/yad2_feed.py --deal rent --region tel-aviv-area --pages 2 --json rent.json --csv rent.csv
```

Real output from 2026-10-29 (stderr lines included):

```
  attempt 1: Radware challenge page, 25 credits
page 1: 43 listings (43 new), 50 credits, {'total': 7892, 'totalPages': 198}
  attempt 1: Radware challenge page, 25 credits
  attempt 2: Radware challenge page, 25 credits
page 2: 43 listings (41 new), 75 credits, {'total': 7892, 'totalPages': 198}
g8fxclwp  4900 ILS  2 rooms  45 m2  apartment  Tel Aviv-Yafo  tags=[]
tj0hpnig  6500 ILS  3 rooms  100 m2  apartment  Holon  tags=[]
zrkow25y  9200 ILS  3 rooms  70 m2  apartment  Tel Aviv-Yafo  tags=[]
t84h5es1  3600 ILS  1 rooms  25 m2  apartment  Tel Aviv-Yafo  tags=[]
o2o8p8zd  5000 ILS  2 rooms  45 m2  apartment  Ramat Gan  tags=['rear facing property', 'open city view', 'bargain']
84 listings, 125 credits
```

Page 2 repeated two promoted `platinum` listings from page 1, which is why it reports 41 new out of 43; the crawler de-duplicates on `token`.

Options: `--deal rent|forsale`, `--region <slug>` (slugs seen on the site: `tel-aviv-area`, `center-and-sharon`, `jerusalem-area`, `coastal-north`, `north-and-valleys`), `--pages N`, `--max-attempts N` for the Radware loop.

## Rent per square metre in the Tel Aviv area

[`examples/yad2_rent_stats.py`](examples/yad2_rent_stats.py) reads that JSON and groups ILS per m² by city and by room count, then lists Yad2's own price cuts:

```
84 listings, 82 with a usable price and size

ILS per m2 by city
  Tel Aviv-Yafo          n=37  median  102.7 ILS/m2   mean  110.3
  Bat Yam                n=18  median   61.5 ILS/m2   mean   62.6
  Ramat Gan              n=12  median   82.5 ILS/m2   mean   83.9
  Holon                  n=11  median   69.9 ILS/m2   mean   74.6
  Givatayim              n=3   median  100.0 ILS/m2   mean   95.2
  Azor                   n=1   median   55.6 ILS/m2   mean   55.6

Price cuts (22 listings below their previous asking price)
  fnv4qcs8  12900 -> 11800 ILS  (-8.5%)  Tel Aviv-Yafo
  r9c32x69  11000 -> 9900 ILS  (-10.0%)  Tel Aviv-Yafo
  ybk5teu4  6990 -> 5990 ILS  (-14.3%)  Tel Aviv-Yafo
```

Two pages out of 198 is a sample of the newest and promoted listings, not the market. The "Tel Aviv area" region also covers Bat Yam, Holon, Ramat Gan, Givatayim and Azor, which is why they appear. For a real index, crawl all pages and keep the `price_before_ils` history across runs.

## Node.js

[`examples/yad2_feed.js`](examples/yad2_feed.js) is the same flow with Node 18's built in `fetch` and no dependencies, including the Radware check and a DOM fallback:

```bash
node examples/yad2_feed.js rent tel-aviv-area 3
```

```
{"token":"uel3k8t3","price_ils":4999,"rooms":3,"size_m2":78,"city_he":"בת ים","neighborhood_he":null,"url":"https://www.yad2.co.il/realestate/item/tel-aviv-area/uel3k8t3"}
{"token":"ocie0vza","price_ils":7000,"rooms":3,"size_m2":72,"city_he":"תל אביב יפו","neighborhood_he":"נווה שאנן","url":"https://www.yad2.co.il/realestate/item/tel-aviv-area/ocie0vza"}
43 listings on page 3 of 198, 7893 total, 25 credits
```

## What this repo does not cover yet

- **Cars.** `https://www.yad2.co.il/vehicles/cars` rendered once as a real page (title `רכבים למכירה`), but with only the header and navigation: no listing cards, no `__NEXT_DATA__`. A second attempt with `country_code=il` got the Radware page. No vehicle data was extracted, so there is no vehicle schema here.
- **Single listing pages.** All four attempts at `/realestate/item/...` got the Radware page. The feed JSON already carries price, size, rooms, floor, coordinates, tags and the image list, which covers most uses.
- **Regions other than Tel Aviv.** Jerusalem area was tried twice and both renders had no feed. The code takes any region slug; we only verified output for `tel-aviv-area` (rent pages 1 to 3, forsale page 1).
- **ScrapingBee's stealth proxy tier** was not part of these tests.

## Related ScrapingBee pages

Other classifieds and property scrapers: [real estate data API](https://www.scrapingbee.com/scrapers/real-estate-data-api/), [classified ads API](https://www.scrapingbee.com/scrapers/classified-api/), [Idealista API](https://www.scrapingbee.com/scrapers/idealista-api/), [Bayut API](https://www.scrapingbee.com/scrapers/bayut-api/), [PropertyGuru API](https://www.scrapingbee.com/scrapers/propertyguru-api/), [OLX API](https://www.scrapingbee.com/scrapers/olx-api/), [Zillow API](https://www.scrapingbee.com/scrapers/zillow-api/).

Documentation: [HTML API parameters and credit costs](https://www.scrapingbee.com/documentation/), [premium proxy country codes](https://www.scrapingbee.com/documentation/country_codes/), [JavaScript scenarios](https://www.scrapingbee.com/documentation/js-scenario/), [data extraction rules](https://www.scrapingbee.com/documentation/data-extraction/), [pricing](https://www.scrapingbee.com/pricing/). New accounts start with 1,000 free credits, roughly 20 to 40 Yad2 feed pages at the rates measured above.

## Scope

This reads public feed pages a visitor sees without signing in. Phone numbers, contact forms and saved searches on Yad2 sit behind a click or an account, and nothing here touches them; ScrapingBee's terms do not allow scraping with login credentials, so an account-only page is out of bounds for this API whatever the technique. Agency names appear in the feed. Private sellers appear only through the listing itself, and storing anything that identifies a person makes you responsible for it under Israeli privacy law. Yad2's own terms of use apply to the site.

## FAQ

**Is this the official Yad2 API?**
No. This repo does not use any Yad2 developer access. It reads the public feed pages, whose data sits in `__NEXT_DATA__`, through ScrapingBee.

**Why does my Yad2 scraper get a page titled "Radware Page"?**
That is Yad2's bot challenge. It comes back as HTTP 200, so check the body, not the status. Premium proxies with JavaScript rendering got past it on about half the feed attempts in our tests; plain requests never did.

**Should I use `country_code=il` for Yad2?**
In our tests it was worse: none of the 8 feed, listing and car page attempts with Israeli IPs returned listings, against 6 of 11 feed attempts without a country code. Re-test before you rely on either, since this kind of result changes.

**How do I get rid of invisible characters in Yad2 Hebrew text?**
Remove U+200E, U+200F and the U+202A to U+202E and U+2066 to U+2069 controls, and fold the maqaf (U+05BE) to a hyphen. `clean_he()` in `yad2_feed.py` does this.

**How many listings per page, and how many pages?**
43 (40 regular plus 3 promoted) on the Tel Aviv area rental feed, 198 pages for 7,892 listings on the day we tested.

## License

MIT. See [LICENSE](LICENSE).
