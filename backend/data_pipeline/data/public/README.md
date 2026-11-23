# SmartDeal public sample dataset

About 2,800 Indian e-commerce products with store offers and a **dummy** 12-month price history. It's built from two free, openly licensed datasets, cleaned, and extended with synthetic rows. The app loads it as **demo data**, and the UI labels it so.

Rebuild it with:

```bash
python -I data_pipeline/build_public_dataset.py --promptcloud flipkart_com-ecommerce_sample.csv --zenodo flipkart_product.csv
```

Counts are in `stats.json`.

## Sources and licences

| Source | What was used | Licence |
|---|---|---|
| **Flipkart Products** by PromptCloud: 20,000 listings crawled from flipkart.com, Dec 2015–Jun 2016 ([Kaggle: PromptCloudHQ/flipkart-products](https://www.kaggle.com/datasets/PromptCloudHQ/flipkart-products); copy used: [Hugging Face jason1966/PromptCloudHQ_flipkart-products](https://huggingface.co/datasets/jason1966/PromptCloudHQ_flipkart-products); licence as stated on [kenthua/flipkart-raw-demo](https://huggingface.co/datasets/kenthua/flipkart-raw-demo)) | Name, brand, category tree, MRP (`retail_price`), selling price (`discounted_price`), rating | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) |
| **Flipkart Review Dataset**: 189,874 reviews of 812 products ([Zenodo, DOI 10.5281/zenodo.17612521](https://doi.org/10.5281/zenodo.17612521)) | Product name, price, and the average of review ratings (with the review count) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |

Because the PromptCloud data is ShareAlike, **this derived dataset is released under CC BY-SA 4.0**. Keep this attribution if you share it.

## What is real and what is synthetic

| Data | Real or synthetic |
|---|---|
| Product names, brands, categories | Real, from the sources. Names are cleaned, mangled characters repaired, and Zenodo categories are inferred from the names |
| Flipkart price and MRP | Real, from the sources (2016 prices for PromptCloud items). Zenodo has no MRP, so one was generated |
| Ratings | Real, from the sources. Zenodo ratings are the mean of real reviews |
| Colour variants (`is_augmented = 1`, `variant_of` = base product) | **Synthetic.** About 1 in 5 fashion, home, furniture, jewellery, watch and bag products got 1–2 colour variants |
| Offers at other stores (Amazon, Myntra, AJIO, Croma, Nykaa, Pepperfry, …) | **Synthetic.** Prices are within −7% to +10% of the Flipkart price |
| Price history and every date in `price_history.csv.gz` | **Synthetic (dummy dates).** Weekly points for 12 months plus the first day of each Indian sale |

The price histories follow realistic stories, so the app's fake-discount check and buy-timing have something to find:
- **Inflated MRP:** the product always sold near today's price, so the "% off" is a **fake discount**.
- **Genuine drop:** a real drop of 13–23% in the last few days.
- **Minor drop:** a small real saving.
- **Above usual:** a recent price rise.
- **Seasonal or steady:** prices that only dip during sales such as Republic Day, Prime Day, Big Billion Days, Diwali and Black Friday.

## Files

- **`products.csv`:** `product_key, name, brand, category, subcategory, mrp, price, rating, rating_count, dataset, source_ref, variant_of, is_augmented`
- **`listings.csv`:** `product_key, store, price, mrp, rating, review_count, delivery_info`
- **`price_history.csv.gz`:** `date, product_key, store, price, mrp`
- **`stats.json`:** counts per file and per category

When the loader (`python -m data_pipeline.seed_public_dataset`) adds these to the database, it shifts every date so the history ends on the day it was loaded.
