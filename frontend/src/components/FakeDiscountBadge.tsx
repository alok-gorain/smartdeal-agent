"use client";

import { ChevronDown } from "lucide-react";
import { useState } from "react";

import PlatformBadge from "@/components/PlatformBadge";
import { rupees } from "@/lib/format";
import type { DiscountData, DiscountResult, Verdict } from "@/lib/types";

const STYLE: Record<Verdict, { box: string; icon: string; title: string }> = {
  FAKE: { box: "border-bad/50 bg-bad/10", icon: "🚩", title: "text-bad" },
  HIGH: { box: "border-bad/40 bg-bad/5", icon: "📈", title: "text-bad" },
  MINOR: { box: "border-warn/50 bg-warn/10", icon: "⚠️", title: "text-warn" },
  GENUINE: { box: "border-good/50 bg-good/10", icon: "✅", title: "text-good" },
  REGULAR: { box: "border-line bg-raised", icon: "ℹ️", title: "text-ink" },
  UNKNOWN: { box: "border-line bg-raised", icon: "❔", title: "text-muted" },
};

function headline(r: DiscountResult): string {
  switch (r.verdict) {
    case "FAKE":
      return `FAKE DISCOUNT — MRP inflated by ${Math.round(r.mrp_inflation_pct ?? 0)}%`;
    case "HIGH":
      return `ABOVE USUAL PRICE — ${Math.abs(Math.round(r.actual_discount_pct ?? 0))}% more than usual`;
    case "MINOR":
      return `MINOR DISCOUNT — only ${Math.floor(r.actual_discount_pct ?? 0)}% real saving`;
    case "GENUINE":
      return `GENUINE DEAL — ${Math.round(r.actual_discount_pct ?? 0)}% below the usual price`;
    case "REGULAR":
      return "REGULAR PRICE — no special deal right now";
    default:
      return "NOT ENOUGH DATA YET";
  }
}

function Bar({ label, value, max, tone }: { label: string; value: number; max: number; tone: string }) {
  return (
    <div className="grid grid-cols-[88px_1fr_auto] items-center gap-2 text-xs">
      <span className="text-muted">{label}</span>
      <div className="h-2.5 overflow-hidden rounded-full bg-bg/60">
        <div className={`h-full rounded-full ${tone}`} style={{ width: `${Math.max(4, (value / max) * 100)}%` }} />
      </div>
      <span className="font-semibold tabular-nums">{rupees(value)}</span>
    </div>
  );
}

export default function FakeDiscountBadge({ data }: { data: DiscountData }) {
  const [open, setOpen] = useState(false);
  const p = data.primary;
  const s = STYLE[p.verdict];
  const max = Math.max(p.mrp ?? 0, p.median_90d ?? 0, p.current_price);

  return (
    <section className={`rounded-xl border p-3 ${s.box}`}>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-start justify-between gap-2 text-left"
      >
        <div>
          <p className={`text-sm font-bold ${s.title}`}>
            <span aria-hidden>{s.icon} </span>
            {headline(p)}
          </p>
          <p className="mt-1 text-xs text-ink/90">{p.explanation}</p>
          <p className="mt-1 flex items-center gap-1.5 text-[11px] text-muted">
            <PlatformBadge slug={p.platform} label={p.platform_label} size="xs" /> {data.product_name}
            {p.confidence === "low" && " · low confidence (short history)"}
            {p.is_synthetic && " · Data history (synthetic)"}
          </p>
        </div>
        <ChevronDown className={`mt-0.5 h-4 w-4 shrink-0 transition-transform ${open ? "rotate-180" : ""}`} aria-hidden />
      </button>

      {open && (
        <div className="mt-3 space-y-3 border-t border-line/70 pt-3">
          {p.median_90d !== undefined && (
            <div className="space-y-1.5">
              {p.mrp ? <Bar label="MRP shown" value={p.mrp} max={max} tone="bg-muted/60" /> : null}
              <Bar label="Usual (90d)" value={p.median_90d} max={max} tone="bg-highlight" />
              <Bar label="Today" value={p.current_price} max={max} tone={p.verdict === "GENUINE" ? "bg-good" : "bg-warn"} />
              <p className="text-[11px] text-muted">
                Claimed {p.claimed_discount_pct ?? 0}% off MRP vs real {p.actual_discount_pct ?? 0}% below the 90-day median.
              </p>
            </div>
          )}
          {data.by_platform.length > 1 && (
            <ul className="space-y-1 text-xs">
              {data.by_platform.map((r) => (
                <li key={r.platform} className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-1.5">
                    <PlatformBadge slug={r.platform} label={r.platform_label} size="xs" />
                    {rupees(r.current_price)}
                  </span>
                  <span className={STYLE[r.verdict].title}>{r.label}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
