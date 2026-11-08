/** White-label: set the app's accent colour from a company's brand colour ("#RRGGBB"). */
const DEFAULT = "#0F766E";

function rgb(hex: string): [number, number, number] | null {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export function applyBrand(hex?: string | null) {
  if (typeof document === "undefined") return;
  const c = rgb(hex || DEFAULT) ?? rgb(DEFAULT)!;
  const soft = c.map((v) => Math.round(v + (255 - v) * 0.88));
  document.documentElement.style.setProperty("--brand", c.join(" "));
  document.documentElement.style.setProperty("--brand-soft", soft.join(" "));
}
