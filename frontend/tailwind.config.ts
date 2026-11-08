import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#F5F4EF",
        ink: "#1B2430",
        slate: "#5B6675",
        line: "#DDD9CF",
        // the brand colour is a CSS variable so each company can have its own (white-label)
        signal: { DEFAULT: "rgb(var(--brand) / <alpha-value>)", soft: "rgb(var(--brand-soft) / <alpha-value>)" },
        amber: { DEFAULT: "#B45309", soft: "#FBEBD7" },
        rust: { DEFAULT: "#B91C1C", soft: "#F9DFDF" },
        moss: { DEFAULT: "#3F6212", soft: "#E6EFD7" },
      },
      fontFamily: { sans: ['"Segoe UI"', "Inter", "system-ui", "Helvetica", "Arial", "sans-serif"] },
    },
  },
  plugins: [],
};
export default config;
