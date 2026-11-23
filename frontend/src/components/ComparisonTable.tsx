import { ArrowUpRight, Star } from "lucide-react";

import PlatformBadge from "@/components/PlatformBadge";
import { rupees } from "@/lib/format";
import type { ComparisonData } from "@/lib/types";

export default function ComparisonTable({ data }: { data: ComparisonData }) {
  const best = data.rows[0];
  // Savings vs the next-cheapest store: comparing with the priciest (often an import seller) overstates it
  const next = data.savings.find((s) => s.amount > 0);
  const range = data.rows.length > 1 ? `${rupees(best.effective_price)}–${rupees(data.rows[data.rows.length - 1].effective_price)}` : null;

  return (
    <section className="overflow-hidden rounded-xl border border-line bg-card">
      <header className="border-b border-line px-3 py-2.5">
        <h3 className="text-sm font-semibold">{data.name}</h3>
        <p className="mt-0.5 text-xs text-muted">
          Cheapest on <strong className="text-good">{data.best_platform_label}</strong>
          {next && (
            <>
              {" "}— <strong className="text-good">{rupees(next.amount)}</strong> less than {next.platform_label}, the next cheapest
            </>
          )}
          {range && <span> · {data.rows.length} stores, {range}</span>}
          {data.is_demo && <span className="ml-2 rounded bg-raised px-1.5 py-0.5 text-[10px]">demo data</span>}
        </p>
      </header>
      <div className="scrollbar-thin overflow-x-auto">
        <table className="w-full min-w-[560px] text-left text-xs">
          <thead className="bg-raised text-muted">
            <tr>
              <th className="px-3 py-2 font-medium">Store</th>
              <th className="px-3 py-2 font-medium">Price</th>
              <th className="px-3 py-2 font-medium">Rating</th>
              <th className="px-3 py-2 font-medium">Delivery</th>
              <th className="px-3 py-2 font-medium">Best offer</th>
              <th className="px-3 py-2 text-right font-medium">Effective price</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => {
              const isBest = r === best;
              return (
                <tr key={r.platform} className={`border-t border-line ${isBest ? "bg-good/10" : ""}`}>
                  <td className="px-3 py-2">
                    <a
                      href={r.url ?? undefined}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 hover:underline"
                    >
                      <PlatformBadge slug={r.platform} label={r.platform_label} size="xs" />
                      {r.url && <ArrowUpRight className="h-3 w-3 text-muted" aria-label="open store" />}
                    </a>
                    {!r.in_stock && <span className="ml-1 text-[10px] text-bad">out of stock</span>}
                    {r.trusted === false && (
                      <span className="ml-1 text-[10px] text-warn" title="Marketplace or unknown seller">
                        unverified
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <div className="font-semibold">{rupees(r.price)}</div>
                    {r.mrp && r.mrp > r.price && <div className="text-[10px] text-muted line-through">{rupees(r.mrp)}</div>}
                  </td>
                  <td className="px-3 py-2">
                    {r.rating ? (
                      <span className="inline-flex items-center gap-1">
                        <Star className="h-3 w-3 fill-warn text-warn" aria-hidden /> {r.rating}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-3 py-2 text-muted">{r.delivery_info ?? "—"}</td>
                  <td className="px-3 py-2">
                    {r.best_deal ? (
                      <span title={r.best_deal.description ?? undefined}>
                        {r.best_deal.bank_name && <strong>{r.best_deal.bank_name} </strong>}
                        <span className="text-muted">−{rupees(r.best_deal.saving ?? 0)}</span>
                      </span>
                    ) : (
                      <span className="text-muted">—</span>
                    )}
                  </td>
                  <td className={`px-3 py-2 text-right font-bold ${isBest ? "text-good" : ""}`}>
                    {rupees(r.effective_price)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
