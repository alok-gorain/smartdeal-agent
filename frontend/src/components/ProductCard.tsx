"use client";

import { ArrowUpRight, BarChart3, Scale, ShieldCheck, Star } from "lucide-react";

import { useAsk } from "@/components/AskContext";
import PlatformBadge from "@/components/PlatformBadge";
import { count, rupees } from "@/lib/format";
import { CATEGORY_EMOJI } from "@/lib/platforms";
import type { ProductGroup } from "@/lib/types";

export default function ProductCard({ product, rank }: { product: ProductGroup; rank?: number }) {
  const ask = useAsk();
  const offers = [...product.offers].sort((a, b) => a.price - b.price);
  const best = offers[0];
  const mrp = product.mrp && product.mrp > best.price ? product.mrp : null;
  const off = mrp ? Math.round(((mrp - best.price) / mrp) * 100) : null;
  const ref = product.product_id ? ` (#${product.product_id})` : "";

  return (
    <article className="flex flex-col gap-3 rounded-xl border border-line bg-card p-3 sm:flex-row">
      <div className="relative flex h-24 w-full shrink-0 items-center justify-center overflow-hidden rounded-lg bg-raised sm:h-28 sm:w-28">
        {product.image_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={product.image_url} alt="" className="h-full w-full object-contain p-1" loading="lazy" />
        ) : (
          <span className="text-4xl" aria-hidden>
            {CATEGORY_EMOJI[product.category ?? ""] ?? "🛍️"}
          </span>
        )}
        {rank === 1 && (
          <span className="absolute left-1 top-1 rounded bg-highlight px-1.5 py-0.5 text-[10px] font-bold text-bg">TOP PICK</span>
        )}
      </div>

      <div className="min-w-0 flex-1">
        <h3 className="line-clamp-2 text-sm font-semibold leading-snug">{product.name}</h3>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
          {product.rating && (
            <span className="inline-flex items-center gap-1">
              <Star className="h-3 w-3 fill-warn text-warn" aria-hidden />
              {product.rating}
              {product.review_count ? <span>({count(product.review_count)})</span> : null}
            </span>
          )}
          <span>
            {product.store_count} store{product.store_count > 1 ? "s" : ""}
          </span>
          {product.is_demo && <span className="rounded bg-raised px-1.5 py-0.5 text-[10px]">demo data</span>}
          {product.trusted === false && (
            <span
              className="rounded bg-warn/15 px-1.5 py-0.5 text-[10px] font-medium text-warn"
              title="Only sold by marketplace or unknown sellers here. Check it is genuine before buying."
            >
              unverified sellers
            </span>
          )}
        </div>

        <div className="mt-2 flex flex-wrap items-baseline gap-x-2">
          <span className="text-xl font-bold text-ink">{rupees(best.price)}</span>
          {mrp && <span className="text-xs text-muted line-through">{rupees(mrp)}</span>}
          {off ? <span className="text-xs font-semibold text-good">{off}% off MRP</span> : null}
          <span className="text-xs text-muted">on</span>
          <PlatformBadge slug={best.platform} label={best.platform_label} size="xs" />
        </div>
        {best.best_deal && best.effective_price !== undefined && best.effective_price < best.price && (
          <p className="mt-1 text-xs text-highlight">
            {rupees(best.effective_price)} with {best.best_deal.title}
          </p>
        )}

        {offers.length > 1 && (
          <ul className="mt-2 flex flex-wrap gap-1.5">
            {offers.slice(1, 6).map((o) => (
              <li key={o.platform}>
                <a
                  href={o.url ?? undefined}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 rounded-md border border-line bg-raised px-2 py-1 text-xs hover:border-highlight"
                >
                  <PlatformBadge slug={o.platform} label={o.platform_label} size="xs" />
                  <span className="font-medium">{rupees(o.price)}</span>
                </a>
              </li>
            ))}
          </ul>
        )}

        <div className="mt-3 flex flex-wrap gap-2">
          <button
            onClick={() => ask(`Compare prices for ${product.name}${ref}`)}
            className="inline-flex items-center gap-1 rounded-lg bg-accent px-2.5 py-1.5 text-xs font-medium text-ink hover:brightness-125"
          >
            <Scale className="h-3.5 w-3.5" aria-hidden /> Compare
          </button>
          {product.product_id && (
            <>
              <button
                onClick={() => ask(`Show price history for ${product.name}${ref}`)}
                className="inline-flex items-center gap-1 rounded-lg bg-accent px-2.5 py-1.5 text-xs font-medium text-ink hover:brightness-125"
              >
                <BarChart3 className="h-3.5 w-3.5" aria-hidden /> Price history
              </button>
              <button
                onClick={() => ask(`Is the discount on ${product.name}${ref} real?`)}
                className="inline-flex items-center gap-1 rounded-lg bg-accent px-2.5 py-1.5 text-xs font-medium text-ink hover:brightness-125"
              >
                <ShieldCheck className="h-3.5 w-3.5" aria-hidden /> Real discount?
              </button>
            </>
          )}
          {best.url && (
            <a
              href={best.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 rounded-lg border border-highlight/60 px-2.5 py-1.5 text-xs font-medium text-highlight hover:bg-highlight/10"
            >
              View on {best.platform_label} <ArrowUpRight className="h-3.5 w-3.5" aria-hidden />
            </a>
          )}
        </div>
      </div>
    </article>
  );
}
