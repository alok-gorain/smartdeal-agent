from datetime import date
from types import SimpleNamespace

import pytest

from scrapers import amazon_scraper, myntra_scraper
from scrapers.http import parse_price
from services.coupon_service import compute_saving
from services.discount_analyzer import classify
from services.platforms.amazon import parse_paapi_items, sign_request
from services.platforms.base import Offer, platform_from_source
from services.platforms.catalog import query_coverage
from services.product_matcher import group_offers, match_score
from services.sale_calendar import event_on, events_for_year, upcoming_events


# ---------- product matching ----------------------------------------------------

def test_same_product_different_titles_match():
    assert match_score("Apple iPhone 16 (Black, 128 GB)", "Apple iPhone 16 128GB Black") >= 88


@pytest.mark.parametrize(
    "a,b",
    [
        ("Apple iPhone 16 128GB Black", "Apple iPhone 16 256GB Black"),  # storage
        ("Apple iPhone 16 128GB Black", "Apple iPhone 16 Pro 128GB Black"),  # tier word
        ("Apple iPhone 16", "Apple iPhone 16e"),  # suffixed model number
        ("Apple iPhone 15 (Black, 128 GB)", "Apple iPhone 16 (Black, 128 GB)"),  # model number
        ("OnePlus 12 5G 12GB RAM 256GB", "OnePlus 12R 5G 12GB RAM 256GB"),
        ("Samsung 55 inch Crystal 4K TV", "Samsung 43 inch Crystal 4K TV"),  # size
    ],
)
def test_variants_do_not_match(a, b):
    assert match_score(a, b) == 0


def test_colour_does_not_split_a_product():
    assert match_score("Apple iPhone 16 128GB Teal", "Apple iPhone 16 (Black, 128 GB)") >= 88
    # units are not mistaken for model numbers
    assert match_score("Redmi Note 13 Pro 5G 8GB RAM 256GB 200MP", "Redmi Note 13 Pro 5G (8 GB RAM, 256 GB)") > 0


def test_accessories_are_not_the_product():
    assert match_score("Samsung Galaxy S24 FE 5G 8GB 128GB", "Spigen Back Cover for Samsung Galaxy S24 FE") == 0
    for title in ["Sony WH-1000XM5 Custom Skin", "WC ShellZ XM5 Headphone Covers for Sony WH1000XM5",
                  "WC SweatZ XM5 Earpad Sweat Covers for Sony WH1000XM5"]:
        assert match_score("Sony WH-1000XM5 Wireless Headphones", title) == 0, title
    # ...but products that merely mention an included case/cable still match
    assert match_score("Apple AirPods Pro 2 with MagSafe Charging Case", "Apple AirPods Pro 2 MagSafe Charging Case USB-C") > 0


async def test_price_outliers_split_out():
    offers = [
        Offer(platform="flipkart", name="Samsung Galaxy S24 FE 5G 128GB", price=39999),
        Offer(platform="amazon", name="Samsung Galaxy S24 FE 5G 128GB", price=41999),
        Offer(platform="jiomart", name="Samsung Galaxy S24 FE 5G 128GB", price=199),  # mislisted item
    ]
    groups = await group_offers(offers, use_llm=False)
    assert len(groups) == 1  # the mislisted item is dropped
    assert {o.platform for o in groups[0].offers} == {"flipkart", "amazon"}


@pytest.mark.parametrize(
    "query,title,keep",
    [
        ("Sony WH 1000XM5 headphones", "Sony WH-1000XM5 Wireless Noise Cancelling Headphones", True),
        ("Sony WH 1000XM5 headphones", "Sony WH1000XM5/B Headphones", True),
        ("Sony WH 1000XM5 headphones", "Nike Zoom Vomero 5 Men's", False),
        ("iphone 16 128gb", "Apple iPhone 15 128GB", False),
        ("pixel 9", "Google Pixel 9 Pro XL", True),
        ("ANC earbuds", "boAt Airdopes 141 ANC TWS", True),  # generic search: no model filter
        ("Samsung 55 inch 4K TV", 'Samsung 55" Crystal 4K UHD Smart TV', True),
    ],
)
def test_model_relevance_filter(query, title, keep):
    from services.search_service import is_relevant

    assert is_relevant(title, query) is keep


@pytest.mark.parametrize(
    "query,title,keep",
    [
        ("ANC earbuds", "Mivi DuoPods Echo New Launch Ai-enc", False),  # ENC is not ANC
        ("ANC earbuds", "boAt Airdopes 91 with ENC Noise Cancellation", False),
        ("ANC earbuds", "JBL Tune 230NC TWS Earbuds", True),
        ("ANC earbuds", "Sony WF-1000XM5 Wireless Noise Cancelling Earbuds", True),
        ("5G phone under 15000", "Redmi 13C 4G", False),
        ("5G phone under 15000", "iQOO Z9 5G (8GB, 128GB)", True),  # 15000 is a budget, not a model
        ("earbuds", "Mivi DuoPods Echo New Launch Ai-enc", True),  # no feature asked for
    ],
)
def test_required_features_filter(query, title, keep):
    from services.search_service import is_relevant

    assert is_relevant(title, query) is keep


async def test_group_checks_every_member():
    # A generic title must not let two different storage variants into one group
    offers = [
        Offer(platform="amazon", name="Apple iPhone 16", price=76990),
        Offer(platform="croma", name="Apple iPhone 16 128GB Black", price=69900),
        Offer(platform="jiomart", name="Apple iPhone 16 256GB Black", price=79900),
    ]
    groups = await group_offers(offers, use_llm=False)
    assert len(groups) == 2
    assert groups[0].name == "Apple iPhone 16 128GB Black"  # most informative title wins


async def test_group_offers_keeps_one_offer_per_store():
    offers = [
        Offer(platform="amazon", name="OnePlus 12 5G 12GB RAM 256GB Flowy Emerald", price=52999),
        Offer(platform="flipkart", name="OnePlus 12 (Flowy Emerald, 256 GB) (12 GB RAM)", price=51999),
        Offer(platform="amazon", name="OnePlus 12 5G 12GB RAM 256GB Flowy Emerald", price=51500),
        Offer(platform="amazon", name="OnePlus 12R 8GB RAM 128GB Iron Gray", price=39999),
    ]
    groups = await group_offers(offers, use_llm=False)
    assert len(groups) == 2
    main = groups[0].to_dict()
    assert {o["platform"] for o in main["offers"]} == {"amazon", "flipkart"}
    assert main["best_price"] == 51500


async def test_demo_and_live_offers_are_never_grouped():
    offers = [
        Offer(platform="amazon", name="Apple iPhone 16 128GB Black", price=69900, source="demo", product_id=1),
        Offer(platform="croma", name="Apple iPhone 16 128GB Black", price=71900, source="live"),
    ]
    groups = await group_offers(offers, use_llm=False)
    assert len(groups) == 2
    assert groups[0].is_demo and not groups[1].is_demo


def test_google_shopping_skips_refurbished():
    from services.platforms.google_shopping import parse_shopping_results

    data = {"shopping_results": [
        {"title": "Apple iPhone 16 128GB Black", "source": "Reliance Digital", "extracted_price": 71900},
        {"title": "Apple iPhone 16 128GB Black (Renewed)", "source": "Amazon.in", "extracted_price": 52000},
        {"title": "Apple iPhone 16 128GB", "source": "Cashify", "extracted_price": 50000, "second_hand_condition": "used"},
    ]}
    offers = parse_shopping_results(data, 10)
    assert [o.platform for o in offers] == ["reliance_digital"]


def test_catalog_query_needs_exact_model_numbers():
    hay = set("google pixel 9 12gb 256gb obsidian".split())
    assert query_coverage(["pixel", "9"], hay) == 1.0
    assert query_coverage(["pixel", "8"], hay) == 0.5
    assert query_coverage(["pixle", "9"], hay) == 1.0  # typo tolerance on words


# ---------- fake discounts ------------------------------------------------------

def test_inflated_mrp_is_fake():
    verdict, actual, claimed = classify(price=19999, mrp=34999, median_price=19999)
    assert verdict == "FAKE" and actual == 0 and claimed > 40


def test_real_drop_is_genuine():
    assert classify(price=44999, mrp=64999, median_price=52999)[0] == "GENUINE"


def test_small_drop_is_minor():
    assert classify(price=49999, mrp=64999, median_price=52999)[0] == "MINOR"


def test_no_claim_no_drop_is_regular():
    assert classify(price=999, mrp=1049, median_price=999)[0] == "REGULAR"


# ---------- sale calendar -------------------------------------------------------

def test_sale_calendar_2026():
    keys = [e.key for e in events_for_year(2026)]
    assert keys[0] == "republic_day" and "diwali" in keys and "black_friday" in keys
    assert event_on(date(2026, 7, 13)).key == "prime_day"
    assert event_on(date(2026, 11, 27)).key == "black_friday"  # 4th Friday of Nov 2026
    assert upcoming_events(date(2026, 11, 22))[0].key == "black_friday"


# ---------- coupons -------------------------------------------------------------

def _coupon(**kw):
    base = dict(discount_type="percent", discount_value=10, min_order_value=None, max_discount=None)
    return SimpleNamespace(**(base | kw))


def test_coupon_cap_and_minimum():
    assert compute_saving(_coupon(max_discount=1500), 30000) == 1500
    assert compute_saving(_coupon(min_order_value=5000), 4000) == 0
    assert compute_saving(_coupon(discount_type="flat", discount_value=2000), 1500) == 1500


# ---------- parsers -------------------------------------------------------------

def test_parse_price():
    assert parse_price("₹1,29,999.00") == 129999.0
    assert parse_price("M.R.P: ₹ 4,490") == 4490.0
    assert parse_price(None) is None


def test_platform_from_source():
    assert platform_from_source("Reliance Digital") == "reliance_digital"
    assert platform_from_source("Croma") == "croma"
    assert platform_from_source("Some New Store.in") == "some_new_store"
    assert platform_from_source("Digital Global") == "digital_global"  # whole words: no "lg" match


@pytest.mark.parametrize(
    "source,trusted",
    [("Amazon.in", True), ("Sangeetha Mobiles", True), ("iCrescent Apple Authorised Store", True),
     ("Meesho", False), ("Snapdeal", False), ("Some Gadget Shop", False)],
)
def test_store_trust(source, trusted):
    assert Offer(platform=platform_from_source(source), name="x", price=1).trusted is trusted


def test_filter_puts_trusted_products_first():
    from services.search_service import filter_groups

    groups = [
        {"name": "Clone buds", "offers": [{"platform": "meesho", "price": 477}], "trusted": False},
        {"name": "Real buds", "offers": [{"platform": "amazon", "price": 2999}], "trusted": True},
    ]
    assert [g["name"] for g in filter_groups(groups)] == ["Real buds", "Clone buds"]


def test_amazon_search_html():
    html = """
    <div data-component-type="s-search-result" data-asin="B0TEST1234">
      <h2><a href="/Sony-WF-1000XM5/dp/B0TEST1234/ref=sr_1_1"><span>Sony WF-1000XM5 Earbuds</span></a></h2>
      <span class="a-price"><span class="a-offscreen">₹19,990</span></span>
      <span class="a-price a-text-price"><span class="a-offscreen">₹29,990</span></span>
      <span class="a-icon-alt">4.4 out of 5 stars</span>
      <img class="s-image" src="https://m.media-amazon.com/x.jpg">
    </div>"""
    [offer] = amazon_scraper.parse_search_html(html)
    assert offer.price == 19990 and offer.mrp == 29990 and offer.rating == 4.4
    assert offer.url == "https://www.amazon.in/Sony-WF-1000XM5/dp/B0TEST1234"


def test_myntra_embedded_json():
    html = """<script>window.__myx = {"searchData":{"results":{"products":[
      {"productId":123,"productName":"Roadster Men Black T-shirt","brand":"Roadster","price":399,"mrp":799,
       "rating":4.13,"ratingCount":1200,"searchImage":"https://img/x.jpg","landingPageUrl":"tshirts/roadster/123/buy"}]}}}</script>"""
    [offer] = myntra_scraper.parse_search_html(html)
    assert offer.price == 399 and offer.rating == 4.1 and offer.url.endswith("/123/buy")


def test_paapi_parse_and_signature():
    data = {"SearchResult": {"Items": [{
        "ASIN": "B0X", "DetailPageURL": "https://www.amazon.in/dp/B0X",
        "ItemInfo": {"Title": {"DisplayValue": "Test Phone"}},
        "Offers": {"Listings": [{"Price": {"Amount": 999.0}, "SavingBasis": {"Amount": 1499.0}}]},
    }]}}
    [offer] = parse_paapi_items(data)
    assert offer.price == 999 and offer.mrp == 1499
    headers = sign_request("{}", "AKIDEXAMPLE", "secret")
    assert headers["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/")


@pytest.mark.parametrize(
    "a,b",
    [
        ("Sony WH-1000XM5 Wireless Headphones", "Sony WF-1000XM5 Wireless Earbuds"),
        ("Samsung Galaxy S24 5G 256GB", "Samsung Galaxy S23 5G 256GB"),
        ("Apple MacBook Air M3 13-inch 8GB 256GB", "Apple MacBook Air M2 13-inch 8GB 256GB"),
    ],
)
def test_different_model_codes_never_match(a, b):
    assert match_score(a, b) == 0


def test_model_code_written_with_space_or_hyphen():
    from services.search_service import is_relevant

    assert match_score("Sony WH-1000XM5 Wireless Headphones", "Sony WH1000XM5/B Noise Cancelling Headphones") > 0
    assert not is_relevant("Sony WF-1000XM5 Wireless Earbuds", "Sony WH 1000XM5")
    assert is_relevant("Sony WH1000XM5/B Headphones", "Sony WH 1000XM5")


async def test_wrong_listing_on_a_stored_product_is_split_off():
    offers = [
        Offer(platform="amazon", name="Sony WH-1000XM5 Wireless Headphones", price=26990, product_id=7, via="catalog"),
        Offer(platform="croma", name="Sony WF-1000XM5 Wireless Earbuds", price=19990, product_id=7, via="catalog"),
    ]
    groups = await group_offers(offers, use_llm=False)
    assert len(groups) == 2  # the earbuds listing no longer rides along with the headphones


def test_price_above_usual_without_a_claim_is_not_fake():
    assert classify(price=55000, mrp=None, median_price=48000)[0] == "HIGH"
    assert classify(price=52000, mrp=54000, median_price=48000)[0] == "HIGH"  # small claim, still above usual
    assert classify(price=52000, mrp=99999, median_price=48000)[0] == "FAKE"  # big claimed discount that isn't real


def test_sample_products_keep_some_slots_after_live_results():
    from services.search_service import pick_results

    live = [{"name": f"live {i}", "is_demo": False} for i in range(10)]
    demo = [{"name": f"demo {i}", "is_demo": True} for i in range(5)]
    picked = pick_results(live + demo, 8)
    assert [g["is_demo"] for g in picked] == [False] * 6 + [True] * 2  # live first, 2 sample slots
    assert pick_results(demo, 8) == demo  # quick-search / no-key mode: seeded catalog results
