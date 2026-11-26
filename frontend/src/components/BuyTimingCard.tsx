import { CalendarClock } from "lucide-react";

import { rupees, shortDate } from "@/lib/format";
import type { TimingData } from "@/lib/types";

export default function BuyTimingCard({ data }: { data: TimingData }) {
  const wait = data.action === "WAIT";
  const tone = wait ? "border-warn/50 bg-warn/10" : data.action === "BUY_NOW" ? "border-good/50 bg-good/10" : "border-line bg-raised";
  const sales = data.upcoming_sales.slice(0, 3);

  return (
    <section className={`rounded-xl border p-3 ${tone}`}>
      <header className="flex items-start gap-2">
        <CalendarClock className="mt-0.5 h-4 w-4 shrink-0 text-highlight" aria-hidden />
        <div>
          <p className={`text-sm font-bold ${wait ? "text-warn" : data.action === "BUY_NOW" ? "text-good" : "text-muted"}`}>
            {data.label}
          </p>
          <p className="mt-0.5 text-xs text-ink/90">{data.reason}</p>
          <p className="mt-0.5 text-[11px] text-muted">
            {data.product_name}
            {data.is_synthetic && " · Data history (synthetic)"}
          </p>
        </div>
      </header>

      {data.avg_price !== undefined && (
        <dl className="mt-3 grid grid-cols-3 gap-2 text-xs">
          <div className="rounded-lg bg-card/70 px-2 py-1.5">
            <dt className="text-muted">Now</dt>
            <dd className="font-semibold">{rupees(data.current_price)}</dd>
          </div>
          <div className="rounded-lg bg-card/70 px-2 py-1.5">
            <dt className="text-muted">12-mo avg</dt>
            <dd className="font-semibold">{rupees(data.avg_price)}</dd>
          </div>
          <div className="rounded-lg bg-card/70 px-2 py-1.5">
            <dt className="text-muted">Lowest</dt>
            <dd className="font-semibold text-good">{rupees(data.lowest_ever)}</dd>
          </div>
        </dl>
      )}

      {sales.length > 0 && (
        <div className="mt-3">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted">Next sales</p>
          <ol className="relative grid grid-cols-3 gap-2">
            <span className="absolute left-[16%] right-[16%] top-[7px] h-px bg-line" aria-hidden />
            {sales.map((s, i) => {
              const saving = s.expected_saving_pct ?? 0;
              return (
                <li key={s.key + s.start_date} className="relative flex flex-col items-center text-center">
                  <span
                    className={`z-10 h-3.5 w-3.5 rounded-full border-2 ${
                      i === 0 ? "border-highlight bg-highlight" : "border-highlight bg-card"
                    }`}
                    aria-hidden
                  />
                  <span className="mt-1.5 text-xs font-semibold leading-tight">{s.name}</span>
                  <span className="text-[11px] text-muted">
                    {s.is_live ? "Live now" : `${shortDate(s.start_date)} · in ${s.days_until}d`}
                  </span>
                  <span className="mt-0.5 text-xs font-semibold">~{rupees(s.predicted_price)}</span>
                  {saving > 0 && <span className="text-[11px] text-good">save {saving}%</span>}
                </li>
              );
            })}
          </ol>
        </div>
      )}
    </section>
  );
}
