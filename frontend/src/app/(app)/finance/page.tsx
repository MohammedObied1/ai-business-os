"use client";
import { useRef, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, download, upload } from "@/lib/api";
import { Attachments } from "@/components/Attachments";
import { EXPENSE_CATEGORIES } from "@/lib/constants";
import { useSession } from "@/lib/session";
import { useApi, usePaged } from "@/lib/hooks";
import { date, money, monthName } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { Badge, ErrorNote, Field, Modal, PageTitle, PagedTable, StatCard, Table, toast, useForm } from "@/components/ui";


export default function Money() {
  const { t, lang } = useT();
  const { can } = useSession();
  const [editing, setEditing] = useState<any>(null);
  const summary = useApi<any>("/api/finance/summary");
  const cashflow = useApi<any[]>("/api/finance/cashflow?months=6");
  const expenses = usePaged<any>("/api/finance/expenses");
  const [receipt, setReceipt] = useState<File | null>(null);
  const [reading, setReading] = useState(false);
  const receiptInput = useRef<HTMLInputElement>(null);
  const byCat = useApi<any[]>("/api/finance/expenses-by-category");
  const report = useApi<any>("/api/reports/finance");
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const today = () => new Date().toISOString().slice(0, 10);
  const f = useForm({ category: "Rent", description: "", amount: 0, expense_date: today(), account_id: 0, tax_amount: 0 });
  const { data: accounts } = useApi<any[]>("/api/accounts");
  const s = summary.data;
  const rtl = lang === "ar";
  const flowName = (n: string) => (n === "cash_in" ? t("Money in") : t("Money out"));

  const reloadAll = () => { summary.reload(); expenses.reload(); byCat.reload(); cashflow.reload(); };
  const openExpense = (x: any = null) => {
    setError(null); setEditing(x); setReceipt(null);
    f.setV(x ? { category: x.category, description: x.description ?? "", amount: x.amount, expense_date: x.expense_date, account_id: x.account_id ?? 0, tax_amount: x.tax_amount ?? 0 }
      : { category: "Rent", description: "", amount: 0, expense_date: today(), account_id: accounts?.find((a) => a.kind === "cash")?.id ?? 0, tax_amount: 0 });
    setOpen(true);
  };
  const save = async () => {
    setError(null);
    try {
      const r = await api(editing ? `/api/finance/expenses/${editing.id}` : "/api/finance/expenses", { method: editing ? "PATCH" : "POST", json: { ...f.v, account_id: +f.v.account_id || null } });
      if (receipt && r?.id) await upload(`/api/attachments?entity=expense&entity_id=${r.id}`, receipt).catch(() => {});
      setOpen(false); reloadAll();
      toast(r?.approval_status === "pending" ? t("Saved. Waiting for a manager's approval.") : t("Saved"));
    } catch (e: any) { setError(e.message); }
  };
  // AI reads a photo of the receipt and fills the form
  const readReceipt = async (file: File | undefined) => {
    if (!file) return;
    setReceipt(file); setReading(true); setError(null);
    try {
      const r = await upload("/api/ai/read-receipt", file);
      f.setV({ ...f.v, category: EXPENSE_CATEGORIES.includes(r.category) ? r.category : "Other", amount: r.total || f.v.amount, tax_amount: r.tax_amount || 0,
        expense_date: /^\d{4}-\d{2}-\d{2}$/.test(r.date) ? r.date : f.v.expense_date, description: [r.vendor, r.description].filter(Boolean).join(" — ") });
      toast("Filled from the receipt. Check it before saving.");
    } catch (e: any) { setError(e.message); } finally { setReading(false); if (receiptInput.current) receiptInput.current.value = ""; }
  };
  const remove = async (x: any) => {
    if (!confirm(t("Delete this expense?"))) return;
    try { await api(`/api/finance/expenses/${x.id}`, { method: "DELETE" }); toast("Deleted"); reloadAll(); } catch (e: any) { toast(e.message, "bad"); }
  };
  if (summary.error) return <div className="text-rust">{summary.error}</div>;

  return (
    <>
      <PageTitle title={t("Expenses")} help={t("Money help")} actions={<>
        <button className="btn-ghost" onClick={() => download(`/api/data/export/expenses?lang=${lang}`).catch((e) => toast(e.message, "bad"))}>⬇ {t("Excel")}</button>
        {can("finance:write") && <button className="btn-primary" onClick={() => openExpense()}>+ {t("Add expense")}</button>}</>} />
      {s && <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label={t("Revenue")} value={money(s.revenue)} note={`${t("Gross profit")}: ${money(s.gross_profit)}`} />
        <StatCard label={t("Expenses")} value={money(s.expenses)} />
        <StatCard label={t("Net profit")} value={money(s.net_profit)} tone={s.net_profit >= 0 ? "good" : "bad"} note={t("{p}% profit", { p: s.margin_pct })} />
        <StatCard label={t("Customers owe you")} value={money(s.receivables)} note={`${t("You owe suppliers")}: ${money(s.payables)}`} />
      </div>}
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <div className="panel p-4"><h2 className="mb-3 text-base font-semibold">{t("Money in and out, last 6 months")}</h2>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={cashflow.data ?? []}>
              <CartesianGrid stroke="#EEECE5" vertical={false} />
              <XAxis dataKey="month" reversed={rtl} tick={{ fontSize: 11 }} tickFormatter={monthName} />
              <YAxis orientation={rtl ? "right" : "left"} tick={{ fontSize: 11 }} tickFormatter={(v) => `${Math.round(v / 1000)}k`} width={40} />
              <Tooltip formatter={(v: number, n: string) => [money(v), flowName(n)]} labelFormatter={monthName} />
              <Legend formatter={flowName} />
              <Bar dataKey="cash_in" fill="#0F766E" radius={[4, 4, 0, 0]} />
              <Bar dataKey="cash_out" fill="#B45309" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="panel"><h2 className="card-title mb-2">{t("Expenses by type, this month")}</h2><Table rows={byCat.data} cols={[{ h: t("Type"), c: (r: any) => t(r.category) }, { h: t("Amount"), c: (r: any) => money(r.amount), end: true }]} /></div>
      </div>
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <div className="panel"><h2 className="card-title mb-2">{t("Late invoices")}</h2><div className="max-h-80 overflow-y-auto"><Table rows={report.data?.overdue ?? null} empty={t("No late invoices.")} cols={[{ h: t("Invoice"), c: (r: any) => r.number }, { h: t("Due"), c: (r: any) => date(r.due_date) }, { h: t("Balance"), c: (r: any) => money(r.balance), end: true }]} /></div></div>
        <div className="panel"><h2 className="card-title mb-2">{t("Customers who owe you")}</h2><div className="max-h-80 overflow-y-auto"><Table rows={report.data?.customers_owing ?? null} cols={[{ h: t("Customer"), c: (r: any) => r.name }, { h: t("Balance"), c: (r: any) => money(r.balance), end: true }]} /></div></div>
      </div>
      <h2 className="mb-3 mt-8 text-lg font-semibold">{t("All expenses")}</h2>
      <div className="panel"><PagedTable paged={expenses} cols={[{ h: t("Date"), c: (r: any) => date(r.expense_date) }, { h: t("Type"), c: (r: any) => t(r.category) }, { h: t("Description"), c: (r: any) => r.description ?? "—" }, { h: t("Amount"), c: (r: any) => money(r.amount, undefined, 2), end: true },
        { h: t("Approval"), c: (r: any) => r.approval_status && r.approval_status !== "approved" ? <Badge tone={r.approval_status === "pending" ? "warn" : "bad"}>{t(`approval.${r.approval_status}`)}</Badge> : "" },
        { h: "", c: (r: any) => can("finance:write") && <div className="flex justify-end gap-1"><button className="link" onClick={() => openExpense(r)}>{t("Edit")}</button><button className="link-danger" onClick={() => remove(r)}>{t("Delete")}</button></div> }]} /></div>
      <Modal title={editing ? t("Edit expense") : t("Add expense")} open={open} onClose={() => setOpen(false)} onSave={save} saveLabel={t("Save expense")}>
        <ErrorNote error={error} />
        {!editing && <div className="mb-4 rounded-lg border border-dashed border-signal/50 bg-signal-soft/40 p-3 text-sm">
          <input ref={receiptInput} type="file" accept="image/*,application/pdf" capture="environment" hidden onChange={(e) => readReceipt(e.target.files?.[0])} />
          <button className="btn-ghost" disabled={reading} onClick={() => receiptInput.current?.click()}>{reading ? `⏳ ${t("Reading…")}` : `📷 ${t("Read a receipt photo (AI)")}`}</button>
          <span className="ms-2 text-xs text-slate">{receipt ? `📎 ${receipt.name}` : t("Take a photo of the bill; the form fills itself and the photo is attached.")}</span>
        </div>}
        <div className="grid gap-3">
          <Field label={t("Type")}><select className="input" value={f.v.category} onChange={f.set("category")}>{Array.from(new Set([...EXPENSE_CATEGORIES, f.v.category])).map((c) => <option key={c} value={c}>{t(c)}</option>)}</select></Field>
          <Field label={t("Description")}><input className="input" value={f.v.description} onChange={f.set("description")} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("Amount")}><input className="input" type="number" step="0.01" value={f.v.amount} onChange={f.set("amount")} /></Field>
            <Field label={t("Date")}><input className="input" type="date" value={f.v.expense_date} onChange={f.set("expense_date")} /></Field>
            <Field label={t("Paid from")}><select className="input" value={f.v.account_id} onChange={f.set("account_id")}>{accounts?.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</select></Field>
            <Field label={t("VAT included in the amount")}><input className="input" type="number" step="0.01" value={f.v.tax_amount} onChange={f.set("tax_amount")} /></Field>
          </div>
        </div>
        {editing && <Attachments entity="expense" id={editing.id} />}
      </Modal>
    </>
  );
}
