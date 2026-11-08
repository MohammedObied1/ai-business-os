// Western digits in both languages; month names and currency placement follow the UI language.
let locale = "ar-u-nu-latn";
let currency = "ILS";
export const setFormatLang = (lang: "ar" | "en") => { locale = lang === "ar" ? "ar-u-nu-latn" : "en"; };
/** The signed-in company's currency, used when money() is called without one. */
export const setFormatCurrency = (cur: string | null | undefined) => { if (cur) currency = cur; };

export const money = (n: number | null | undefined, cur?: string, decimals = 0) => {
  if (n == null) return "—";
  try { return new Intl.NumberFormat(locale, { style: "currency", currency: cur ?? currency, maximumFractionDigits: decimals, minimumFractionDigits: decimals }).format(n); }
  catch { return `${num(n, decimals)} ${cur ?? currency}`; }
};
export const num = (n: number | null | undefined, d = 0) => (n == null ? "—" : new Intl.NumberFormat(locale, { maximumFractionDigits: d }).format(n));
export const pct = (n: number | null | undefined) => (n == null ? "—" : `${n > 0 ? "+" : ""}${n.toFixed(1)}%`);
export const date = (s: string | null | undefined) => (s ? new Date(s).toLocaleDateString(locale, { day: "numeric", month: "short", year: "numeric" }) : "—");
export const monthName = (ym: string) => new Date(`${ym}-01T00:00:00`).toLocaleDateString(locale, { month: "short" });
