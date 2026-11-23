import typography from "@tailwindcss/typography";
import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Theme tokens are CSS variables (see globals.css) so light/dark switch at runtime
        bg: "rgb(var(--bg) / <alpha-value>)",
        card: "rgb(var(--card) / <alpha-value>)",
        raised: "rgb(var(--raised) / <alpha-value>)",
        accent: "rgb(var(--accent) / <alpha-value>)",
        highlight: "rgb(var(--highlight) / <alpha-value>)",
        ink: "rgb(var(--ink) / <alpha-value>)",
        muted: "rgb(var(--muted) / <alpha-value>)",
        line: "rgb(var(--line) / <alpha-value>)",
        good: "rgb(var(--good) / <alpha-value>)",
        warn: "rgb(var(--warn) / <alpha-value>)",
        bad: "rgb(var(--bad) / <alpha-value>)",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
      },
      keyframes: {
        pulseDot: { "0%, 80%, 100%": { opacity: "0.25" }, "40%": { opacity: "1" } },
        fadeIn: { from: { opacity: "0", transform: "translateY(4px)" }, to: { opacity: "1", transform: "none" } },
      },
      animation: {
        pulseDot: "pulseDot 1.2s infinite ease-in-out",
        fadeIn: "fadeIn 0.25s ease-out",
      },
    },
  },
  plugins: [typography],
};

export default config;
