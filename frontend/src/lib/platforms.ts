// Brand colours for store badges and chart lines.
// Chart colours are chosen to stay distinguishable from each other on both themes.

interface PlatformStyle {
  label: string;
  badge: string; // badge background
  text: string; // badge text
  chart: string; // chart line
}

const STYLES: Record<string, PlatformStyle> = {
  amazon: { label: "Amazon", badge: "#FF9900", text: "#111111", chart: "#FF9900" },
  flipkart: { label: "Flipkart", badge: "#2874F0", text: "#FFFFFF", chart: "#4C8DF6" },
  myntra: { label: "Myntra", badge: "#FF3F6C", text: "#FFFFFF", chart: "#FF3F6C" },
  croma: { label: "Croma", badge: "#00A99D", text: "#FFFFFF", chart: "#12B5A8" },
  reliance_digital: { label: "Reliance Digital", badge: "#E42529", text: "#FFFFFF", chart: "#C084FC" },
  vijay_sales: { label: "Vijay Sales", badge: "#8B1E3F", text: "#FFFFFF", chart: "#A3E635" },
  tata_cliq: { label: "Tata CLiQ", badge: "#DA1C5C", text: "#FFFFFF", chart: "#F472B6" },
  ajio: { label: "AJIO", badge: "#2C4152", text: "#FFFFFF", chart: "#94A3B8" },
  nykaa: { label: "Nykaa", badge: "#FC2779", text: "#FFFFFF", chart: "#FB7185" },
  jiomart: { label: "JioMart", badge: "#0078AD", text: "#FFFFFF", chart: "#38BDF8" },
  snapdeal: { label: "Snapdeal", badge: "#E40046", text: "#FFFFFF", chart: "#FDA4AF" },
  pepperfry: { label: "Pepperfry", badge: "#F16521", text: "#FFFFFF", chart: "#FB923C" },
  firstcry: { label: "FirstCry", badge: "#FF7043", text: "#FFFFFF", chart: "#FDBA74" },
  decathlon: { label: "Decathlon", badge: "#0082C3", text: "#FFFFFF", chart: "#7DD3FC" },
};

const FALLBACK_CHART = ["#FACC15", "#34D399", "#60A5FA", "#F97316", "#E879F9"];

export function platformStyle(slug: string, label?: string): PlatformStyle {
  return (
    STYLES[slug] ?? {
      label: label ?? slug.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
      badge: "#475569",
      text: "#FFFFFF",
      chart: FALLBACK_CHART[slug.length % FALLBACK_CHART.length],
    }
  );
}

export const CATEGORY_EMOJI: Record<string, string> = {
  mobiles: "📱",
  laptops: "💻",
  audio: "🎧",
  tv: "📺",
  fashion: "👕",
  footwear: "👟",
  appliances: "🏠",
  beauty: "💄",
  jewellery: "💍",
  watches: "⌚",
  bags: "👜",
  home: "🏡",
  kitchen: "🍳",
  furniture: "🛋️",
  toys: "🧸",
  baby: "🍼",
  sports: "⚽",
  cameras: "📷",
  tablets: "📱",
  gaming: "🎮",
  automotive: "🚗",
  tools: "🔧",
  stationery: "✏️",
  pets: "🐾",
  health: "🩺",
  electronics: "🔌",
  mobile_accessories: "🔌",
  computer_accessories: "⌨️",
};
