"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { date } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { Badge, ErrorNote, Field, Modal, PageTitle, StatCard, Table, toast } from "@/components/ui";

const usd = (n: number) => `$${(n ?? 0).toLocaleString("en", { maximumFractionDigits: 2 })}`;

export default function PlatformBilling() {
  const { t } = useT();
  const data = useApi<any>("/api/platform/billing", [], { platform: true });
  const companies = useApi<any[]>("/api/platform/companies", [], { platform: true });
  const [form, setForm] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"unpaid" | "all">("unpaid");

  const run = async () => {
    try { const r = await api("/api/platform/billing/run", { method: "POST", platform: true }); toast(t("{n} bills created", { n: r.created })); data.reload(); }
    catch (e: any) { toast(e.message, "bad"); }
  };
  const paid = async (i: any) => {
    const m = prompt(t("Payment received. Extend the subscription by how many months? (0 = don't extend)"), "1");
    if (m === null) return;
    try { await api(`/api/platform/billing/${i.id}/paid?extend_months=${+m || 0}`, { method: "POST", platform: true }); toast("Saved"); data.reload(); } catch (e: any) { toast(e.message, "bad"); }
  };
  const voidIt = async (i: any) => {
    if (!confirm(t("Cancel this bill?"))) return;
    await api(`/api/platform/billing/${i.id}/void`, { method: "POST", platform: true }); data.reload();
  };
  const create = async () => {
    setError(null);
    try { await api(`/api/platform/companies/${form.company_id}/invoices`, { method: "POST", platform: true, json: { amount: +form.amount, period: form.period, note: form.note || null } }); setForm(null); data.reload(); toast("Saved"); }
    catch (e: any) { setError(e.message); }
  };
  const rows = data.data?.items.filter((i: any) => filter === "all" || i.status === "unpaid") ?? null;
  const overdue = (data.data?.items ?? []).filter((i: any) => i.status === "unpaid" && i.due_date && i.due_date < new Date().toISOString().slice(0, 10)).length;

  return (
    <>
      <PageTitle title={t("Subscription billing")} help={t("Platform billing help")} actions={<>
        <button className="btn-ghost" onClick={() => { setError(null); setForm({ company_id: companies.data?.[0]?.id, amount: "", period: new Date().toISOString().slice(0, 7), note: "" }); }}>+ {t("Manual bill")}</button>
        <button className="btn-primary" onClick={run}>{t("Create this month's bills")}</button></>} />
      <div className="mb-6 grid gap-4 sm:grid-cols-3">
        <StatCard label={t("Unpaid")} value={usd(data.data?.unpaid_total)} tone={data.data?.unpaid_total ? "bad" : "neutral"} />
        <StatCard label={t("Overdue bills")} value={String(overdue)} tone={overdue ? "bad" : "neutral"} />
        <StatCard label={t("Bills")} value={String(data.data?.items.length ?? 0)} />
      </div>
      <div className="mb-3 flex gap-1 text-sm">{(["unpaid", "all"] as const).map((f) => <button key={f} onClick={() => setFilter(f)} className={`rounded-md px-3 py-1 ${filter === f ? "bg-signal text-white" : "text-slate hover:bg-paper"}`}>{t(f === "unpaid" ? "Unpaid" : "All")}</button>)}</div>
      <div className="panel"><Table rows={rows} empty={t("No bills. Bills are created automatically on the 1st of each month for companies on paid plans.")} cols={[
        { h: t("Number"), c: (i: any) => <span className="font-medium">{i.number}</span> }, { h: t("Company"), c: (i: any) => i.company },
        { h: t("Period"), c: (i: any) => <span dir="ltr">{i.period}</span> }, { h: t("Plan"), c: (i: any) => i.plan_name ?? "—" },
        { h: t("Due"), c: (i: any) => date(i.due_date) }, { h: t("Amount"), c: (i: any) => usd(i.amount), end: true },
        { h: t("Status"), c: (i: any) => <Badge tone={i.status === "paid" ? "good" : i.status === "void" ? "neutral" : "warn"}>{t(`bill.${i.status}`)}</Badge> },
        { h: "", c: (i: any) => i.status === "unpaid" && <div className="flex justify-end gap-1"><button className="link" onClick={() => paid(i)}>{t("Mark paid")}</button><button className="link-danger" onClick={() => voidIt(i)}>{t("Cancel")}</button></div> },
      ]} /></div>

      <Modal title={t("Manual bill")} open={!!form} onClose={() => setForm(null)} onSave={create}>
        {form && <>
          <ErrorNote error={error} />
          <div className="grid gap-3">
            <Field label={t("Company")}><select className="input" value={form.company_id} onChange={(e) => setForm({ ...form, company_id: +e.target.value })}>
              {companies.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label={t("Amount") + " ($)"}><input className="input" type="number" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} /></Field>
              <Field label={t("Period")}><input className="input" type="month" value={form.period} onChange={(e) => setForm({ ...form, period: e.target.value })} /></Field>
            </div>
            <Field label={t("Note")}><input className="input" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} /></Field>
          </div>
        </>}
      </Modal>
    </>
  );
}
