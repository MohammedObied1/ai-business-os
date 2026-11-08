"use client";
import Link from "next/link";
import { useState } from "react";
import { api, download } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { date, money, num } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { DateRange, WhatsAppButton, useMonthRange } from "@/components/money";
import { Badge, Modal, PageTitle, StatCard, Table, Tabs, toast } from "@/components/ui";

const TABS = ["profit & loss", "vat", "who owes", "by employee", "by product", "by customer", "daily", "by branch", "cash flow", "stock value",
              "dead stock", "expiring", "pricing ideas", "warning signs", "cashier shifts"] as const;
type Tab = (typeof TABS)[number];
const DATED: Tab[] = ["profit & loss", "vat", "by employee", "by product", "by customer", "daily", "by branch"];
// tab -> the API "report" key used by /api/reports/export/{key} (only tabular reports can be exported as CSV)
const EXPORTABLE: Partial<Record<Tab, string>> = { "by employee": "sales-by-user", "by product": "sales-by-product", "by customer": "sales-by-customer",
  daily: "daily-sales", "who owes": "aging", "dead stock": "dead-stock" };

function Row({ label, value, strong, tone }: { label: string; value: string; strong?: boolean; tone?: "good" | "bad" }) {
  return <div className={`flex justify-between border-b border-line/60 py-2 ${strong ? "text-base font-semibold" : "text-sm"}`}><span>{label}</span><span className={tone === "good" ? "text-moss" : tone === "bad" ? "text-rust" : ""}>{value}</span></div>;
}

export default function Reports() {
  const { t } = useT();
  const { company, can } = useSession();
  const tabs = TABS.filter((x) => x !== "warning signs" || can("audit:read"));
  const [tab, setTab] = useState<Tab>("profit & loss");
  const r = useMonthRange();
  const qs = `start=${r.start}&end=${r.end}`;
  const path: Partial<Record<Tab, string>> = {
    "profit & loss": `/api/reports/pnl?${qs}`, vat: `/api/reports/vat?${qs}`, "who owes": "/api/reports/aging", "by employee": `/api/reports/sales-by-user?${qs}`,
    "by product": `/api/reports/sales-by-product?${qs}`, "by customer": `/api/reports/sales-by-customer?${qs}`, daily: `/api/reports/daily-sales?${qs}`,
    "stock value": "/api/inventory/valuation", expiring: "/api/inventory/expiring?days=90",
    "pricing ideas": "/api/insights/pricing", "warning signs": "/api/insights/risk?days=30", "cashier shifts": "/api/pos/shifts",
  };
  const path2 = { ...path, "by branch": `/api/reports/branch?${qs}`, "cash flow": "/api/reports/cashflow?months=6", "dead stock": "/api/reports/dead-stock?days=90" } as Record<Tab, string>;
  const { data } = useApi<any>(path2[tab], [tab, qs]);
  const anomalies = useApi<any[]>(tab === "warning signs" ? "/api/insights/anomalies?days=14" : null, [tab]);
  const [saveOpen, setSaveOpen] = useState(false);
  const [saveName, setSaveName] = useState("");
  const saved = useApi<any[]>(saveOpen ? "/api/reports/saved" : null, [saveOpen]);
  const exportCsv = () => download(`/api/reports/export/${EXPORTABLE[tab]}?${qs}`, `${EXPORTABLE[tab]}.csv`);
  const saveReport = async () => {
    if (!saveName.trim()) return;
    try { await api("/api/reports/saved", { method: "POST", json: { name: saveName.trim(), report: tab, params: { start: r.start, end: r.end } } });
      toast("Saved"); setSaveName(""); saved.reload(); } catch (e: any) { toast(e.message, "bad"); }
  };
  const openSaved = (s: any) => { const t2 = s.report as Tab; if (TABS.includes(t2)) setTab(t2); if (s.params?.start && s.params?.end) r.set(s.params.start, s.params.end); setSaveOpen(false); };
  const deleteSaved = async (id: number) => { try { await api(`/api/reports/saved/${id}`, { method: "DELETE" }); saved.reload(); } catch (e: any) { toast(e.message, "bad"); } };

  return (
    <>
      <PageTitle title={t("Reports")} help={t("Reports help")} actions={<div className="flex flex-wrap gap-2 print:hidden">
        <button className="btn-ghost" onClick={() => setSaveOpen(true)}>⭐ {t("Saved reports")}</button>
        {EXPORTABLE[tab] && <button className="btn-ghost" onClick={exportCsv}>⬇ CSV</button>}
        <button className="btn-ghost" onClick={() => window.print()}>🖨 {t("Print / PDF")}</button>
      </div>} />
      <Modal title={t("Saved reports")} open={saveOpen} onClose={() => setSaveOpen(false)}>
        <div className="mb-4 flex gap-2">
          <input className="input" placeholder={t("Name this view (e.g. {x})", { x: t(tab) })} value={saveName} onChange={(e) => setSaveName(e.target.value)} />
          <button className="btn-primary shrink-0" onClick={saveReport}>{t("Save current view")}</button>
        </div>
        <div className="divide-y divide-line">{(saved.data ?? []).map((s: any) => (
          <div key={s.id} className="flex items-center justify-between gap-3 py-2">
            <button className="text-start text-sm hover:text-signal" onClick={() => openSaved(s)}><b>{s.name}</b> <span className="text-xs text-slate">· {t(s.report)}</span></button>
            <button className="link-danger text-xs" onClick={() => deleteSaved(s.id)}>{t("Delete")}</button>
          </div>))}
          {saved.data?.length === 0 && <p className="py-3 text-sm text-slate">{t("No saved reports yet.")}</p>}
        </div>
      </Modal>
      <div className="print:hidden"><Tabs tabs={tabs} value={tab} onChange={setTab} /></div>
      {DATED.includes(tab) && <div className="mb-4 print:hidden"><DateRange start={r.start} end={r.end} onChange={r.set} /></div>}
      <div className="mb-3 hidden text-sm print:block">{company?.name} · {t(tab)} · {DATED.includes(tab) ? `${date(r.start)} – ${date(r.end)}` : date(new Date().toISOString())}</div>
      {!data ? <div className="text-sm text-slate">{t("Loading…")}</div> : <>
        {tab === "profit & loss" && (
          <div className="grid gap-6 lg:grid-cols-3">
            <div className="panel p-5 lg:col-span-2">
              <Row label={t("Sales (before VAT)")} value={money(data.sales, undefined, 2)} />
              <Row label={t("Returns")} value={`− ${money(data.returns, undefined, 2)}`} />
              <Row label={t("Net sales")} value={money(data.net_sales, undefined, 2)} strong />
              <Row label={t("Cost of goods sold")} value={`− ${money(data.cogs, undefined, 2)}`} />
              <Row label={`${t("Gross profit")} (${data.gross_margin_pct}%)`} value={money(data.gross_profit, undefined, 2)} strong />
              <div className="mt-3 text-sm font-medium text-slate">{t("Expenses")}</div>
              {data.expenses.map((e: any) => <Row key={e.category} label={`   ${t(e.category)}`} value={`− ${money(e.amount, undefined, 2)}`} />)}
              <Row label={t("Total expenses")} value={`− ${money(data.total_expenses, undefined, 2)}`} />
              <Row label={`${t("Net profit")} (${data.net_margin_pct}%)`} value={money(data.net_profit, undefined, 2)} strong tone={data.net_profit >= 0 ? "good" : "bad"} />
            </div>
            <div className="space-y-4">
              <StatCard label={t("Net sales")} value={money(data.net_sales)} />
              <StatCard label={t("Gross profit")} value={money(data.gross_profit)} note={`${data.gross_margin_pct}%`} />
              <StatCard label={t("Net profit")} value={money(data.net_profit)} tone={data.net_profit >= 0 ? "good" : "bad"} note={`${data.net_margin_pct}%`} />
            </div>
          </div>
        )}
        {tab === "vat" && (
          <div className="panel max-w-2xl p-5">
            <Row label={t("Taxable sales")} value={money(data.taxable_sales, undefined, 2)} />
            <Row label={t("VAT on sales (after returns)")} value={money(data.output_tax, undefined, 2)} />
            <Row label={t("VAT paid on purchases")} value={money(data.input_tax_purchases, undefined, 2)} />
            <Row label={t("VAT paid on expenses")} value={money(data.input_tax_expenses, undefined, 2)} />
            <Row label={data.tax_due >= 0 ? t("VAT to pay") : t("VAT refund due")} value={money(Math.abs(data.tax_due), undefined, 2)} strong tone={data.tax_due >= 0 ? "bad" : "good"} />
            <p className="mt-3 text-xs text-slate">{t("VAT report note")}</p>
          </div>
        )}
        {tab === "who owes" && (
          <div className="panel"><Table rows={data} empty={t("Nobody owes you anything.")} cols={[
            { h: t("Customer"), c: (x: any) => <Link className="font-medium hover:underline" href={`/customers/${x.customer_id}`}>{x.name}</Link> },
            { h: t("Not due yet"), c: (x: any) => x.current ? money(x.current) : "—", end: true },
            { h: "1-30", c: (x: any) => x.d30 ? money(x.d30) : "—", end: true },
            { h: "31-60", c: (x: any) => x.d60 ? money(x.d60) : "—", end: true },
            { h: "61-90", c: (x: any) => x.d90 ? <span className="text-amber">{money(x.d90)}</span> : "—", end: true },
            { h: "+90", c: (x: any) => x.older ? <span className="font-semibold text-rust">{money(x.older)}</span> : "—", end: true },
            { h: t("Total"), c: (x: any) => <b>{money(x.total, undefined, 2)}</b>, end: true },
            { h: "", c: (x: any) => <div className="print:hidden"><WhatsAppButton phone={x.phone} className="!px-3 !py-1 !text-xs"
                text={t("Reminder message", { name: x.name, amount: money(x.total, undefined, 2), company: company?.name ?? "" })} /></div> },
          ]} /></div>
        )}
        {tab === "by employee" && <div className="panel"><Table rows={data} cols={[
          { h: t("Employee"), c: (x: any) => x.name }, { h: t("Orders"), c: (x: any) => x.orders, end: true },
          { h: t("Net sales"), c: (x: any) => money(x.revenue), end: true }, { h: t("Profit"), c: (x: any) => money(x.profit), end: true },
        ]} /></div>}
        {tab === "by product" && <div className="panel"><Table rows={data} cols={[
          { h: t("Product"), c: (x: any) => x.name }, { h: t("Category"), c: (x: any) => x.category ?? "—" }, { h: t("Quantity"), c: (x: any) => num(x.quantity, 2), end: true },
          { h: t("Net sales"), c: (x: any) => money(x.revenue), end: true }, { h: t("Profit"), c: (x: any) => money(x.profit), end: true }, { h: t("Margin"), c: (x: any) => `${x.margin_pct}%`, end: true },
        ]} /></div>}
        {tab === "by customer" && <div className="panel"><Table rows={data} cols={[
          { h: t("Customer"), c: (x: any) => x.name }, { h: t("Orders"), c: (x: any) => x.orders, end: true }, { h: t("Net sales"), c: (x: any) => money(x.revenue), end: true },
        ]} /></div>}
        {tab === "daily" && <div className="panel"><Table rows={data} cols={[
          { h: t("Date"), c: (x: any) => date(x.date) }, { h: t("Orders"), c: (x: any) => x.orders, end: true }, { h: t("Net sales"), c: (x: any) => money(x.net_sales, undefined, 2), end: true },
          { h: t("VAT"), c: (x: any) => money(x.tax, undefined, 2), end: true }, { h: t("Money received"), c: (x: any) => money(x.received, undefined, 2), end: true },
        ]} /></div>}
        {tab === "stock value" && <>
          <div className="mb-4 grid gap-4 sm:grid-cols-2">
            <StatCard label={t("Stock value at cost")} value={money(data.total_cost)} />
            <StatCard label={t("Stock value at sale price")} value={money(data.total_sale)} note={`${t("Expected profit")}: ${money(data.total_sale - data.total_cost)}`} tone="good" />
          </div>
          <div className="panel"><Table rows={data.items} cols={[
            { h: t("Product"), c: (x: any) => x.name }, { h: t("Quantity"), c: (x: any) => num(x.quantity, 2), end: true }, { h: t("Cost"), c: (x: any) => money(x.cost_price, undefined, 2), end: true },
            { h: t("Value at cost"), c: (x: any) => money(x.cost_value, undefined, 2), end: true }, { h: t("Value at sale price"), c: (x: any) => money(x.sale_value, undefined, 2), end: true },
          ]} /></div>
        </>}
        {tab === "by branch" && <>
          <h3 className="mb-2 text-sm font-semibold text-slate">{t("By branch")}</h3>
          <div className="panel mb-4"><Table rows={data.by_branch} empty={t("No branches set up yet.")} cols={[
            { h: t("Branch"), c: (x: any) => x.name }, { h: t("Orders"), c: (x: any) => x.orders, end: true }, { h: t("Net sales"), c: (x: any) => money(x.revenue), end: true },
          ]} /></div>
          <h3 className="mb-2 text-sm font-semibold text-slate">{t("By warehouse")}</h3>
          <div className="panel"><Table rows={data.by_warehouse} cols={[
            { h: t("Warehouse"), c: (x: any) => x.name }, { h: t("Orders"), c: (x: any) => x.orders, end: true }, { h: t("Net sales"), c: (x: any) => money(x.revenue), end: true },
          ]} /></div>
        </>}
        {tab === "cash flow" && <div className="panel"><Table rows={data} cols={[
          { h: t("Month"), c: (x: any) => x.month }, { h: t("Money in"), c: (x: any) => money(x.cash_in, undefined, 2), end: true },
          { h: t("Money out"), c: (x: any) => money(x.cash_out, undefined, 2), end: true },
          { h: t("Net"), c: (x: any) => <span className={x.net >= 0 ? "text-moss" : "text-rust"}>{money(x.net, undefined, 2)}</span>, end: true },
        ]} /></div>}
        {tab === "dead stock" && <>
          <p className="mb-3 text-sm text-slate">{t("Dead stock help")}</p>
          <div className="panel"><Table rows={data} empty={t("Nothing looks stuck. Every product in stock has moved recently.")} cols={[
            { h: t("Product"), c: (x: any) => <Link className="text-signal" href={`/inventory?product=${x.product_id}`}>{x.name}</Link> },
            { h: t("Category"), c: (x: any) => x.category ?? "—" }, { h: t("In stock"), c: (x: any) => num(x.on_hand, 2), end: true },
            { h: t("Value tied up"), c: (x: any) => <b>{money(x.value, undefined, 2)}</b>, end: true },
            { h: t("Last sold"), c: (x: any) => x.last_sold ? date(x.last_sold) : t("Never") },
          ]} /></div>
        </>}
        {tab === "expiring" && <div className="panel"><Table rows={data} empty={t("Nothing expires in the next 90 days.")} cols={[
          { h: t("Product"), c: (x: any) => x.product }, { h: t("Batch"), c: (x: any) => x.batch || "—" }, { h: t("Warehouse"), c: (x: any) => x.warehouse },
          { h: t("Expiry date"), c: (x: any) => <span className={x.days_left < 0 ? "font-semibold text-rust" : x.days_left <= 30 ? "text-amber" : ""}>{date(x.expiry_date)}</span> },
          { h: t("Days left"), c: (x: any) => x.days_left < 0 ? <span className="text-rust">{t("expired")}</span> : x.days_left, end: true },
          { h: t("Quantity"), c: (x: any) => num(x.quantity, 2), end: true }, { h: t("Value at cost"), c: (x: any) => money(x.value), end: true },
        ]} /></div>}
        {tab === "pricing ideas" && <>
          <p className="mb-3 text-sm text-slate">{t("Pricing ideas help")}</p>
          <div className="panel"><Table rows={data} empty={t("No pricing problems found. Prices look healthy.")} cols={[
            { h: t("Product"), c: (x: any) => <Link className="text-signal" href={`/inventory?product=${x.product_id}`}>{x.name}</Link> },
            { h: t("Idea"), c: (x: any) => <Badge tone={x.kind === "below_cost" ? "bad" : x.kind === "raise" ? "good" : "warn"}>{t(`price.${x.kind}`)}</Badge> },
            { h: t("Cost"), c: (x: any) => money(x.cost, undefined, 2), end: true }, { h: t("Price now"), c: (x: any) => money(x.price, undefined, 2), end: true },
            { h: t("Suggested"), c: (x: any) => <b>{money(x.suggested_price, undefined, 2)}</b>, end: true },
            { h: t("Margin"), c: (x: any) => `${x.margin_pct}% (${t("category")} ${x.category_margin_pct}%)`, end: true },
            { h: t("Why it matters"), c: (x: any) => <span className="text-xs text-slate">{x.kind === "raise" ? t("+{m} profit a month", { m: money(x.extra_profit_month) }) : x.kind === "slow" ? t("{m} of money stuck in stock", { m: money(x.tied_up_value) }) : t("You lose money on every sale")}</span> },
          ]} /></div>
        </>}
        {tab === "warning signs" && <>
          <p className="mb-3 text-sm text-slate">{t("Warning signs help")}</p>
          {!!anomalies.data?.length && <div className="mb-5">
            <h3 className="mb-2 text-sm font-semibold text-slate">{t("Unusual days")}</h3>
            <div className="panel"><Table rows={anomalies.data} cols={[
              { h: t("Date"), c: (a: any) => date(a.date) }, { h: t("Metric"), c: (a: any) => t(a.metric) },
              { h: t("What happened"), c: (a: any) => <Badge tone={a.direction === "spike" ? "warn" : "bad"}>{a.direction === "spike" ? t("Spike") : t("Drop")}</Badge> },
              { h: t("Value"), c: (a: any) => money(a.value, undefined, 2), end: true }, { h: t("Usually around"), c: (a: any) => money(a.baseline_avg, undefined, 2), end: true },
            ]} /></div>
          </div>}
          <div className="panel"><Table rows={data} empty={t("No activity in the last 30 days.")} cols={[
            { h: t("Employee"), c: (x: any) => <span className="font-medium">{x.name}</span> }, { h: t("Sales"), c: (x: any) => x.orders, end: true },
            { h: t("Cancelled"), c: (x: any) => x.cancelled, end: true }, { h: t("Avg. discount"), c: (x: any) => `${x.avg_discount}%`, end: true },
            { h: t("Below cost"), c: (x: any) => x.below_cost_lines, end: true }, { h: t("Refunds"), c: (x: any) => `${x.refunds} · ${money(x.refund_amount)}`, end: true },
            { h: t("Cash difference"), c: (x: any) => <span className={x.cash_diff < 0 ? "text-rust" : ""}>{money(x.cash_diff, undefined, 2)}</span>, end: true },
            { h: t("Check"), c: (x: any) => x.flags.length ? <div className="flex flex-wrap gap-1">{x.flags.map((f: string) => <Badge key={f} tone="warn">{t(`risk.${f}`)}</Badge>)}</div> : <Badge tone="good">✓</Badge> },
          ]} /></div>
        </>}
        {tab === "cashier shifts" && <div className="panel"><Table rows={data} empty={t("No shifts yet. Cashiers open a shift from the point of sale.")} cols={[
          { h: t("Cashier"), c: (x: any) => x.user }, { h: t("Opened"), c: (x: any) => new Date(x.opened_at + "Z").toLocaleString() },
          { h: t("Closed"), c: (x: any) => x.closed_at ? new Date(x.closed_at + "Z").toLocaleString() : <Badge tone="info">{t("Open now")}</Badge> },
          { h: t("Opening cash"), c: (x: any) => money(x.opening_float, undefined, 2), end: true }, { h: t("Expected"), c: (x: any) => money(x.expected_cash, undefined, 2), end: true },
          { h: t("Counted"), c: (x: any) => x.counted_cash == null ? "—" : money(x.counted_cash, undefined, 2), end: true },
          { h: t("Difference"), c: (x: any) => x.difference == null ? "—" : <span className={Math.abs(x.difference) >= 1 ? "font-semibold text-rust" : "text-moss"}>{money(x.difference, undefined, 2)}</span>, end: true },
        ]} /></div>}
      </>}
    </>
  );
}
