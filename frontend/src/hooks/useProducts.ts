"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { HistoryData, PlatformStatus } from "@/lib/types";

/** Which store adapters the backend has enabled (shown in the header). */
export function usePlatforms() {
  const [platforms, setPlatforms] = useState<PlatformStatus[] | null>(null);
  useEffect(() => {
    api.platforms().then(setPlatforms).catch(() => setPlatforms([]));
  }, []);
  return platforms;
}

/** Price history for a product, refetched when the range changes. */
export function usePriceHistory(productId: number | null, months: number, initial?: HistoryData) {
  const [data, setData] = useState<HistoryData | undefined>(initial);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!productId) return;
    if (initial && months === initial.months) {
      setData(initial);
      return;
    }
    let cancelled = false;
    setLoading(true);
    api
      .history(productId, months)
      .then((d) => !cancelled && (setData(d), setError(null)))
      .catch((e: Error) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [productId, months, initial]);

  return { data, loading, error };
}
