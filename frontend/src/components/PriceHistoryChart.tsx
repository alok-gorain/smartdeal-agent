"use client";

import { TrendingDown, TrendingUp } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { usePriceHistory } from "@/hooks/useProducts";
import { useThemeColors } from "@/hooks/useThemeColors";
import { compactRupees, rupees, shortDate } from "@/lib/format";
import { platformStyle } from "@/lib/platforms";
import type { HistoryData } from "@/lib/types";

const SALE_SHORT: [RegExp, string][] = [
  [/republic/i, "Republic Day"],
  [/holi/i, "Holi"],
  [/summer/i, "Summer"],
  [/end of reason/i, "EORS"],
  [/prime/i, "Prime Day"],
  [/independence/i, "Aug 15"],
  [/billion|festival/i, "BBD / GIF"],
  [/diwali/i, "Diwali"],
  [/black friday/i, "Black Friday"],
  [/year-end/i, "Year-end"],
];

function shortSale(name: string): string {
  return SALE_SHORT.find(([re]) => re.test(name))?.[1] ?? name;
}

type Mode = "avg" | "low";

const MAX_LINES = 6;

export default function PriceHistoryChart({ data: initial }: { data: HistoryData }) {
  const [months, setMonths] = useState(initial.months);
  const [mode, setMode] = useState<Mode>("low");
  const { data, loading } = usePriceHistory(initial.product_id, months, initial);
  const h = data ?? initial;
  const c = useThemeColors();
  const [narrow, setNarrow] = useState(false);

  // On phones the in-chart sale labels overlap, so they move into a line under the chart
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 640px)");
    const update = () => setNarrow(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);

  const domain = useMemo(() => {
    const values: number[] = [];
    h.series.forEach((row) =>
      h.platforms.slice(0, MAX_LINES).forEach((p) => {
        const v = row[mode === "low" ? `${p.slug}_low` : p.slug];
        if (typeof v === "number") values.push(v);
      }),
    );
    if (!values.length) return [0, 1];
    const min = Math.min(...values);
    const max = Math.max(...values);
    const pad = (max - min) * 0.15 || max * 0.05;
    return [Math.max(0, Math.floor(min - pad)), Math.ceil(max + pad)];
  }, [h, mode]);

  // Up to 6 lines stay readable; the API lists the most-tracked stores first
  const shown = h.platforms.slice(0, MAX_LINES);
  const hiddenCount = h.platforms.length - shown.length;

  const sparse = (slug: string) =>
    h.series.filter((row) => typeof row[mode === "low" ? `${slug}_low` : slug] === "number").length <= 3;

  if (!h.data_points) {
    return (
      <section className="rounded-xl border border-line bg-card p-4 text-sm text-muted">
        No price history recorded yet for {h.product_name}. Prices are recorded daily from now on.
      </section>
    );
  }

  return (
    <section className="rounded-xl border border-line bg-card p-3">
      <header className="mb-2 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold">📊 Price history · {h.product_name}</h3>
          <p className="mt-0.5 text-xs text-muted">
            {mode === "low" ? "Lowest price each month" : "Average price each month"}; dashed lines mark sales
            {h.is_synthetic && <span className="ml-2 rounded bg-raised px-1.5 py-0.5 text-[10px]">demo data</span>}
          </p>
          {!h.is_synthetic && h.from_google && (
            <p className="mt-1 text-xs text-muted">
              Real prices from Google Shopping&apos;s price history
              {h.tracked_since ? ` · SmartDeal tracking daily since ${shortDate(h.tracked_since)}` : ""}
            </p>
          )}
          {!h.is_synthetic && !h.from_google && h.tracking_since && (h.days_tracked ?? 0) < 30 && (
            <p className="mt-1 text-xs text-warn">
              Tracking started {shortDate(h.tracking_since)} · {h.days_tracked} day{h.days_tracked === 1 ? "" : "s"} of
              prices so far. History fills in as prices are recorded daily.
            </p>
          )}
        </div>
        <div className="flex gap-1 text-xs">
          <div className="flex overflow-hidden rounded-lg border border-line" role="group" aria-label="Price type">
            {(["low", "avg"] as Mode[]).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                aria-pressed={mode === m}
                className={`px-2 py-1 ${mode === m ? "bg-accent text-ink" : "text-muted hover:text-ink"}`}
              >
                {m === "low" ? "Lowest" : "Average"}
              </button>
            ))}
          </div>
          <select
            value={months}
            onChange={(e) => setMonths(Number(e.target.value))}
            className="rounded-lg border border-line bg-raised px-1.5 py-1 text-ink"
            aria-label="Range"
          >
            <option value={6}>6 months</option>
            <option value={12}>12 months</option>
            <option value={24}>24 months</option>
          </select>
        </div>
      </header>

      <div className={`h-64 w-full sm:h-72 ${loading ? "opacity-50" : ""}`}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={h.series} margin={{ top: 18, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke={c.line} strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="label"
              tick={{ fill: c.muted, fontSize: 11 }}
              tickLine={false}
              axisLine={{ stroke: c.line }}
              interval="preserveStartEnd"
            />
            <YAxis
              domain={domain}
              tickFormatter={compactRupees}
              tick={{ fill: c.muted, fontSize: 11 }}
              tickLine={false}
              axisLine={false}
              width={52}
            />
            <Tooltip
              formatter={(value: number, key: string) => [rupees(value), platformStyle(key.replace(/_low$/, "")).label]}
              contentStyle={{
                background: c.card,
                border: "1px solid rgb(var(--line))",
                borderRadius: 8,
                fontSize: 12,
              }}
              labelStyle={{ color: c.ink, fontWeight: 600 }}
            />
            <Legend
              formatter={(key: string) => platformStyle(key.replace(/_low$/, "")).label}
              wrapperStyle={{ fontSize: 11 }}
            />
            {h.sale_events.map((e) => (
              <ReferenceLine
                key={e.label}
                x={e.label}
                stroke={c.highlight}
                strokeOpacity={0.55}
                strokeDasharray="4 4"
                label={
                  narrow
                    ? undefined
                    : { value: e.names.map(shortSale).join(" · "), position: "insideTop", fill: c.highlight, fontSize: 9 }
                }
              />
            ))}
            {shown.map((p) => (
              <Line
                key={p.slug}
                type="monotone"
                dataKey={mode === "low" ? `${p.slug}_low` : p.slug}
                stroke={platformStyle(p.slug, p.label).chart}
                strokeWidth={2}
                // Show points when a store has only a few months of data, or a lone point would be invisible
                dot={sparse(p.slug) ? { r: 3 } : false}
                activeDot={{ r: 4 }}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>

      {hiddenCount > 0 && (
        <p className="mt-1 text-[11px] text-muted">
          Showing the {shown.length} most-tracked stores · {hiddenCount} more in the data
        </p>
      )}

      {narrow && h.sale_events.length > 0 && (
        <p className="mt-1 text-[11px] leading-relaxed text-muted">
          <span className="text-highlight">┆ Sales:</span>{" "}
          {h.sale_events.map((e) => `${e.label.split(" ")[0]} ${e.names.map(shortSale).join("/")}`).join(" · ")}
        </p>
      )}

      <dl className="mt-2 grid grid-cols-2 gap-2 text-xs sm:grid-cols-3">
        {h.lowest && (
          <div className="rounded-lg bg-raised px-2.5 py-1.5">
            <dt className="text-muted">Lowest</dt>
            <dd className="font-semibold text-good">
              {rupees(h.lowest.price)}{" "}
              <span className="font-normal text-muted">
                {platformStyle(h.lowest.platform).label}, {shortDate(h.lowest.date)}
              </span>
            </dd>
          </div>
        )}
        {h.highest && (
          <div className="rounded-lg bg-raised px-2.5 py-1.5">
            <dt className="text-muted">Highest</dt>
            <dd className="font-semibold text-bad">
              {rupees(h.highest.price)}{" "}
              <span className="font-normal text-muted">{shortDate(h.highest.date)}</span>
            </dd>
          </div>
        )}
        {h.trend && (
          <div className="col-span-2 rounded-lg bg-raised px-2.5 py-1.5 sm:col-span-1">
            <dt className="text-muted">3-month trend</dt>
            <dd className="inline-flex items-center gap-1 font-semibold">
              {h.trend.direction === "down" ? (
                <TrendingDown className="h-3.5 w-3.5 text-good" aria-hidden />
              ) : (
                <TrendingUp className={`h-3.5 w-3.5 ${h.trend.direction === "up" ? "text-bad" : "text-muted"}`} aria-hidden />
              )}
              {h.trend.change_pct_3m > 0 ? "+" : ""}
              {h.trend.change_pct_3m}%
            </dd>
          </div>
        )}
      </dl>
    </section>
  );
}
