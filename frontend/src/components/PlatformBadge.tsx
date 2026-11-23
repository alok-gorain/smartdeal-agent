import { platformStyle } from "@/lib/platforms";

export default function PlatformBadge({ slug, label, size = "sm" }: { slug: string; label?: string; size?: "xs" | "sm" }) {
  const s = platformStyle(slug, label);
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded-md font-semibold ${
        size === "xs" ? "px-1.5 py-0.5 text-[10px]" : "px-2 py-0.5 text-xs"
      }`}
      style={{ backgroundColor: s.badge, color: s.text }}
    >
      {label ?? s.label}
    </span>
  );
}
