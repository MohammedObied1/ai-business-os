"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { api, download } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { money } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import InvoiceView from "@/components/InvoiceView";
import { PaymentFields, PaymentValue, WhatsAppButton, emptyPayment, paymentPayload } from "@/components/money";
import { ErrorNote, Field, Modal, toast } from "@/components/ui";

export default function InvoicePage() {
  const { t, lang } = useT();
  const router = useRouter();
  const { can, company } = useSession();
  const { id } = useParams<{ id: string }>();
  const { data: d, reload, error: loadError } = useApi<any>(`/api/sales/invoices/${id}`);
  const [payOpen, setPayOpen] = useState(false);
  const [amount, setAmount] = useState(0);
  const [pay, setPay] = useState<PaymentValue>(emptyPayment());
  const [error, setError] = useState<string | null>(null);
  const [shareToken, setShareToken] = useState<string | null>(null);
  const [plan, setPlan] = useState<{ count: number; first_due: string; every_days: number } | null>(null);

  if (loadError) return <div className="text-rust">{loadError}</div>;
  if (!d) return <div className="text-sm text-slate">{t("Loading…")}</div>;
  const inv = d.invoice;
  const balance = inv.total - inv.paid_amount - (inv.credited_amount || 0);
  const token = shareToken ?? d.public_token;
  const link = token ? `${window.location.origin}/i/${token}` : "";

  const recordPayment = async () => {
    setError(null);
    try {
      const p = await api("/api/sales/payments", { method: "POST", json: { invoice_id: inv.id, amount, ...paymentPayload(pay) } });
      toast("Payment recorded"); setPayOpen(false); reload();
      if (p.number && confirm(t("Print the receipt voucher?"))) router.push(`/vouchers/${p.number}`);
    } catch (e: any) { setError(e.message); }
  };
  const cancel = async () => {
    if (!confirm(t("Cancel this invoice?"))) return;
    try { const r = await api(`/api/sales/invoices/${inv.id}/cancel`, { method: "POST" }); toast(r?.pending_approval ? "Sent to a manager for approval" : "Invoice cancelled"); reload(); } catch (e: any) { toast(e.message, "bad"); }
  };
  const share = async () => {
    try { const r = await api(`/api/sales/invoices/${inv.id}/share`, { method: "POST" }); setShareToken(r.token); return r.token as string; } catch (e: any) { toast(e.message, "bad"); return null; }
  };
  const copyLink = async () => {
    const tk = token ?? (await share());
    if (!tk) return;
    await navigator.clipboard.writeText(`${window.location.origin}/i/${tk}`).catch(() => {});
    toast("Link copied");
  };
  const sendEmail = async () => {
    const to = prompt(t("Send to email:"), d.customer.email ?? "");
    if (to === null) return;
    try { const r = await api(`/api/sales/invoices/${inv.id}/email`, { method: "POST", json: { to: to || null, lang } }); toast(r.status === "sent" ? t("Email sent") : t("Email saved in the outbox (email sending is not set up yet)")); }
    catch (e: any) { toast(e.message, "bad"); }
  };
  const savePlan = async () => {
    setError(null);
    try { await api(`/api/sales/invoices/${inv.id}/installments`, { method: "POST", json: plan }); setPlan(null); toast("Saved"); reload(); } catch (e: any) { setError(e.message); }
  };
  const waText = t("Invoice message", { name: d.customer.name, number: inv.number, amount: money(inv.total, d.company.currency, 2), company: company?.name ?? "" }) + (link ? `\n${link}` : "");

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3 print:hidden">
        <Link href="/sales" className="link -ms-2">{lang === "ar" ? "→" : "←"} {t("Sales")}</Link>
        <div className="flex flex-wrap gap-2">
          {!["paid", "cancelled"].includes(inv.status) && can("payments:write") && <button className="btn-primary" onClick={() => { setError(null); setPay(emptyPayment()); setAmount(+balance.toFixed(2)); setPayOpen(true); }}>{t("Record payment")}</button>}
          <button className="btn-ghost" onClick={() => window.print()}>🖨 {t("Print / PDF")}</button>
          {token ? <WhatsAppButton phone={d.customer.phone} text={waText} /> : d.customer.phone && <button className="btn-ghost" onClick={share}>{t("Prepare WhatsApp link")}</button>}
          <button className="btn-ghost" onClick={copyLink}>🔗 {t("Copy link")}</button>
          <button className="btn-ghost" onClick={sendEmail}>✉ {t("Email")}</button>
          <button className="btn-ghost" onClick={() => download(`/api/sales/invoices/${inv.id}/ubl.xml`, `${inv.number}.xml`).catch((e) => toast(e.message, "bad"))}>⬇ {t("E-invoice (XML)")}</button>
          {!["paid", "cancelled"].includes(inv.status) && can("invoices:create") && <button className="btn-ghost" onClick={() => { setError(null); setPlan({ count: 3, first_due: new Date(Date.now() + 30 * 86400000).toISOString().slice(0, 10), every_days: 30 }); }}>📅 {t("Instalments")}</button>}
          {inv.order_id && inv.status !== "cancelled" && can("returns:create") && <Link className="btn-ghost" href={`/sales?return=${inv.order_id}`}>↩ {t("Return items")}</Link>}
          {inv.paid_amount === 0 && !(inv.credited_amount > 0) && inv.status !== "cancelled" && can("invoices:create") && <button className="btn-ghost !text-rust" onClick={cancel}>{t("Cancel invoice")}</button>}
        </div>
      </div>
      <InvoiceView d={d} />
      <Modal title={t("Record payment")} open={payOpen} onClose={() => setPayOpen(false)} onSave={recordPayment} saveLabel={t("Record payment")}>
        <ErrorNote error={error} />
        <div className="mb-3"><Field label={t("Amount")}><input className="input" type="number" step="0.01" value={amount} onChange={(e) => setAmount(+e.target.value)} /></Field></div>
        <PaymentFields value={pay} onChange={setPay} />
      </Modal>
      <Modal title={t("Instalment plan")} open={!!plan} onClose={() => setPlan(null)} onSave={savePlan}>
        {plan && <>
          <ErrorNote error={error} />
          <div className="grid grid-cols-3 gap-3">
            <Field label={t("Number of instalments")}><input className="input" type="number" min={2} max={120} value={plan.count} onChange={(e) => setPlan({ ...plan, count: +e.target.value })} /></Field>
            <Field label={t("First payment")}><input className="input" type="date" value={plan.first_due} onChange={(e) => setPlan({ ...plan, first_due: e.target.value })} /></Field>
            <Field label={t("Every (days)")}><input className="input" type="number" value={plan.every_days} onChange={(e) => setPlan({ ...plan, every_days: +e.target.value })} /></Field>
          </div>
          <p className="mt-3 text-sm">{t("Each instalment")}: <b>{money(inv.total / Math.max(plan.count, 1), d.currency ?? undefined, 2)}</b></p>
          <p className="mt-1 text-xs text-slate">{t("Payments are applied to the oldest instalment first. You'll get an alert when an instalment is late.")}</p>
        </>}
      </Modal>
    </>
  );
}
