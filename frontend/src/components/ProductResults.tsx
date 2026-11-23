import { AlertTriangle } from "lucide-react";

import ProductCard from "@/components/ProductCard";
import type { ProductsData } from "@/lib/types";

export default function ProductResults({ data }: { data: ProductsData }) {
  const failed = Object.keys(data.errors ?? {});
  return (
    <section className="space-y-2">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">{data.title}</h3>
        <span className="text-xs text-muted">
          {data.groups.length} of {data.total_found} shown · trusted stores first, cheapest store first in each
        </span>
      </header>
      {failed.length > 0 && (
        <p className="flex items-start gap-1.5 rounded-lg border border-warn/40 bg-warn/10 px-2.5 py-1.5 text-xs">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warn" aria-hidden />
          <span>
            Couldn&apos;t reach {failed.join(", ")} this time — showing results from the other stores.
          </span>
        </p>
      )}
      {data.groups.length === 0 ? (
        <p className="rounded-lg bg-card px-3 py-4 text-center text-sm text-muted">No products match.</p>
      ) : (
        <div className="grid gap-2">
          {data.groups.map((g, i) => (
            <ProductCard key={`${g.product_id ?? g.name}-${i}`} product={g} rank={i + 1} />
          ))}
        </div>
      )}
    </section>
  );
}
