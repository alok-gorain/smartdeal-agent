"""Build SmartDeal's public sample dataset from free, openly licensed data.

Sources (see data/public/README.md for licences and attribution):
  1. PromptCloud "Flipkart Products" — 20,000 Flipkart listings crawled Dec 2015–Jun 2016
     (name, brand, category tree, MRP, selling price, rating). CC BY-SA 4.0.
  2. Zenodo record 17612521 "Flipkart Review Dataset" — 189,874 reviews of 812 products
     (name, price, rating). CC BY 4.0.

Neither source has price history, so this script:
  - cleans and de-duplicates products and maps them to SmartDeal categories;
  - adds rows: colour variants of some products, and offers at 1-3 more Indian stores per product;
  - generates a DUMMY dated price history for every offer (12 months: weekly noise, Indian
    sale-season dips, and some inflated-MRP "fake discount" items).

Everything generated is labelled synthetic. Run it with the raw files downloaded elsewhere:

  python -I data_pipeline/build_public_dataset.py --promptcloud PATH.csv --zenodo PATH.csv
"""

import argparse
import csv
import gzip
import hashlib
import json
import random
import re
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from statistics import mean

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))  # explicit, so the script also runs with python -I

from services.sale_calendar import events_between  # noqa: E402

OUT_DIR = BACKEND / "data_pipeline" / "data" / "public"
HISTORY_DAYS = 365

# ---------- categories ----------------------------------------------------------------

PROMPTCLOUD_CATEGORIES = {
    "Clothing": "fashion", "Sunglasses": "fashion", "Jewellery": "jewellery", "Footwear": "footwear",
    "Mobiles & Accessories": "mobile_accessories", "Automotive": "automotive",
    "Home Decor & Festive Needs": "home", "Home Furnishing": "home", "Home Improvement": "home",
    "Beauty and Personal Care": "beauty", "Kitchen & Dining": "kitchen", "Computers": "computer_accessories",
    "Watches": "watches", "Baby Care": "baby", "Tools & Hardware": "tools", "Toys & School Supplies": "toys",
    "Pens & Stationery": "stationery", "Bags, Wallets & Belts": "bags", "Furniture": "furniture",
    "Sports & Fitness": "sports", "Cameras & Accessories": "cameras", "Gaming": "gaming", "Pet Supplies": "pets",
    "Health & Personal Care Appliances": "appliances", "Home & Kitchen": "appliances",
    "Home Entertainment": "electronics",
}
# How many products to keep per category from the 20k PromptCloud rows (balanced sample)
PROMPTCLOUD_CAPS = {
    "fashion": 260, "jewellery": 120, "footwear": 140, "mobile_accessories": 90, "automotive": 60, "home": 160,
    "beauty": 110, "kitchen": 110, "computer_accessories": 80, "laptops": 10, "watches": 90, "baby": 60,
    "tools": 40, "toys": 60, "stationery": 40, "bags": 70, "furniture": 40, "sports": 60, "cameras": 40,
    "appliances": 50, "gaming": 20, "pets": 20, "electronics": 19,
}
# First match wins (Zenodo has no category column)
KEYWORD_CATEGORIES = [
    (r"\bipad\b|\btablet\b|\btab\b", "tablets"),
    (r"\blaptop|notebook pc|macbook", "laptops"),
    (r"ink cartridge|printer|toner|\bups\b|inverter|\bbattery\b", "electronics"),
    (r"rice cooker|dishwasher|place settings|water heater|sewing machine|juicer|blender", "appliances"),
    (r"blazer|\bsuit\b|sweatshirt|sweater|leggings|night ?suit|innerwear|socks", "fashion"),
    (r"nutrition|health drink|protein|antiseptic|sanitizer|thermometer|oximeter|\bbp monitor|first aid", "health"),
    (r"\bsmartphone|\bmobile phone|\b\d+\s?gb ram\b", "mobiles"),
    (r"charger|charging adapter|power ?bank|screen guard|tempered glass|back cover|phone case|usb cable|type-c cable", "mobile_accessories"),
    (r"\btv\b.*(stand|cabinet|unit|mount)|entertainment unit|wall shel", "furniture"),
    (r"smart ?tv|\bled tv|television|\btv\b", "tv"),
    (r"earphone|headphone|earbud|neckband|speaker|soundbar|\btws\b", "audio"),
    (r"camera|cctv|webcam", "cameras"),
    (r"keyboard|\bmouse\b|gaming|controller|joystick", "computer_accessories"),
    (r"chromecast|streaming|dongle|router|stabilizer|extension board|smart plug", "electronics"),
    (r"air cooler|\bfan\b|heater|geyser|water purifier|mixer|grinder|food processor|induction|kettle|microwave|"
     r"\boven\b|\biron\b|vacuum|air fryer|refrigerator|washing machine|chimney|sandwich maker|toaster|immersion", "appliances"),
    (r"trimmer|shaver|hair dryer|straightener|epilator", "beauty"),
    (r"serum|face wash|cream|shampoo|lipstick|perfume|deodorant|makeup|lotion|sunscreen|face care|skin", "beauty"),
    (r"\bsofa|chair|table|desk|wardrobe|\bbed\b|cabinet|shelf|rack|bookcase|stool|mattress", "furniture"),
    (r"bedsheet|curtain|cushion|pillow|blanket|door mat|\bmat\b|rug|carpet|towel|lamp|light|clock|plant|decor|"
     r"frame|diffuser|mop|bucket|broom", "home"),
    (r"dinner set|cookware|\bpan\b|kadai|tawa|bottle|glass|\bmug|container|lunch box|knife|cutlery|kitchen|"
     r"pressure cooker|gloves", "kitchen"),
    (r"\btoy|\brc\b|remote control car|helicopter|doll|puzzle|stunt car|building blocks", "toys"),
    (r"football|cricket|\bgym\b|yoga|fitness|cycle|badminton|dumbbell|skipping|athletic", "sports"),
    (r"shoe|sneaker|sandal|slipper|flip flop|\bboots?\b", "footwear"),
    (r"t-shirt|\bshirt|jeans|kurta|kurti|dupatta|saree|\bdress|\btop\b|trouser|jacket|hoodie|track ?pant|shorts", "fashion"),
    (r"smart ?watch|\bwatch", "watches"),
    (r"backpack|\bbag\b|wallet|handbag|trolley", "bags"),
    (r"\bpen\b|notebook|stationery|diary|marker", "stationery"),
    (r"\bpet\b|\bdog\b|\bcat\b", "pets"),
    (r"\bbaby|diaper|feeding", "baby"),
    (r"helmet|\bcar\b|bike|motorcycle", "automotive"),
]

# Stores that sell each category (Flipkart is always included: both sources are Flipkart data)
STORE_POOLS = {
    "fashion": ["myntra", "ajio", "amazon", "tata_cliq"], "footwear": ["myntra", "ajio", "amazon", "tata_cliq"],
    "jewellery": ["amazon", "myntra", "ajio", "tata_cliq"], "watches": ["amazon", "myntra", "tata_cliq", "ajio"],
    "bags": ["myntra", "amazon", "ajio"], "beauty": ["nykaa", "amazon", "myntra", "tata_cliq"],
    "mobiles": ["amazon", "croma", "reliance_digital", "vijay_sales"],
    "laptops": ["amazon", "croma", "reliance_digital", "vijay_sales"],
    "tv": ["amazon", "croma", "reliance_digital", "vijay_sales"],
    "audio": ["amazon", "croma", "reliance_digital", "tata_cliq"],
    "cameras": ["amazon", "croma", "reliance_digital"], "gaming": ["amazon", "croma", "reliance_digital"],
    "electronics": ["amazon", "croma", "reliance_digital"],
    "mobile_accessories": ["amazon", "croma", "jiomart"], "computer_accessories": ["amazon", "croma", "reliance_digital"],
    "appliances": ["amazon", "croma", "reliance_digital", "jiomart"],
    "kitchen": ["amazon", "jiomart", "pepperfry"], "home": ["amazon", "pepperfry", "jiomart"],
    "furniture": ["pepperfry", "amazon"], "baby": ["firstcry", "amazon", "jiomart"],
    "toys": ["firstcry", "amazon", "jiomart"], "sports": ["decathlon", "amazon"],
    "automotive": ["amazon", "jiomart"], "tools": ["amazon", "jiomart"], "stationery": ["amazon", "jiomart"],
    "pets": ["amazon", "jiomart"],
    "tablets": ["amazon", "croma", "reliance_digital", "vijay_sales"],
    "health": ["amazon", "jiomart", "nykaa"],
}
DELIVERY = {
    "flipkart": "2–3 days", "amazon": "Prime: 1–2 days", "myntra": "3–4 days", "ajio": "4–6 days",
    "tata_cliq": "4–6 days", "nykaa": "3–5 days", "croma": "2–4 days / store pickup",
    "reliance_digital": "3–5 days / store pickup", "vijay_sales": "3–5 days", "jiomart": "2–4 days",
    "pepperfry": "5–7 days", "firstcry": "3–5 days", "decathlon": "2–4 days",
}
COLOURS = ["Black", "Navy Blue", "Grey", "Maroon", "Olive Green", "White", "Beige", "Teal", "Mustard", "Pink"]
COLOUR_WORDS = re.compile(r"\b(black|white|blue|red|green|grey|gray|silver|gold|pink|purple|yellow|orange|beige|"
                          r"brown|navy|maroon|teal|olive|multicolor|multicolour)\b", re.I)
VARIANT_CATEGORIES = {"fashion", "footwear", "bags", "watches", "home", "kitchen", "furniture", "jewellery"}


def fmt(value) -> str:
    """379 instead of 379.0 in the CSVs."""
    if value is None or value == "":
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def key_for(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


def rnd(*parts) -> random.Random:
    """Deterministic RNG per item, so rebuilding gives the same dataset."""
    return random.Random(int(key_for(*map(str, parts)), 16))


def retail_round(p: float) -> float:
    """Indian retail style: ₹379, ₹1,299, ₹24,999."""
    if p >= 1000:
        return float(max(round(p / 100) * 100 - 1, 1))
    if p >= 100:
        return float(max(round(p / 10) * 10 - 1, 1))
    return float(max(round(p), 1))


def fix_mojibake(text: str) -> str:
    """Undo double-encoded UTF-8 ("Ã¢Â®" -> "®", "Â°" -> "°") where the source text was mangled."""
    for _ in range(2):
        if not re.search("[ÃÂ]", text):
            break
        repaired = None
        for codec in ("cp1252", "latin-1"):
            try:
                repaired = text.encode(codec).decode("utf-8")
                break
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
        if repaired is None:
            break
        text = repaired
    text = re.sub(r"â(?=[®™©])", "", text)  # leftover of a triple-encoded symbol
    return text.replace("Â", "")


def clean_name(text: str) -> str:
    text = fix_mojibake(text)
    text = text.replace("�", " ").replace("\xa0", " ")
    text = re.sub(r"\?(?=\s|\(|$)", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"\(\s+", "(", text)


def parse_money(text: str | None) -> float | None:
    if not text:
        return None
    m = re.search(r"\d[\d,]*(?:\.\d+)?", text)
    if not m:
        return None
    value = float(m.group(0).replace(",", ""))
    return value if value > 0 else None


def categorize(name: str) -> str:
    low = name.lower()
    for pattern, category in KEYWORD_CATEGORIES:
        if re.search(pattern, low):
            return category
    return "home"


# ---------- sources -------------------------------------------------------------------

def load_promptcloud(path: Path) -> list[dict]:
    csv.field_size_limit(10**8)
    seen, picked = set(), defaultdict(list)
    with open(path, encoding="utf-8", errors="replace", newline="") as f:
        for r in csv.DictReader(f):
            name = clean_name(r["product_name"])
            mrp, price = parse_money(r["retail_price"]), parse_money(r["discounted_price"])
            if not name or not mrp or not price or price > mrp or not (49 <= price <= 300000):
                continue
            norm = re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()
            if norm in seen:
                continue
            tree = [p.strip() for p in re.sub(r'^\["|"\]$', "", r["product_category_tree"]).split(">>")]
            category = PROMPTCLOUD_CATEGORIES.get(tree[0])
            if category is None:
                continue
            if category == "computer_accessories" and len(tree) > 1 and tree[1] == "Laptops":
                category = "laptops"
            seen.add(norm)
            rating = float(r["product_rating"]) if re.match(r"^\d(\.\d+)?$", r["product_rating"] or "") else None
            brand = r["brand"].strip() or name.split()[0]
            picked[category].append({
                "name": name, "brand": brand[:80], "category": category,
                "subcategory": tree[1] if len(tree) > 1 else "", "mrp": mrp, "price": price,
                "rating": rating, "rating_count": None, "dataset": "promptcloud", "source_ref": r["uniq_id"],
                "_priority": (rating is None, not r["brand"].strip()),
            })
    rows = []
    for category, items in picked.items():
        rng = random.Random(f"cap-{category}")
        rng.shuffle(items)
        items.sort(key=lambda x: x["_priority"])  # rated and branded first (stable after shuffle)
        rows.extend(items[: PROMPTCLOUD_CAPS.get(category, 30)])
    for row in rows:
        row.pop("_priority")
    return rows


def load_zenodo(path: Path) -> list[dict]:
    reviews = defaultdict(lambda: {"prices": [], "rates": []})
    with open(path, encoding="utf-8", errors="replace", newline="") as f:
        for r in csv.DictReader(f):
            name = clean_name(r.get("ProductName") or "")
            price = parse_money(r.get("Price"))
            if not name or not price:
                continue
            reviews[name]["prices"].append(price)
            if (r.get("Rate") or "").strip().isdigit():
                reviews[name]["rates"].append(int(r["Rate"]))
    rows = []
    for name, d in reviews.items():
        price = sorted(d["prices"])[len(d["prices"]) // 2]
        if not (49 <= price <= 300000):
            continue
        rng = rnd("zenodo-mrp", name)
        # The source has no MRP; most Flipkart listings show one above the price
        mrp = retail_round(price * rng.choice([1.0, 1.15, 1.3, 1.5, 1.8, 2.2]))
        rows.append({
            "name": name, "brand": name.split()[0].strip(",.()")[:80], "category": categorize(name),
            "subcategory": "", "mrp": max(mrp, price), "price": price,
            "rating": round(mean(d["rates"]), 1) if d["rates"] else None,
            "rating_count": len(d["rates"]) or None, "dataset": "zenodo", "source_ref": key_for("zenodo", name),
        })
    return rows


# ---------- augmentation: more rows -----------------------------------------------------

def add_colour_variants(products: list[dict]) -> list[dict]:
    """About 1 in 5 products in colour-friendly categories gets one or two colour variants."""
    variants = []
    for p in products:
        if p["category"] not in VARIANT_CATEGORIES or COLOUR_WORDS.search(p["name"]):
            continue
        rng = rnd("variant", p["product_key"])
        if rng.random() > 0.2:
            continue
        for colour in rng.sample(COLOURS, rng.choice([1, 2])):
            price = retail_round(p["price"] * rng.uniform(0.97, 1.05))
            variants.append(p | {
                "product_key": key_for(p["product_key"], colour),
                "name": f"{p['name']} ({colour})", "price": price, "mrp": max(p["mrp"], price),
                "variant_of": p["product_key"], "is_augmented": 1,
            })
    return variants


def make_listings(p: dict) -> list[dict]:
    """Flipkart (from the source data) plus 1-3 other stores at nearby prices."""
    rng = rnd("stores", p["product_key"])
    pool = STORE_POOLS.get(p["category"], ["amazon", "jiomart"])
    others = rng.sample(pool, k=min(len(pool), rng.choice([1, 2, 2, 3])))
    listings = [{"store": "flipkart", "price": p["price"], "mrp": p["mrp"]}]
    for store in others:
        price = retail_round(p["price"] * rng.uniform(0.93, 1.10))
        listings.append({"store": store, "price": price, "mrp": max(p["mrp"], price)})
    for listing in listings:
        rating = p["rating"]
        listing["rating"] = round(min(5.0, max(1.0, rating + rng.uniform(-0.2, 0.1))), 1) if rating else None
        listing["review_count"] = int(p["rating_count"] * rng.uniform(0.2, 1.0)) if p["rating_count"] else None
        listing["delivery_info"] = DELIVERY.get(listing["store"])
    return listings


# ---------- augmentation: dummy dated price history -------------------------------------

def pick_pattern(p: dict) -> str:
    """Price story for a product's history. Big "% off MRP" listings are a mix of fake discounts
    (always sold at that price) and real recent drops, so the discount check has real work to do."""
    rng = rnd("pattern", p["product_key"])
    claimed = (p["mrp"] - p["price"]) / p["mrp"] if p["mrp"] else 0
    roll = rng.random()
    if claimed >= 0.25:
        return ("always_discounted" if roll < 0.35 else "genuine_drop" if roll < 0.70
                else "minor_drop" if roll < 0.90 else "price_up")
    return ("seasonal" if roll < 0.40 else "genuine_drop" if roll < 0.65 else "minor_drop" if roll < 0.80
            else "price_up" if roll < 0.90 else "steady")


# Usual price before the recent change, relative to today's price
USUAL_FACTOR = {
    "genuine_drop": (1.15, 1.30),  # real deal now: 13-23% below usual
    "minor_drop": (1.06, 1.11),    # small real saving
    "price_up": (0.86, 0.93),      # price went up recently
    "always_discounted": (0.99, 1.03),
    "seasonal": (0.98, 1.04),
    "steady": (0.99, 1.02),
}


def daily_prices(p: dict, listing: dict, today: date) -> dict[date, float]:
    """A year of daily prices that ends at today's listed price."""
    rng = rnd("history", p["product_key"], listing["store"])
    pattern = pick_pattern(p)
    current = listing["price"]
    usual = current * rng.uniform(*USUAL_FACTOR[pattern])
    drop_days = rng.randint(3, 12)  # the recent price change happened 3-12 days ago
    start = today - timedelta(days=HISTORY_DAYS)
    events = {e.key: e for e in events_between(start, today)}
    depth = {k: rng.uniform(0.08, 0.25) for k in events}
    if p["category"] in ("fashion", "footwear") and "eors" in depth:
        depth["eors"] = rng.uniform(0.25, 0.4)
    prices: dict[date, float] = {}
    level = 1.0
    for i in range(HISTORY_DAYS, -1, -1):
        day = today - timedelta(days=i)
        if i % 7 == 0:
            level = 1 + rng.uniform(-0.025, 0.025) * (0.3 if pattern == "steady" else 1)
        price = usual * level
        if pattern in ("genuine_drop", "minor_drop", "price_up") and i <= drop_days:
            price = current * (1 + rng.uniform(-0.01, 0.01))
        event = next((e for e in events.values() if e.start <= day <= e.end), None)
        if event and pattern != "steady":
            d = depth[event.key]
            if event.key == "prime_day" and listing["store"] != "amazon":
                d = 0.03
            price *= 1 - d
        prices[day] = retail_round(price)
    prices[today] = current
    return prices


def sample_dates(today: date) -> list[date]:
    """Weekly for a year (evenly spaced, so a 90-day median isn't skewed), plus each sale's first day."""
    start = today - timedelta(days=HISTORY_DAYS)
    dates = {today - timedelta(days=d) for d in range(0, HISTORY_DAYS + 1, 7)}
    dates |= {e.start for e in events_between(start, today)}
    return sorted(d for d in dates if start <= d <= today)


# ---------- main --------------------------------------------------------------------------

def build(promptcloud: Path, zenodo: Path, out: Path, today: date) -> dict:
    products = load_promptcloud(promptcloud) + load_zenodo(zenodo)
    for p in products:
        p["product_key"] = key_for(p["dataset"], p["source_ref"])
        p.setdefault("variant_of", "")
        p.setdefault("is_augmented", 0)
    variants = add_colour_variants(products)
    products += variants

    out.mkdir(parents=True, exist_ok=True)
    dates = sample_dates(today)
    n_listings = n_points = 0
    product_cols = ["product_key", "name", "brand", "category", "subcategory", "mrp", "price", "rating",
                    "rating_count", "dataset", "source_ref", "variant_of", "is_augmented"]
    listing_cols = ["product_key", "store", "price", "mrp", "rating", "review_count", "delivery_info"]
    with open(out / "products.csv", "w", newline="", encoding="utf-8") as fp, \
         open(out / "listings.csv", "w", newline="", encoding="utf-8") as fl, \
         gzip.open(out / "price_history.csv.gz", "wt", newline="", encoding="utf-8") as fh:
        wp, wl, wh = csv.writer(fp), csv.writer(fl), csv.writer(fh)
        wp.writerow(product_cols)
        wl.writerow(listing_cols)
        wh.writerow(["date", "product_key", "store", "price", "mrp"])
        for p in products:
            wp.writerow([fmt(p.get(c)) for c in product_cols])
            for listing in make_listings(p):
                n_listings += 1
                wl.writerow([p["product_key"]] + [fmt(listing.get(c)) for c in listing_cols[1:]])
                daily = daily_prices(p, listing, today)
                for d in dates:
                    wh.writerow([d.isoformat(), p["product_key"], listing["store"], fmt(daily[d]), fmt(listing["mrp"])])
                    n_points += 1

    by_category = defaultdict(int)
    for p in products:
        by_category[p["category"]] += 1
    stats = {
        "built_on": today.isoformat(),
        "products": len(products),
        "from_promptcloud": sum(p["dataset"] == "promptcloud" and not p["is_augmented"] for p in products),
        "from_zenodo": sum(p["dataset"] == "zenodo" and not p["is_augmented"] for p in products),
        "colour_variants_added": len(variants),
        "store_listings": n_listings,
        "price_history_rows": n_points,
        "history_dates_per_listing": len(dates),
        "categories": dict(sorted(by_category.items(), key=lambda x: -x[1])),
    }
    (out / "stats.json").write_text(json.dumps(stats, indent=2) + "\n")
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--promptcloud", type=Path, required=True, help="flipkart_com-ecommerce_sample.csv")
    parser.add_argument("--zenodo", type=Path, required=True, help="flipkart_product.csv from Zenodo 17612521")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--today", type=date.fromisoformat, default=date.today(),
                        help="last day of the dummy history (the loader shifts dates to the load day anyway)")
    args = parser.parse_args()
    print(json.dumps(build(args.promptcloud, args.zenodo, args.out, args.today), indent=2))


if __name__ == "__main__":
    main()
