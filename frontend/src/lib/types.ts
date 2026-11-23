// Shapes returned by the SmartDeal API (mirrors backend/services/*)

export interface Deal {
  id: number;
  platform: string;
  offer_kind: "coupon" | "bank_offer";
  code: string | null;
  title: string;
  description: string | null;
  discount_type: "percent" | "flat" | "cashback";
  discount_value: number;
  min_order_value: number | null;
  max_discount: number | null;
  bank_name: string | null;
  card_type: string | null;
  categories: string[] | null;
  valid_until: string | null;
  source_url: string | null;
  saving?: number;
  effective_price?: number;
}

export interface Offer {
  platform: string;
  platform_label: string;
  name: string;
  price: number;
  mrp: number | null;
  rating: number | null;
  review_count: number | null;
  image_url: string | null;
  url: string | null;
  brand: string | null;
  category: string | null;
  in_stock: boolean;
  seller: string | null;
  delivery_info: string | null;
  source: "live" | "demo";
  via: string | null;
  product_id: number | null;
  discount_percent: number | null;
  trusted?: boolean;
  best_deal?: Deal | null;
  effective_price?: number;
}

export interface ProductGroup {
  product_id: number | null;
  name: string;
  brand: string | null;
  category: string | null;
  image_url: string | null;
  best_price: number;
  best_platform: string;
  best_platform_label: string;
  best_effective_price?: number;
  best_effective_platform?: string;
  mrp: number | null;
  rating: number | null;
  review_count: number | null;
  max_saving: number;
  store_count: number;
  is_demo: boolean;
  trusted?: boolean;
  offers: Offer[];
}

export interface ProductsData {
  title: string;
  query: string;
  groups: ProductGroup[];
  errors: Record<string, string>;
  searched?: string[];
  total_found: number;
  filters?: Record<string, unknown>;
}

export interface ComparisonRow {
  platform: string;
  platform_label: string;
  price: number;
  mrp: number | null;
  rating: number | null;
  review_count: number | null;
  delivery_info: string | null;
  in_stock: boolean;
  url: string | null;
  trusted?: boolean;
  best_deal: Deal | null;
  effective_price: number;
}

export interface ComparisonData {
  product_id: number | null;
  name: string;
  image_url: string | null;
  is_demo: boolean;
  rows: ComparisonRow[];
  best_platform: string;
  best_platform_label: string;
  savings: { platform: string; platform_label: string; amount: number }[];
}

export interface HistoryRow {
  month: string;
  label: string;
  lowest: number | null;
  [platform: string]: string | number | null;
}

export interface HistoryData {
  product_id: number;
  product_name: string;
  months: number;
  platforms: { slug: string; label: string }[];
  series: HistoryRow[];
  sale_events: { label: string; names: string[] }[];
  lowest: { price: number; platform: string; date: string } | null;
  highest: { price: number; platform: string; date: string } | null;
  stats: Record<string, { label: string; min: number; max: number; avg: number; latest: number }>;
  trend: { change_pct_3m: number; direction: "up" | "down" | "flat" } | null;
  data_points: number;
  days_tracked?: number;
  tracking_since?: string | null;
  from_google?: boolean;
  tracked_since?: string | null;
  is_synthetic: boolean;
}

export type Verdict = "FAKE" | "HIGH" | "MINOR" | "GENUINE" | "REGULAR" | "UNKNOWN";

export interface DiscountResult {
  product_id: number;
  product_name: string;
  platform: string;
  platform_label: string;
  current_price: number;
  mrp: number | null;
  verdict: Verdict;
  label: string;
  explanation: string;
  median_90d?: number;
  lowest_90d?: number;
  highest_90d?: number;
  actual_discount_pct?: number;
  claimed_discount_pct?: number;
  mrp_inflation_pct?: number;
  history_days: number;
  confidence: string;
  is_synthetic?: boolean;
}

export interface DiscountData {
  product_id: number;
  product_name: string;
  primary: DiscountResult;
  by_platform: DiscountResult[];
}

export interface UpcomingSale {
  key: string;
  name: string;
  start_date: string;
  end_date: string;
  days_until: number;
  is_live: boolean;
  platforms: string[];
  typical_discount_pct: number;
  predicted_price: number;
  expected_saving?: number;
  expected_saving_pct?: number;
  based_on?: string;
}

export interface TimingData {
  product_id: number;
  product_name: string;
  current_price: number;
  current_platform: string;
  action: "BUY_NOW" | "WAIT" | "UNKNOWN";
  label: string;
  reason: string;
  wait_days?: number;
  avg_price?: number;
  lowest_ever?: number;
  lowest_ever_date?: string;
  cheapest_month?: string;
  upcoming_sales: UpcomingSale[];
  confidence: string;
  is_synthetic?: boolean;
}

export interface CouponsData {
  platform: string | null;
  bank_name: string | null;
  price: number | null;
  items: Deal[];
}

export type Block =
  | { kind: "products"; data: ProductsData }
  | { kind: "comparison"; data: ComparisonData }
  | { kind: "history"; data: HistoryData }
  | { kind: "discount"; data: DiscountData }
  | { kind: "timing"; data: TimingData }
  | { kind: "coupons"; data: CouponsData };

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "error";
  content: string;
  blocks?: Block[];
}

export type ServerEvent =
  | { type: "thinking"; content: string }
  | { type: "response"; content: string; blocks: Block[] }
  | { type: "error"; content: string };

export interface PlatformStatus {
  slug: string;
  label: string;
  kind: "direct" | "aggregator" | "catalog";
  enabled: boolean;
  mode: string;
}
