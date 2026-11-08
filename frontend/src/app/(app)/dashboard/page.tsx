"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Line, LineChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { date, money, monthName, num, pct } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { PageTitle, StatCard, Table, toast } from "@/components/ui";

type W = { type: string; w: number };
const SPAN = ["", "lg:col-span-1", "lg:col-span-2", "lg:col-span-3", "lg:col-span-4"];

/** Customizable dashboard: each person picks, orders and sizes their widgets; the server only sends what they may see. */
export default function Dashboard() {
  const { t, lang } = useT();
  const mine = useApi<{ widgets: W[]; data: Record<string, any> }>("/api/dashboards/mine");
  const catalog = useApi<{ type: string; w: number; display: string }[]>("/api/dashboards/widgets");
  const [editing, setEditing] = useState(false);
  const [layout, setLayout] = useState<W[]>([]);
  useEffect(() => { if (mine.data) setLayout(mine.data.widgets); }, [mine.data]);
  const d = mine.data?.data ?? {};
  const rtl = lang === "ar";

  const move = (i: number, dir: -1 | 1) => { const j = i + dir; if (j < 0 || j >= layout.length) return; const x = [...layout]; [x[i], x[j]] = [x[j], x[i]]; setLayout(x); };
  const resize = (i: number) => setLayout(layout.map((w, j) => (j === i ? { ...w, w: (w.w % 4) + 1 } : w)));
  const remove = (i: number) => setLayout(layout.filter((_, j) => j !== i));
  const add = (type: string) => setLayout([...layout, { type, w: catalog.data?.find((c) => c.type === type)?.w ?? 1 }]);
  const save = async () => {
    try { await api("/api/dashboards/mine", { method: "PUT", json: layout }); toast("Saved"); setEditing(false); mine.reload(); }
    catch (e: any) { toast(e.message, "bad"); }
  };
  const growth = (g: number | null | undefined) => (g == null ? undefined : `${pct(g)} ${t("vs last month")}`);
  const tone = (g: number | null | undefined) => (g == null ? "neutral" : g >= 0 ? "good" : "bad") as "good" | "bad" | "neutral";

  const body = (w: W) => {
    const x = d[w.type];
    if (!x) return <div className="panel p-4 text-sm text-slate">{editing ? t("Save to load this widget") : t("Loading…")}</div>;
    switch (w.type) {
      case "sales_today": return <StatCard label={t("Sales today")} value={money(x.value)} note={t("{n} sales", { n: x.note })} />;
      case "sales_month": return <StatCard label={t("Sales this month")} value={money(x.value)} note={growth(x.growth)} tone={tone(x.growth)} />;
      case "profit_month": return <StatCard label={t("Profit this month")} value={money(x.value)} note={growth(x.growth)} tone={tone(x.growth)} />;
      case "expenses_month": return <StatCard label={t("Expenses this month")} value={money(x.value)} />;
      case "receivables": return <StatCard label={t("Customers owe you")} value={money(x.value)} />;
      case "payables": return <StatCard label={t("You owe suppliers")} value={money(x.value)} />;
      case "cash": return <StatCard label={t("Cash")} value={money(x.value)} />;
      case "bank": return <StatCard label={t("Bank")} value={money(x.value)} />;
      case "inventory_value": return <StatCard label={t("Goods in stock")} value={money(x.value)} />;
      case "sales_chart": return (
        <div className="panel p-4">
          <h2 className="mb-3 text-base font-semibold">{t("Sales, last 12 months")}</h2>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={x.series}>
              <CartesianGrid stroke="#EEECE5" vertical={false} />
              <XAxis dataKey="month" reversed={rtl} tick={{ fontSize: 11 }} tickFormatter={monthName} />
              <YAxis orientation={rtl ? "right" : "left"} tick={{ fontSize: 11 }} tickFormatter={(v) => `${Math.round(v / 1000)}k`} width={40} />
              <Tooltip formatter={(v: number, n: string) => [money(v), t(n)]} labelFormatter={monthName} />
              <Legend formatter={(v) => t(v)} />
              <Line type="monotone" dataKey="revenue" name="revenue" stroke="#0F766E" strokeWidth={2} dot={false} />
              {x.series?.[0]?.profit !== undefined && <Line type="monotone" dataKey="profit" name="profit" stroke="#B45309" strokeWidth={2} dot={false} />}
            </LineChart>
          </ResponsiveContainer>
        </div>);
      default: {
        const tables: Record<string, [string, any[]]> = {
          overdue_invoices: [t("Late invoices"), [{ h: t("Invoice"), c: (r: any) => <Link className="text-signal" href={`/sales/invoices/${r.id}`}>{r.number}</Link> },
            { h: t("Due"), c: (r: any) => date(r.due_date) }, { h: t("Balance"), c: (r: any) => money(r.balance), end: true }]],
          low_stock: [t("Running low"), [{ h: t("Product"), c: (r: any) => r.name }, { h: t("In stock"), c: (r: any) => num(r.stock), end: true }, { h: t("Minimum"), c: (r: any) => num(r.min_stock), end: true }]],
          top_products: [t("Top products this month"), [{ h: t("Product"), c: (r: any) => r.name }, { h: t("Revenue"), c: (r: any) => money(r.revenue), end: true }]],
          top_customers: [t("Top customers this month"), [{ h: t("Customer"), c: (r: any) => r.name }, { h: t("Revenue"), c: (r: any) => money(r.revenue), end: true }]],
          sales_by_employee: [t("Sales by employee"), [{ h: t("Employee"), c: (r: any) => r.name }, { h: t("Orders"), c: (r: any) => r.orders, end: true }, { h: t("Revenue"), c: (r: any) => money(r.revenue), end: true }]],
        };
        const [title, cols] = tables[w.type] ?? [w.type, []];
        return <div className="panel"><h2 className="card-title p-4 pb-0">{title}</h2><Table rows={x.rows} pageSize={10} cols={cols} empty={t("Nothing here.")} /></div>;
      }
    }
  };

  const available = (catalog.data ?? []).filter((c) => !layout.some((w) => w.type === c.type));
  return (
    <>
      <PageTitle title={t("Dashboard")} help={t("Dashboard builder help")} actions={editing
        ? <><button className="btn-ghost" onClick={() => { setLayout(mine.data?.widgets ?? []); setEditing(false); }}>{t("Cancel")}</button><button className="btn-primary" onClick={save}>{t("Save layout")}</button></>
        : <button className="btn-ghost" onClick={() => setEditing(true)}>✎ {t("Customize")}</button>} />
      {editing && available.length > 0 && <div className="panel mb-4 p-3">
        <div className="mb-2 text-sm font-medium">{t("Add a widget")}</div>
        <div className="flex flex-wrap gap-2">{available.map((c) => <button key={c.type} className="rounded-full border border-line px-3 py-1 text-sm hover:border-signal hover:bg-signal-soft" onClick={() => add(c.type)}>+ {t(`widget.${c.type}`)}</button>)}</div>
      </div>}
      {!layout.length && <div className="panel p-10 text-center text-sm text-slate">{t("Your dashboard is empty. Press Customize to add widgets.")}</div>}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {layout.map((w, i) => (
          <div key={`${w.type}-${i}`} className={`relative ${SPAN[w.w]} ${w.w >= 2 ? "sm:col-span-2" : ""}`}>
            {editing && <div className="absolute end-2 top-2 z-10 flex gap-1 rounded-md bg-white/90 p-0.5 text-xs shadow">
              <button className="px-1.5" title={t("Move")} onClick={() => move(i, -1)}>{rtl ? "→" : "←"}</button>
              <button className="px-1.5" title={t("Move")} onClick={() => move(i, 1)}>{rtl ? "←" : "→"}</button>
              <button className="px-1.5" title={t("Size")} onClick={() => resize(i)}>⇔ {w.w}</button>
              <button className="px-1.5 text-rust" title={t("Remove")} onClick={() => remove(i)}>✕</button>
            </div>}
            {body(w)}
          </div>
        ))}
      </div>
    </>
  );
}
