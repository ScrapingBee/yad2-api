// Yad2 feed page -> listings, Node 18+ (global fetch), no dependencies.
//
//   SCRAPINGBEE_API_KEY=... node yad2_feed.js rent tel-aviv-area 1
//
// Same contract as yad2_feed.py: premium proxy plus JavaScript rendering,
// a Radware check on every 200, and listings read from __NEXT_DATA__.

const API = "https://app.scrapingbee.com/api/v1/";
const KEY = process.env.SCRAPINGBEE_API_KEY;
if (!KEY) {
  console.error("Set SCRAPINGBEE_API_KEY first.");
  process.exit(1);
}

const [deal = "rent", region = "tel-aviv-area", page = "1"] = process.argv.slice(2);

// U+200E/U+200F and the isolate controls out, maqaf and dashes to "-",
// gershayim to a plain double quote.
const clean = (s) =>
  s == null
    ? null
    : String(s)
        .replace(/[\u200e\u200f\u061c\u202a-\u202e\u2066-\u2069]/g, "")
        .replace(/[\u05be\u2010-\u2014\u2212]/g, "-")
        .replace(/\u05f4/g, '"')
        .replace(/\u05f3/g, "'")
        .replace(/\s+/g, " ")
        .trim();

async function render(url, attempts = 3) {
  let spent = 0;
  for (let i = 1; i <= attempts; i++) {
    const qs = new URLSearchParams({ url, render_js: "true", premium_proxy: "true", wait: "3000" });
    const res = await fetch(`${API}?${qs}`, { headers: { Authorization: `Bearer ${KEY}` } });
    if (res.status === 500) continue; // not billed
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${(await res.text()).slice(0, 200)}`);
    spent += Number(res.headers.get("spb-cost") || 0);
    const html = await res.text();
    if (html.slice(0, 3000).includes("<title>Radware Page</title>")) {
      console.error(`attempt ${i}: Radware page, ${res.headers.get("spb-cost")} credits`);
    } else if (html.includes("__NEXT_DATA__") || html.includes('data-testid="item-basic"')) {
      return { html, spent };
    } else {
      console.error(`attempt ${i}: rendered without a feed, ${res.headers.get("spb-cost")} credits`);
    }
  }
  throw new Error(`no usable render after ${attempts} attempts, ${spent} credits`);
}

(async () => {
  const url = `https://www.yad2.co.il/realestate/${deal}/${region}` + (page === "1" ? "" : `?page=${page}`);
  const { html, spent } = await render(url);
  const m = html.match(/<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)<\/script>/);
  if (!m) {
    // Some renders arrive without the JSON. The cards are still in the DOM.
    const cards = html.match(/<li data-testid="item-basic"[\s\S]*?<\/li>/g) || [];
    const strip = (x) => clean((x || "").replace(/<[^>]+>/g, " "));
    for (const c of cards.slice(0, 5)) {
      const tok = (c.match(/href="\/realestate\/item\/[a-z-]+\/(\w+)/) || [])[1];
      const price = strip((c.match(/data-testid="price"[^>]*>([\s\S]*?)<\/span>/) || [])[1]);
      const line1 = strip((c.match(/data-testid="item-info-line-1st"[^>]*>([\s\S]*?)<\/span>/) || [])[1]);
      const line2 = strip((c.match(/data-testid="item-info-line-2nd"[^>]*>([\s\S]*?)<\/span>/) || [])[1]);
      console.log(JSON.stringify({ token: tok, price, line1, line2, source: "dom" }));
    }
    console.log(`${cards.length} cards from the DOM (no __NEXT_DATA__ in this render), ${spent} credits`);
    return;
  }
  const queries = JSON.parse(m[1]).props.pageProps.dehydratedState.queries;
  const feed = queries.find((q) => /^realestate-\w+-feed$/.test(q.queryKey[0]));
  const data = feed.state.data;
  const ads = [...(data.platinum || []), ...(data.yad2 || [])].filter((a) => a.token);
  const rows = ads.map((a) => ({
    token: a.token,
    price_ils: a.price ?? null,
    rooms: a.additionalDetails?.roomsCount ?? null,
    size_m2: a.additionalDetails?.squareMeter ?? null,
    city_he: clean(a.address?.city?.text),
    neighborhood_he: clean(a.address?.neighborhood?.text),
    url: `https://www.yad2.co.il/realestate/item/${region}/${a.token}`,
  }));
  for (const r of rows.slice(0, 5)) console.log(JSON.stringify(r));
  console.log(`${rows.length} listings on page ${page} of ${data.pagination?.totalPages}, ${data.pagination?.total} total, ${spent} credits`);
})().catch((e) => {
  console.error(e.message);
  process.exit(1);
});
