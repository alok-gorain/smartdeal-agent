"use client";

import { useEffect, useState } from "react";

const TOKENS = ["line", "muted", "ink", "card", "highlight"] as const;
type ThemeColors = Record<(typeof TOKENS)[number], string>;

const DARK_DEFAULTS: ThemeColors = {
  line: "rgb(46 61 99)",
  muted: "rgb(148 163 184)",
  ink: "rgb(230 236 245)",
  card: "rgb(22 33 62)",
  highlight: "rgb(0 210 255)",
};

function read(): ThemeColors {
  const style = getComputedStyle(document.documentElement);
  return Object.fromEntries(
    TOKENS.map((t) => [t, `rgb(${style.getPropertyValue(`--${t}`).trim() || "0 0 0"})`]),
  ) as ThemeColors;
}

/** Resolved theme colours for SVG charts (SVG attributes can't use CSS variables reliably). */
export function useThemeColors(): ThemeColors {
  const [colors, setColors] = useState<ThemeColors>(DARK_DEFAULTS);
  useEffect(() => {
    setColors(read());
    const observer = new MutationObserver(() => setColors(read()));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);
  return colors;
}
