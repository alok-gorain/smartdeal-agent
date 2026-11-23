"use client";

import { Check, Copy, CreditCard, Ticket } from "lucide-react";
import { useState } from "react";

import PlatformBadge from "@/components/PlatformBadge";
import { rupees } from "@/lib/format";
import type { CouponsData, Deal } from "@/lib/types";

function describe(c: Deal): string {
  const value =
    c.discount_type === "flat"
      ? `${rupees(c.discount_value)} off`
      : `${c.discount_value}% ${c.discount_type === "cashback" ? "cashback" : "off"}`;
  const cap = c.max_discount ? ` up to ${rupees(c.max_discount)}` : "";
  const min = c.min_order_value ? ` · min ${rupees(c.min_order_value)}` : "";
  return value + cap + min;
}

function CodeChip({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={() => {
        navigator.clipboard?.writeText(code).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        });
      }}
      className="inline-flex items-center gap-1 rounded-md border border-dashed border-highlight px-2 py-0.5 font-mono text-[11px] text-highlight hover:bg-highlight/10"
      aria-label={`Copy code ${code}`}
    >
      {code}
      {copied ? <Check className="h-3 w-3" aria-hidden /> : <Copy className="h-3 w-3" aria-hidden />}
    </button>
  );
}

export default function CouponList({ data }: { data: CouponsData }) {
  if (!data.items.length) {
    return <p className="rounded-xl bg-card p-3 text-sm text-muted">No active offers match.</p>;
  }
  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold">🏷️ Coupons & bank offers</h3>
      <ul className="grid gap-2 sm:grid-cols-2">
        {data.items.slice(0, 10).map((c) => (
          <li key={c.id} className="flex flex-col gap-1.5 rounded-xl border border-line bg-card p-3">
            <div className="flex items-center justify-between gap-2">
              <PlatformBadge slug={c.platform === "any" ? "other" : c.platform} label={c.platform === "any" ? "All stores" : undefined} size="xs" />
              <span className="inline-flex items-center gap-1 text-[11px] text-muted">
                {c.offer_kind === "bank_offer" ? <CreditCard className="h-3 w-3" aria-hidden /> : <Ticket className="h-3 w-3" aria-hidden />}
                {c.bank_name ? `${c.bank_name} ${c.card_type ?? ""}`.trim() : "Coupon"}
              </span>
            </div>
            <p className="text-sm font-semibold leading-snug">{c.title}</p>
            <p className="text-xs text-muted">{describe(c)}</p>
            <div className="mt-auto flex flex-wrap items-center justify-between gap-2 pt-1">
              {c.code ? <CodeChip code={c.code} /> : <span className="text-[11px] text-muted">Auto-applied</span>}
              <span className="text-[11px] text-muted">
                {c.saving ? <strong className="text-good">Saves {rupees(c.saving)} · </strong> : null}
                {c.valid_until ? `till ${new Date(c.valid_until).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}` : ""}
              </span>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
