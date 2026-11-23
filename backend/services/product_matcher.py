"""Match the same product across stores.

Order of checks (cheapest first):
1. Variant attributes (model number, storage, RAM, screen size, tier words like Pro/Max).
   If they conflict, the products are different, whatever the title similarity.
   Colour is ignored: the same phone in black and teal costs the same.
2. rapidfuzz token-set similarity on normalised titles.
3. Gemini, only for the ambiguous middle band, batched into one call.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache

from rapidfuzz import fuzz

from core.config import settings
from services.platforms.base import Offer

logger = logging.getLogger(__name__)

SAME_THRESHOLD = 88
AMBIGUOUS_THRESHOLD = 72

COLORS = {
    "black", "white", "blue", "red", "green", "grey", "gray", "silver", "gold", "pink", "purple",
    "yellow", "orange", "beige", "brown", "navy", "titanium", "graphite", "midnight", "starlight",
    "teal", "ultramarine", "cream", "lavender", "mint", "olive", "maroon", "charcoal", "violet",
}
# Model-tier words: "iPhone 16" and "iPhone 16 Pro" are different products, so these must match exactly
VARIANT_WORDS = {"pro", "max", "plus", "ultra", "lite", "mini", "fe", "neo", "prime", "air", "slim"}
# Connectivity is often left out of titles, so it only conflicts when both titles state it
CONNECTIVITY_WORDS = {"5g", "4g", "lte", "wifi", "cellular"}
FILLER = {
    "with", "and", "for", "the", "new", "latest", "edition", "smartphone", "mobile", "phone", "unlocked",
    "inch", "inches", "cm", "india", "official", "warranty", "by", "of", "in", "a", "an",
}

_STORAGE_RE = re.compile(r"(\d+)\s*(gb|tb)\b")
_RAM_RE = re.compile(r"(\d+)\s*gb\s*ram|ram\s*(\d+)\s*gb")
_SIZE_RE = re.compile(r"(\d{2}(?:\.\d)?)\s*(?:\"|inch|inches|in\b|-inch)")
_NUMBER_RE = re.compile(r"^\d{1,4}$")
# Accessories sold "for" a product: never the same item as the product itself
ACCESSORY_RE = re.compile(
    r"\b(back cover|flip cover|book cover|phone cover|mobile cover|case cover|cover case|"
    r"silicone (?:case|cover)|protective (?:case|cover)|bumper|armou?r case|rugged case|clear case|"
    r"(?:covers?|cases?|skins?|pouch(?:es)?|chargers?|cables?|adapters?|straps?|bands?|holders?|mounts?|stands?) for|"
    r"tempered glass|screen guard|screen protector|lens protector|camera protector|privacy glass|"
    r"skins|custom skin|vinyl skin|skin sticker|decal|ear ?pads?|ear cushions?|replacement pads|sweat covers?|"
    r"carrying case|carry case|hard case|travel case|"
    r"compatible with|replacement)\b",
    re.I,
)
# Model numbers with a letter suffix: "16e", "12r", "2a", "7t" (not units like "128gb", "5g", "4k", "45w")
_SUFFIX_MODEL_RE = re.compile(r"^\d+[a-z]{1,2}$")
_UNIT_SUFFIX_RE = re.compile(
    r"^\d+(gb|tb|mb|g|k|w|hz|mp|mm|cm|m|l|ml|kg|v|h|hr|p|d|x|th|st|nd|rd|pc|pcs|yr|in)$"
)


# A 2-letter series prefix + a 3+ digit model, written with a hyphen or a space: "WH-1000XM5", "WF 1000XM5"
_PREFIXED_MODEL_RE = re.compile(r"\b([a-z]{2})[- ](\d{3,}[a-z0-9]*)\b")
# Alphanumeric model codes: "s24", "m3", "a35", "wh1000xm5" (letters and digits, starting with a letter)
_MODEL_CODE_RE = re.compile(r"^[a-z]{1,3}\d[a-z0-9]*$")


def normalize(name: str) -> str:
    s = name.lower()
    s = s.replace("″", '"').replace("''", '"')
    s = re.sub(r"(\d+)\s+(gb|tb|mah|hz|w)\b", r"\1\2", s)
    s = _PREFIXED_MODEL_RE.sub(r"\1\2", s)  # keep "WH-1000XM5" whole, so it's never confused with "WF-1000XM5"
    s = re.sub(r"[^a-z0-9\". ]+", " ", s)
    tokens = [t for t in s.split() if t not in FILLER]
    return " ".join(tokens).strip()


def make_search_text(name: str, brand: str | None = None, category: str | None = None,
                     tags: list[str] | None = None) -> str:
    """Text the catalog search prefilters on (see Product.search_text)."""
    return normalize(" ".join([name, brand or "", (category or "").replace("_", " "), " ".join(tags or [])]))


@dataclass
class Attributes:
    storage: set[str] = field(default_factory=set)
    ram: set[str] = field(default_factory=set)
    colors: set[str] = field(default_factory=set)
    size: set[str] = field(default_factory=set)
    variants: set[str] = field(default_factory=set)
    connectivity: set[str] = field(default_factory=set)
    numbers: set[str] = field(default_factory=set)
    codes: set[str] = field(default_factory=set)
    accessory: bool = False


@lru_cache(maxsize=4096)
def extract_attributes(name: str) -> Attributes:
    s = name.lower()
    ram = {m.group(1) or m.group(2) for m in _RAM_RE.finditer(s)}
    storage = {f"{a}{u}" for a, u in _STORAGE_RE.findall(s)}
    # RAM values often appear as "8GB" too; don't treat them as storage
    storage -= {f"{r}gb" for r in ram}
    words = set(re.findall(r"[a-z0-9]+", s))
    norm_tokens = set(normalize(name).split())
    suffix_models = {
        t for t in norm_tokens if _SUFFIX_MODEL_RE.match(t) and not _UNIT_SUFFIX_RE.match(t)
    }
    return Attributes(
        storage=storage,
        ram=ram,
        colors=words & COLORS,
        size={m for m in _SIZE_RE.findall(s)},
        variants=(words & VARIANT_WORDS) | suffix_models,
        connectivity=words & CONNECTIVITY_WORDS,
        numbers={t for t in norm_tokens if _NUMBER_RE.match(t)},
        codes={t for t in norm_tokens if _MODEL_CODE_RE.match(t) and t not in CONNECTIVITY_WORDS},
        accessory=bool(ACCESSORY_RE.search(name)),
    )


def attributes_conflict(a: Attributes, b: Attributes) -> bool:
    if a.accessory != b.accessory:  # "Galaxy S24 FE" vs "Galaxy S24 FE back cover"
        return True
    if a.storage and b.storage and not (a.storage & b.storage):
        return True
    if a.ram and b.ram and not (a.ram & b.ram):
        return True
    if a.size and b.size and not (a.size & b.size):
        return True
    if a.connectivity and b.connectivity and not (a.connectivity & b.connectivity):
        return True
    # "iPhone 15" vs "iPhone 16": model numbers must overlap when both titles have them
    if a.numbers and b.numbers and not (a.numbers & b.numbers):
        return True
    # "WH-1000XM5" vs "WF-1000XM5", "Galaxy S24" vs "S23", "M3" vs "M2": model codes must overlap too
    if a.codes and b.codes and not (a.codes & b.codes):
        return True
    # "iPhone 16" vs "iPhone 16 Pro" / "iPhone 16e": tier words and suffixed models must match exactly
    if a.variants != b.variants:
        return True
    return False


@lru_cache(maxsize=4096)
def _identity_text(name: str) -> str:
    """Normalised title without colour words (colour doesn't change which product it is)."""
    return " ".join(t for t in normalize(name).split() if t not in COLORS)


def similarity(a: str, b: str) -> float:
    return fuzz.token_set_ratio(_identity_text(a), _identity_text(b))


def match_score(a: str, b: str) -> float:
    """0 when the variants conflict, otherwise the title similarity (0-100)."""
    if attributes_conflict(extract_attributes(a), extract_attributes(b)):
        return 0.0
    return similarity(a, b)


@dataclass
class ProductGroup:
    """One product with its offers from different stores."""

    name: str
    offers: list[Offer] = field(default_factory=list)

    def add(self, offer: Offer) -> None:
        # One offer per store: a fresh result beats one stored in our DB, otherwise keep the cheapest
        for i, existing in enumerate(self.offers):
            if existing.platform != offer.platform:
                continue
            existing_stored, offer_stored = existing.via == "catalog", offer.via == "catalog"
            if existing_stored and not offer_stored:
                offer.product_id = offer.product_id or existing.product_id
                self.offers[i] = offer
            elif offer_stored and not existing_stored:
                existing.product_id = existing.product_id or offer.product_id
            elif offer.price < existing.price:
                self.offers[i] = offer
            return
        self.offers.append(offer)

    def conflicts_with(self, offer: Offer) -> bool:
        """True if the offer's variant conflicts with ANY offer already in the group."""
        attrs = extract_attributes(offer.name)
        return any(attributes_conflict(attrs, extract_attributes(o.name)) for o in self.offers)

    def score(self, offer: Offer) -> float:
        if self.conflicts_with(offer):
            return 0.0
        return max(similarity(offer.name, o.name) for o in self.offers)

    def best_name(self) -> str:
        """The most informative title: one that states storage, without bundle extras, shortest first."""
        def rank(title: str) -> tuple:
            attrs = extract_attributes(title)
            bundle = bool(re.search(r"\b(with|combo|bundle|protection|coverage|applecare)\b", title, re.I))
            return (not attrs.storage, bundle, len(title))

        return min((o.name for o in self.offers), key=rank)

    @property
    def product_id(self) -> int | None:
        return next((o.product_id for o in self.offers if o.product_id), None)

    @property
    def is_demo(self) -> bool:
        return all(o.source == "demo" for o in self.offers)

    def to_dict(self) -> dict:
        offers = sorted(self.offers, key=lambda o: o.price)
        best = offers[0]
        worst = offers[-1]
        ratings = [o.rating for o in offers if o.rating]
        image = next((o.image_url for o in offers if o.image_url), None)
        return {
            "product_id": self.product_id,
            "name": self.name,
            "brand": next((o.brand for o in offers if o.brand), None),
            "category": next((o.category for o in offers if o.category), None),
            "image_url": image,
            "best_price": best.price,
            "best_platform": best.platform,
            "best_platform_label": best.platform_label,
            "mrp": max((o.mrp for o in offers if o.mrp), default=None),
            "rating": round(sum(ratings) / len(ratings), 1) if ratings else None,
            "review_count": sum(o.review_count or 0 for o in offers) or None,
            "max_saving": round(worst.price - best.price, 2) if len(offers) > 1 else 0,
            "store_count": len(offers),
            "is_demo": all(o.source == "demo" for o in offers),
            "trusted": any(o.trusted for o in offers),
            "offers": [o.model_dump() for o in offers],
        }


LLM_MATCH_TIMEOUT_SECONDS = 12


async def llm_same_product(pairs: list[tuple[str, str]]) -> list[bool]:
    """Ask Gemini whether each pair of titles is the same product + variant. One call for all pairs."""
    if not pairs:
        return []
    from core.llm import make_chat_runnable

    numbered = "\n".join(f'{i}. A="{a}" | B="{b}"' for i, (a, b) in enumerate(pairs))
    prompt = (
        "For each numbered pair of e-commerce product titles, answer whether they are the SAME product "
        "and SAME variant (model, storage, RAM, screen size). Ignore colour, seller and bundle wording. "
        f"Answer ONLY with a JSON array of booleans, in order, with {len(pairs)} items.\n\n{numbered}"
    )
    resp = await make_chat_runnable(temperature=0).ainvoke(prompt)
    text = resp.text if isinstance(resp.text, str) else str(resp.content)
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        raise ValueError("LLM did not return a JSON array")
    answers = json.loads(m.group(0))
    if len(answers) != len(pairs):
        raise ValueError("LLM returned the wrong number of answers")
    return [bool(a) for a in answers]


async def group_offers(offers: list[Offer], use_llm: bool | None = None) -> list[ProductGroup]:
    """Cluster offers into products. Groups are returned in the order first seen."""
    if use_llm is None:
        use_llm = settings.llm_enabled and settings.llm_match_enabled

    groups: list[ProductGroup] = []
    ambiguous: list[tuple[Offer, ProductGroup]] = []

    for offer in offers:
        best_group, best_score = None, 0.0
        for group in groups:
            # Never mix sample prices with real ones in one comparison
            if (offer.source == "demo") != group.is_demo:
                continue
            # Offers already linked to different DB products are different products
            if offer.product_id and group.product_id and offer.product_id != group.product_id:
                continue
            if offer.product_id and offer.product_id == group.product_id:
                # Same stored product, unless the titles prove a past mismatch (self-heals old bad merges)
                if not group.conflicts_with(offer):
                    best_group, best_score = group, 100.0
                    break
                continue
            score = group.score(offer)
            if score > best_score:
                best_group, best_score = group, score
        if best_group and best_score >= SAME_THRESHOLD:
            best_group.add(offer)
        elif best_group and best_score >= AMBIGUOUS_THRESHOLD and use_llm:
            ambiguous.append((offer, best_group))
        else:
            groups.append(ProductGroup(name=offer.name, offers=[offer]))

    if ambiguous:
        try:
            answers = await asyncio.wait_for(
                llm_same_product([(o.name, g.best_name()) for o, g in ambiguous]), LLM_MATCH_TIMEOUT_SECONDS
            )
        except Exception as exc:  # noqa: BLE001 - timeouts, 503s, bad JSON: fall back to fuzzy-only
            logger.warning("LLM matching unavailable (%s); keeping ambiguous offers separate", str(exc)[:120] or type(exc).__name__)
            answers = [False] * len(ambiguous)
        for (offer, group), same in zip(ambiguous, answers):
            # Re-check: the group may have gained offers since the question was asked
            if same and not group.conflicts_with(offer):
                group.add(offer)
            else:
                groups.append(ProductGroup(name=offer.name, offers=[offer]))

    groups = split_price_outliers(merge_groups(groups))
    for group in groups:
        group.name = group.best_name()
    return groups


OUTLIER_LOW, OUTLIER_HIGH = 0.45, 2.2


def split_price_outliers(groups: list[ProductGroup]) -> list[ProductGroup]:
    """An offer at a fraction (or a multiple) of the other stores' price is almost always a
    different item (an accessory, a bundle, a wrong listing), so it is dropped."""
    out: list[ProductGroup] = []
    for group in groups:
        prices = sorted(o.price for o in group.offers)
        if len(prices) < 2:
            out.append(group)
            continue
        mid = prices[len(prices) // 2] if len(prices) % 2 else (prices[len(prices) // 2 - 1] + prices[len(prices) // 2]) / 2
        if len(prices) == 2:
            mid = max(prices)  # with two offers, judge the cheaper one against the dearer
        keep = [o for o in group.offers if OUTLIER_LOW * mid <= o.price <= OUTLIER_HIGH * mid]
        if not keep:
            out.append(group)
            continue
        outliers = [o for o in group.offers if o not in keep]
        group.offers = keep
        out.append(group)
        if len(prices) == 2:
            # Two stores, no majority: can't tell which price is wrong, so show them separately
            for o in outliers:
                o.product_id = None
                out.append(ProductGroup(name=o.name, offers=[o]))
        elif outliers:
            logger.info("dropped %d listing(s) priced far from the other stores for %r", len(outliers), group.name[:60])
    return out


def merge_groups(groups: list[ProductGroup]) -> list[ProductGroup]:
    """Second pass: grouping depends on arrival order, so merge groups that turned out
    to be the same product once every group has all its members."""
    merged: list[ProductGroup] = []
    for group in groups:
        target = None
        for candidate in merged:
            if candidate.is_demo != group.is_demo:
                continue
            if candidate.product_id and group.product_id and candidate.product_id != group.product_id:
                continue
            if any(candidate.conflicts_with(o) for o in group.offers):
                continue
            best = max(similarity(a.name, b.name) for a in candidate.offers for b in group.offers)
            if best >= SAME_THRESHOLD:
                target = candidate
                break
        if target is None:
            merged.append(group)
        else:
            for offer in group.offers:
                target.add(offer)
    return merged
