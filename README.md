# SmartDeal Agent

An AI shopping assistant for Indian shoppers. Ask in plain language ("ANC earbuds under ₹3000") and it:

- **Searches many stores at once**: Amazon, Flipkart, Myntra, and (through Google Shopping) Croma, Reliance Digital, Vijay Sales, Tata CLiQ, AJIO, Nykaa, JioMart, brand stores and more
- **Matches the same product across stores**, variant-aware (128GB ≠ 256GB, iPhone 16 ≠ 16 Pro)
- **Ranks by effective price**: listed price minus the best coupon or bank-card offer
- **Shows 12-month price history** per store, with Indian sale events marked
- **Detects fake discounts**: compares today's price with the 90-day median instead of the MRP
- **Predicts the best time to buy** from price history plus the Indian sale calendar (Republic Day, Prime Day, Big Billion Days, Diwali, Black Friday, …)
- **Remembers the conversation**: "now only Samsung", "under ₹1500", "sort by rating" refine the previous results without searching again

It runs with **no API keys at all** (demo catalog of 50 products and a rule-based quick-search mode). Add keys to switch on the Gemini agent and live prices.

---

## Architecture

```
Next.js chat UI ──WebSocket──▶ FastAPI ──▶ LangGraph ReAct agent (Gemini)
   (Recharts)        REST                      │ tools
                                               ▼
                         search_service ── store adapters (parallel, fail-soft)
                               │            ├─ catalog          (Postgres: demo + tracked products)
                               │            ├─ google_shopping  (SerpApi → most Indian stores)
                               │            ├─ amazon           (PA-API 5.0 → scraper fallback)
                               │            ├─ flipkart         (Affiliate API → scraper fallback)
                               │            └─ myntra           (embedded page JSON)
                               ▼
                         product_matcher (variant rules → rapidfuzz → Gemini for unclear pairs)
                               ▼
        Postgres: products, listings, daily price_records, coupons, LangGraph checkpoints
        Redis: search cache (30 min), chat transcripts, Celery broker
        Celery beat: 06:00 IST daily price collection · offers refresh every 6 h
```

**Agent tools** (`backend/agents/tools.py`): `search_products`, `filter_results`, `compare_prices`, `get_price_history`, `analyze_discount`, `predict_best_buy_time`, `find_coupons`. Each tool returns text for the model plus a structured block the UI renders (product cards, comparison table, chart, badges).

**Without a Gemini key**, or if the model fails mid-conversation, chat falls back to a rule-based mode (`agents/fallback.py`) that uses the same tools.

---

## Quick start (Docker)

```bash
cp .env.example .env        # optional: add GOOGLE_API_KEY, SERPAPI_KEY
docker compose up --build
```

- Chat UI: http://localhost:3000
- API docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

On first start the backend runs migrations and seeds 50 products, 12 months of synthetic price history and 20 offers.

## Local development (without Docker)

Needs Python 3.12, Node 20, and Postgres 16 + Redis 7 running (or just `docker compose up postgres redis`).

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
alembic upgrade head
python -m data_pipeline.seed_data
uvicorn main:app --reload --port 8000
```

```bash
cd backend && celery -A celery_app worker --loglevel=info
```

```bash
cd backend && celery -A celery_app beat --loglevel=info
```

```bash
cd frontend && npm install && npm run dev
```

Run the tests:

```bash
cd backend && pytest
```

---

## Configuration

All settings come from environment variables (see `.env.example`).

| Variable | Purpose |
|---|---|
| `GOOGLE_API_KEY` | Turns on the Gemini agent. Free key at aistudio.google.com |
| `GEMINI_MODEL` | Default `gemini-flash-lite-latest`: tracks Google's current Flash-Lite, ~1.5–3 s per agent step |
| `GEMINI_FALLBACK_MODELS` | Tried in order when the main model is overloaded (503), retired (404) or slow. Default `gemini-3.5-flash-lite,gemini-3.1-flash-lite` |
| `LLM_TIMEOUT_SECONDS` | Per-model timeout before failing over (default 20) |
| `SERPAPI_KEY` | Google Shopping India, which covers most Indian stores in one call. **Recommended main live source** |
| `AMAZON_ACCESS_KEY` / `AMAZON_SECRET_KEY` / `AMAZON_PARTNER_TAG` | Amazon PA-API 5.0 |
| `FLIPKART_AFFILIATE_ID` / `FLIPKART_AFFILIATE_TOKEN` | Flipkart Affiliate API |
| `HISTORY_BACKFILL_ENABLED` / `HISTORY_BACKFILL_MONTHLY_LIMIT` | Load ~12 months of real price history from Google Shopping the first time a product is analysed (1 SerpApi search per product; default cap 100/month) |
| `PRICE_REFRESH_DAILY_LIMIT` | Live products re-priced each morning (1 SerpApi search each; skips products already priced that day). Default 2; raise it on a paid SerpApi plan |
| `SEED_PUBLIC_DATASET` | Load the ~2,800-product public sample dataset at startup (default `true`; it's skipped once loaded) |
| `ENABLE_SCRAPERS` | Direct Amazon/Flipkart/Myntra scrapers when no keys are set. Local development only |
| `DEMO_CATALOG` | Seeded sample products: `auto` (default) = only while no live price source is configured, `true` = always, `false` = never. Sample and real prices are never mixed in one comparison |
| `ENABLED_PLATFORMS` | Comma list of adapters to allow, e.g. `catalog,google_shopping` |
| `DATABASE_URL`, `REDIS_URL` | Storage |
| `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_WS_URL` | Backend URLs for the frontend (**baked in at build time**) |

### About data sources

- **Scraping Amazon/Flipkart breaks their terms of service and gets blocked by CAPTCHA quickly.** The scrapers rate-limit to 1 request per second per host and rotate User-Agents, but they're meant for local experiments only. They're off by default in Docker.
- Amazon PA-API access needs an Associates account with 3 qualifying sales in 180 days. Flipkart's affiliate API is hard to get approved for.
- **SerpApi (Google Shopping)** is the practical, legal way to cover "all stores". Adding another store is one adapter in `backend/services/platforms/` plus one line in `registry.py`.
- Coupons and bank offers come from `backend/data_pipeline/data/offers.json`, reloaded every 6 hours. Coupon sites (GrabOn, CouponDunia) forbid scraping, so this file is meant to be edited by hand or filled from an affiliate network's offer feed.

### Live result quality

Google Shopping returns a lot of noise, so live results are cleaned before they're compared:

- **Model-specific searches** ("Sony WH-1000XM5", "iPhone 16") keep only listings that mention that model number. Google pads these searches with unrelated popular products.
- **Accessories** (covers, skins, ear pads, chargers, tempered glass) are dropped unless the search asks for one.
- **Used, refurbished and known pre-owned stores** are skipped.
- **Variants never merge**: 16 ≠ 16e ≠ 16 Plus, and 128GB ≠ 256GB. Colours are treated as the same product.
- **Listings priced far from the other stores** for the same product (under 45% or over 220% of the median) are dropped as mislisted.

### Price history for live products

SmartDeal records every tracked product's price daily, but a newly found product would start with no history. So the first time the agent (or the history API) looks at a live product, it **backfills about 12 months of real per-store prices from Google Shopping** (SerpApi `google_product`):

- **What Google provides:** a dated price each time a store changed its price. Each price is held until the next change, and one-day glitches are dropped.
- **Stored separately:** these prices are saved as `source = google_history`. SmartDeal's own daily prices always take priority for the same day.
- **Budget:** it costs one SerpApi search per product, runs at most once per product, and stops at `HISTORY_BACKFILL_MONTHLY_LIMIT`.
- **Fake-discount check:** compares a store's price with the lower of two things: that store's own 90-day median, or the typical lowest price across stores. A store that "drops" from its own inflated price isn't flagged as a deal if the product is usually cheaper elsewhere.

### Public sample dataset (~2,800 products)

`backend/data_pipeline/data/public/` holds a sample catalogue built from two free, openly licensed datasets:
- **PromptCloud's Flipkart Products:** 20,000 listings, CC BY-SA 4.0.
- **Zenodo Flipkart Review Dataset:** 812 products with 189,874 reviews, CC BY 4.0.

The build cleaned and de-duplicated them and **added rows**: 295 colour variants, and offers at 1–3 more stores per product (8,399 listings). Neither source has price history, so the build also generates a **dummy dated 12-month history** (520,738 rows). That history mixes inflated-MRP "fake discounts", genuine drops and sale-season dips.

The API loads the dataset once at startup (`SEED_PUBLIC_DATASET=true`) and shifts its dates to end on the load day. With `DEMO_CATALOG=true`, these products appear as **sample listings**, after real results. See the folder's README for sources, licences and what is real versus synthetic. To rebuild:

```bash
cd backend && python -I data_pipeline/build_public_dataset.py --promptcloud <flipkart_com-ecommerce_sample.csv> --zenodo <flipkart_product.csv>
```

### Data history

Seeded products and offers come from the local catalog; their generated price history is synthetic. The UI labels seeded products as "sample listing" and synthetic history as "Data history (synthetic)". Once a live source (e.g. `SERPAPI_KEY`) is set, demo products are hidden automatically and never matched with real ones.

Real price history builds up from the day live sources are switched on: every searched product is stored and re-priced daily at 06:00 IST. Until a product has about a week of prices, the fake-discount check says "not enough data", and buy-timing needs about a month.

---

## API

| Method | Path | Description |
|---|---|---|
| WS | `/ws/chat/{session_id}` | Chat. Send `{"message": "..."}`; receive `thinking` steps, then `{"type":"response","content":md,"blocks":[...]}` |
| GET | `/api/chat/{session_id}/history` | Restore a conversation |
| GET | `/api/products/search?q=&category=&platforms=&budget_min=&budget_max=` | Search all stores |
| GET | `/api/products/{id}` | Product with every store listing |
| GET | `/api/history/{id}?months=12` | Month-wise history per store + sale markers |
| GET | `/api/history/{id}/discount` | Fake-discount analysis |
| GET | `/api/history/{id}/prediction` | Buy-now-or-wait prediction |
| GET | `/api/coupons?platform=&bank=&category=&price=` | Active coupons and bank offers (with savings for a price) |
| GET | `/api/platforms` | Which store adapters are active and how they get data |
| GET | `/health` | Database, Redis and LLM status |

---

## Deploying to Railway

The live deployment runs **5 Railway services**:

| Service | Source | What it runs |
|---|---|---|
| `api` | `backend/` (Dockerfile), `SERVICE_ROLE=api` | Migrations, seed, offers sync, then FastAPI on `$PORT` |
| `jobs` | `backend/` (Dockerfile), `SERVICE_ROLE=jobs` | Celery worker with the scheduler built in (daily prices at 06:00 IST, offers every 6 h) |
| `web` | `frontend/` (Dockerfile) | Next.js; `NEXT_PUBLIC_API_URL` is baked in at build time |
| `Postgres`, `Redis` | Railway databases | Data, chat memory, cache, Celery broker |

Steps with the [Railway CLI](https://docs.railway.com/guides/cli):

```bash
railway login
railway init --name smartdeal-agent
railway add --database postgres
railway add --database redis
railway add --service api
railway add --service jobs
railway add --service web
railway domain --service api --port 8000
railway domain --service web --port 3000
```

Variables (`railway variable set KEY=VALUE --service <name> --skip-deploys`):

- **api and jobs:** `DATABASE_URL=${{Postgres.DATABASE_URL}}`, `REDIS_URL=${{Redis.REDIS_URL}}`, `SERVICE_ROLE` (`api` / `jobs`), `GEMINI_MODEL`, `GEMINI_FALLBACK_MODELS`. Plain `postgresql://` URLs are converted to the async driver automatically.
- **api only:** `PORT=8000`, `CORS_ORIGINS=https://<web domain>`.
- **web:** `PORT=3000`, `NEXT_PUBLIC_API_URL=https://<api domain>`. The WebSocket URL is derived from it.
- **Secrets:** pipe them in so they never appear on screen, e.g. `printf %s "$KEY" | railway variable set GOOGLE_API_KEY --stdin --service api`.

Deploy (uploads the folder; `.railwayignore` keeps `.env`, `.venv` and `node_modules` out):

```bash
railway up backend --path-as-root --service api --detach
```

```bash
railway up backend --path-as-root --service jobs --detach
```

```bash
railway up frontend --path-as-root --service web --detach
```

Backend images install from `requirements.lock` and the frontend from `package-lock.json`, so Railway builds the exact tested versions.

Google Cloud Run isn't a good fit for the `jobs` service, because Cloud Run scales idle services to zero.

---

## Project layout

```
backend/
  agents/          state, prompts, tools, LangGraph graph, runner, rule-based fallback
  api/             REST + WebSocket routes
  core/            settings, database, Redis, logging
  data_pipeline/   Celery tasks, seed script, synthetic history, offers file
  models/          SQLAlchemy models (Product, ProductListing, PriceRecord, Coupon)
  scrapers/        polite HTTP + Amazon / Flipkart / Myntra parsers
  services/        search, matching, history, discount, prediction, coupons, sale calendar
    platforms/     one adapter per data source + registry
  alembic/         migrations
  tests/
frontend/src/
  app/             layout, / → /chat, chat page
  components/      ChatWindow, MessageBubble, ProductCard, ComparisonTable, PriceHistoryChart,
                   FakeDiscountBadge, BuyTimingCard, CouponList, LoadingAnimation, …
  hooks/ lib/      WebSocket chat hook, API client, types, formatting
```
