"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { date, money } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { Badge, ErrorNote, Field, Modal, PageTitle, StatCard, Status, Table, toast, useForm } from "@/components/ui";
import { PaymentFields, PaymentValue, WhatsAppButton, emptyPayment, paymentPayload, whatsappLink } from "@/components/money";
import { Attachments } from "@/components/Attachments";
import { CustomerExtraFields } from "@/components/CustomerFields";

const KINDS = ["call", "whatsapp", "email", "visit", "complaint", "note"];

export default function CustomerProfile() {
  const { t, lang } = useT();
  const router = useRouter();
  const { can, company } = useSession();
  const [recvOpen, setRecvOpen] = useState(false);
  const [recvAmount, setRecvAmount] = useState(0);
  const [recv, setRecv] = useState<PaymentValue>(emptyPayment());
  const { id } = useParams<{ id: string }>();
  const { data: c, reload } = useApi<any>(`/api/customers/${id}`);
  const { data: orders } = useApi<any[]>(`/api/sales/orders?customer_id=${id}`);
  const { data: invoices } = useApi<any[]>(`/api/sales/invoices?customer_id=${id}`);
  const [kind, setKind] = useState("call");
  const [summary, setSummary] = useState("");
  const [editOpen, setEditOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [portalOpen, setPortalOpen] = useState(false);
  const [portalDays, setPortalDays] = useState(90);
  const portalInfo = useApi<any>(portalOpen ? `/api/customers/${id}/portal-link` : null, [portalOpen]);
  const f = useForm({ name: "", email: "", phone: "", address: "", customer_type: "business", credit_limit: 0, notes: "", price_list_id: null as number | null, assigned_user_id: null as number | null, visit_days: "" });
  if (!c) return <div className="text-sm text-slate">{t("Loading…")}</div>;

  const addInteraction = async () => { if (!summary.trim()) return; await api(`/api/customers/${id}/interactions`, { method: "POST", json: { kind, summary } }); setSummary(""); reload(); };
  const openEdit = () => { setError(null); f.setV({ name: c.name, email: c.email ?? "", phone: c.phone ?? "", address: c.address ?? "", customer_type: c.customer_type, credit_limit: c.credit_limit, notes: c.notes ?? "", price_list_id: c.price_list_id ?? null, assigned_user_id: c.assigned_user_id ?? null, visit_days: c.visit_days ?? "" }); setEditOpen(true); };
  const save = async () => { setError(null); try { await api(`/api/customers/${id}`, { method: "PATCH", json: { ...f.v, visit_days: f.v.visit_days || null } }); setEditOpen(false); toast("Saved"); reload(); } catch (e: any) { setError(e.message); } };
  const receive = async () => {
    setError(null);
    try {
      const pays = await api("/api/sales/receipts", { method: "POST", json: { customer_id: +id, amount: recvAmount, ...paymentPayload(recv) } });
      setRecvOpen(false); toast("Payment recorded"); reload();
      if (pays[0]?.number) router.push(`/vouchers/${pays[0].number}`);
    } catch (e: any) { setError(e.message); }
  };
  const portal = async (how: "copy" | "whatsapp", renew = false) => {
    try {
      // an active link is reused (its expiry is extended); an expired one or "renew" makes a new link and the old one stops working
      const r = await api(`/api/customers/${id}/portal-link?days=${portalDays}&renew=${renew}`, { method: "POST" });
      const url = `${window.location.origin}/portal/${r.token}`;
      if (how === "copy") { await navigator.clipboard.writeText(url).catch(() => {}); toast(renew ? "New link copied. The old one no longer works." : "Link copied"); }
      else window.open(whatsappLink(c.phone, t("Portal message", { name: c.name, company: company?.name ?? "" }) + `
${url}`), "_blank");
      portalInfo.reload();
    } catch (e: any) { toast(e.message, "bad"); }
  };
  const revokePortal = async () => {
    if (!confirm(t("Stop the portal link? The customer won't be able to open it."))) return;
    try { await api(`/api/customers/${id}/portal-link`, { method: "DELETE" }); toast("Link stopped"); portalInfo.reload(); } catch (e: any) { toast(e.message, "bad"); }
  };
  const remove = async () => {
    if (!confirm(t("Delete {x}?", { x: c.name }))) return;
    try { await api(`/api/customers/${id}`, { method: "DELETE" }); toast("Deleted"); router.push("/customers"); } catch (e: any) { toast(e.message, "bad"); }
  };

  return (
    <>
      <Link href="/customers" className="link -ms-2 mb-2 inline-block">{lang === "ar" ? "→" : "←"} {t("All customers")}</Link>
      <PageTitle title={c.name} help={[t(c.customer_type), c.address, c.phone, c.email].filter(Boolean).join(" · ")} actions={<>
        {c.open_balance > 0 && can("payments:write") && <button className="btn-primary" onClick={() => { setError(null); setRecv(emptyPayment()); setRecvAmount(+c.open_balance.toFixed(2)); setRecvOpen(true); }}>{t("Receive payment")}</button>}
        <Link className="btn-ghost" href={`/customers/${id}/statement`}>{t("Account statement")}</Link>
        {c.open_balance > 0 && <WhatsAppButton phone={c.phone} text={t("Reminder message", { name: c.name, amount: money(c.open_balance, undefined, 2), company: company?.name ?? "" })} />}
        {can("customers:write") && <button className="btn-ghost" onClick={() => setPortalOpen(true)} title={t("Customer portal help")}>🔗 {t("Portal link")}</button>}
        {can("customers:write") && <button className="btn-ghost" onClick={openEdit}>{t("Edit")}</button>}
        {can("customers:delete") && <button className="btn-ghost !text-rust" onClick={remove}>{t("Delete")}</button>}</>} />
      {c.notes && <p className="-mt-3 mb-5 rounded-lg bg-paper p-3 text-sm">{c.notes}</p>}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label={t("Total bought")} value={money(c.total_revenue)} note={`${c.orders_count} ${t("Orders")}`} />
        <StatCard label={t("Owes you")} value={money(c.open_balance, undefined, 2)} tone={c.credit_limit && c.open_balance > c.credit_limit ? "bad" : "neutral"} note={c.credit_limit && c.open_balance > c.credit_limit ? t("Over credit limit") : `${t("Credit limit")}: ${money(c.credit_limit)}`} />
        <StatCard label={t("Last purchase")} value={date(c.last_purchase)} />
        <StatCard label={t("Rating")} value={`${c.score} / 100`} tone={c.score >= 60 ? "good" : c.score < 30 ? "bad" : "neutral"} />
      </div>
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <div className="panel"><h2 className="card-title mb-2">{t("Invoices")}</h2>
          <Table rows={invoices} empty={t("No invoices yet.")} onRow={(r: any) => router.push(`/sales/invoices/${r.id}`)} cols={[{ h: t("Number"), c: (r: any) => <span dir="ltr">{r.number}</span> }, { h: t("Due"), c: (r: any) => date(r.due_date) }, { h: t("Balance"), c: (r: any) => money(r.total - r.paid_amount, undefined, 2), end: true }, { h: t("Status"), c: (r: any) => <Status value={r.status} /> }]} /></div>
        <div className="panel"><h2 className="card-title mb-2">{t("Orders")}</h2>
          <Table rows={orders} empty={t("No sales yet.")} cols={[{ h: t("Number"), c: (r: any) => <span dir="ltr">{r.number}</span> }, { h: t("Date"), c: (r: any) => date(r.order_date) }, { h: t("Total"), c: (r: any) => money(r.total, undefined, 2), end: true }, { h: t("Status"), c: (r: any) => <Status value={r.status} /> }]} /></div>
      </div>
      <div className="panel mt-6 p-4">
        <h2 className="text-base font-semibold">{t("Notes & calls")}</h2>
        <div className="mt-3 flex flex-wrap gap-2 sm:flex-nowrap">
          <select className="input sm:w-40" value={kind} onChange={(e) => setKind(e.target.value)}>{KINDS.map((k) => <option key={k} value={k}>{t(k)}</option>)}</select>
          <input className="input" placeholder={t("What happened?")} value={summary} onChange={(e) => setSummary(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addInteraction()} />
          <button className="btn-primary" onClick={addInteraction}>{t("Add")}</button>
        </div>
        <ul className="mt-4 divide-y divide-line">
          {c.interactions.map((i: any) => <li key={i.id} className="flex flex-wrap items-center gap-3 py-2.5 text-sm"><span className="w-28 shrink-0 text-slate">{date(i.occurred_at)}</span><Badge tone={i.kind === "complaint" ? "bad" : "neutral"}>{t(i.kind)}</Badge><span dir="auto">{i.summary}</span></li>)}
          {!c.interactions.length && <li className="py-2 text-sm text-slate">{t("No notes yet.")}</li>}
        </ul>
      </div>

      <div className="panel mt-6 p-4"><Attachments entity="customer" id={+id} compact /></div>

      <Modal title={t("Receive payment")} open={recvOpen} onClose={() => setRecvOpen(false)} onSave={receive} saveLabel={t("Record payment")}>
        <ErrorNote error={error} />
        <p className="mb-3 text-sm text-slate">{t("Receive payment help")}</p>
        <div className="mb-3"><Field label={t("Amount")}><input className="input" type="number" step="0.01" value={recvAmount} onChange={(e) => setRecvAmount(+e.target.value)} /></Field></div>
        <PaymentFields value={recv} onChange={setRecv} />
      </Modal>
      <Modal title={t("Edit customer")} open={editOpen} onClose={() => setEditOpen(false)} onSave={save}>
        <ErrorNote error={error} />
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2"><Field label={t("Name")}><input className="input" value={f.v.name} onChange={f.set("name")} /></Field></div>
          <Field label={t("Phone")}><input className="input" dir="ltr" value={f.v.phone} onChange={f.set("phone")} /></Field>
          <Field label={t("Email")}><input className="input" dir="ltr" value={f.v.email} onChange={f.set("email")} /></Field>
          <Field label={t("City / address")}><input className="input" value={f.v.address} onChange={f.set("address")} /></Field>
          <Field label={t("Type")}><select className="input" value={f.v.customer_type} onChange={f.set("customer_type")}><option value="business">{t("Business")}</option><option value="individual">{t("Individual")}</option></select></Field>
          <Field label={t("Credit limit")}><input className="input" type="number" value={f.v.credit_limit} onChange={f.set("credit_limit")} /></Field>
          <CustomerExtraFields v={f.v} onChange={(patch) => f.setV({ ...f.v, ...patch })} />
          <div className="col-span-2"><Field label={t("Notes")}><textarea className="input h-20" value={f.v.notes} onChange={f.set("notes")} /></Field></div>
        </div>
      </Modal>
      <Modal title={t("Customer portal")} open={portalOpen} onClose={() => setPortalOpen(false)}>
        <p className="mb-3 text-sm text-slate">{t("Customer portal help")}</p>
        {portalInfo.data && <div className="mb-4 rounded-lg bg-paper p-3 text-sm">
          {portalInfo.data.active
            ? <><Badge tone="good">{t("Active")}</Badge> {t("until")} {date(portalInfo.data.expires_at)}</>
            : <Badge tone="neutral">{t("No active link")}</Badge>}
          {portalInfo.data.last_seen_at && <div className="mt-1 text-xs text-slate">{t("Last opened")}: {date(portalInfo.data.last_seen_at)}</div>}
        </div>}
        <Field label={t("Link works for (days)")}><input className="input" type="number" min={1} max={365} value={portalDays} onChange={(e) => setPortalDays(+e.target.value || 90)} /></Field>
        <div className="mt-4 flex flex-wrap gap-2">
          <button className="btn-primary" onClick={() => portal("copy")}>🔗 {t("Copy link")}</button>
          {c.phone && <button className="btn-ghost" onClick={() => portal("whatsapp")}>{t("Send portal on WhatsApp")}</button>}
          {portalInfo.data?.active && <button className="btn-ghost" onClick={() => portal("copy", true)}>{t("New link (old one stops)")}</button>}
          {portalInfo.data?.active && <button className="btn-ghost !text-rust" onClick={revokePortal}>{t("Stop link")}</button>}
        </div>
      </Modal>
    </>
  );
}
