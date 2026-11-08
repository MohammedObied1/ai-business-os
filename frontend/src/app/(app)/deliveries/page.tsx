"use client";
import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { date, money } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { WhatsAppButton } from "@/components/money";
import { ErrorNote, Field, Modal, PageTitle, Status, Table, Tabs, toast } from "@/components/ui";

const TABS = ["my deliveries", "open", "done"] as const;

export default function Deliveries() {
  const { t } = useT();
  const { can, user } = useSession();
  const office = can("sales:read");
  const [tab, setTab] = useState<(typeof TABS)[number]>(office ? "open" : "my deliveries");
  const status = tab === "done" ? "delivered,failed,returned" : "assigned,out";
  const list = useApi<any[]>(`/api/deliveries?status=${status}${tab === "my deliveries" ? "&mine=true" : ""}`, [tab]);
  const users = useApi<any[]>(office ? "/api/users" : null);
  const orders = useApi<any[]>(office ? "/api/sales/orders?status=confirmed&limit=300" : null);
  const customers = useApi<any[]>(office ? "/api/customers?limit=5000" : null);
  const custName = useMemo(() => Object.fromEntries((customers.data ?? []).map((c) => [c.id, c.name])), [customers.data]);
  const [form, setForm] = useState<any>(null);
  const [done, setDone] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const create = async () => {
    setError(null);
    try {
      await api("/api/deliveries", { method: "POST", json: { ...form, driver_id: form.driver_id || null, scheduled_for: form.scheduled_for || null, address: form.address || null } });
      setForm(null); toast("Saved"); list.reload();
    } catch (e: any) { setError(e.message); }
  };
  const setStatus = async (d: any, s: string, extra: any = {}) => {
    try { await api(`/api/deliveries/${d.id}/status`, { method: "POST", json: { status: s, ...extra } }); toast("Saved"); list.reload(); setDone(null); }
    catch (e: any) { toast(e.message, "bad"); }
  };
  const mapLink = (addr: string) => `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(addr)}`;

  const Card = ({ d }: { d: any }) => (
    <div className="panel p-4">
      <div className="flex items-start justify-between gap-2">
        <div><div className="font-semibold">{d.customer}</div><div className="text-xs text-slate">{d.order_number} · {date(d.scheduled_for)}</div></div>
        <Status value={d.status} />
      </div>
      {d.address && <a className="mt-2 block text-sm text-signal" href={mapLink(d.address)} target="_blank" rel="noreferrer">📍 {d.address}</a>}
      <div className="mt-1 text-sm">{t("Order total")}: <b>{money(d.total)}</b></div>
      {d.status === "delivered" && d.amount_due > 0 && <div className="mt-1 text-sm text-rust">{t("Still due")}: <b>{money(d.amount_due)}</b></div>}
      {d.note && <p className="mt-1 text-xs text-slate">{d.note}</p>}
      <div className="mt-3 flex flex-wrap gap-2">
        {d.phone && <a className="btn-ghost !py-1.5" href={`tel:${d.phone}`}>📞 {t("Call")}</a>}
        {d.phone && <WhatsAppButton phone={d.phone} text={t("Hello, your order {n} is on the way.", { n: d.order_number })} className="!py-1.5" />}
        {d.status === "assigned" && <button className="btn-ghost !py-1.5" onClick={() => setStatus(d, "out")}>🚚 {t("On the way")}</button>}
        {["assigned", "out"].includes(d.status) && <button className="btn-primary !py-1.5" onClick={() => setDone({ d, received_by: "", cash_collected: 0, note: "" })}>✓ {t("Delivered")}</button>}
        {["assigned", "out"].includes(d.status) && <button className="btn-ghost !py-1.5" onClick={() => { if (confirm(t("Mark as returned? No payment is collected and the order is not marked delivered."))) setStatus(d, "returned"); }}>↩ {t("Returned")}</button>}
        {["assigned", "out"].includes(d.status) && <button className="link-danger" onClick={() => { const n = prompt(t("Why couldn't it be delivered?")); if (n !== null) setStatus(d, "failed", { note: n }); }}>{t("Failed")}</button>}
      </div>
    </div>
  );

  return (
    <>
      <PageTitle title={t("Deliveries")} help={t("Deliveries help")} actions={can("sales:write") && <button className="btn-primary" onClick={() => { setError(null); setForm({ order_id: 0, driver_id: "", address: "", scheduled_for: new Date().toISOString().slice(0, 10), note: "" }); }}>+ {t("New delivery")}</button>} />
      {office && <Tabs tabs={TABS} value={tab} onChange={setTab} />}
      {tab === "my deliveries" || !office
        ? <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {list.data?.length === 0 && <div className="panel p-8 text-center text-slate md:col-span-2">{t("No deliveries for you right now.")}</div>}
          {list.data?.map((d) => <Card key={d.id} d={d} />)}
        </div>
        : <div className="panel"><Table rows={list.data} cols={[
          { h: t("Order"), c: (d: any) => <span className="font-medium">{d.order_number}</span> }, { h: t("Customer"), c: (d: any) => d.customer },
          { h: t("Address"), c: (d: any) => <span className="text-sm">{d.address ?? "—"}</span> }, { h: t("Driver"), c: (d: any) => d.driver ?? <span className="text-amber">{t("Not assigned")}</span> },
          { h: t("Date"), c: (d: any) => date(tab === "done" ? d.delivered_at : d.scheduled_for) },
          { h: t("Cash collected"), c: (d: any) => d.cash_collected ? money(d.cash_collected) : "—", end: true },
          { h: t("Still due"), c: (d: any) => d.amount_due > 0 ? <span className="text-rust">{money(d.amount_due)}</span> : "—", end: true },
          { h: t("Status"), c: (d: any) => <Status value={d.status} /> },
          { h: "", c: (d: any) => ["assigned", "out"].includes(d.status) && <button className="link" onClick={() => setDone({ d, received_by: "", cash_collected: 0, note: "" })}>✓ {t("Delivered")}</button> },
        ]} /></div>}

      <Modal title={t("New delivery")} open={!!form} onClose={() => setForm(null)} onSave={create}>
        {form && <>
          <ErrorNote error={error} />
          <div className="grid gap-3">
            <Field label={t("Order")}><select className="input" value={form.order_id} onChange={(e) => setForm({ ...form, order_id: +e.target.value })}>
              <option value={0}>{t("Select…")}</option>
              {orders.data?.map((o) => <option key={o.id} value={o.id}>{o.number} · {custName[o.customer_id] ?? ""} · {money(o.total, o.currency ?? undefined)}</option>)}</select></Field>
            <Field label={t("Driver")}><select className="input" value={form.driver_id} onChange={(e) => setForm({ ...form, driver_id: e.target.value ? +e.target.value : "" })}>
              <option value="">{t("Not assigned")}</option>{users.data?.filter((u) => u.is_active).map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}</select></Field>
            <Field label={t("Address (empty = customer's address)")}><input className="input" value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label={t("Date")}><input className="input" type="date" value={form.scheduled_for} onChange={(e) => setForm({ ...form, scheduled_for: e.target.value })} /></Field>
              <Field label={t("Note")}><input className="input" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} /></Field>
            </div>
          </div>
        </>}
      </Modal>

      <Modal title={t("Delivered")} open={!!done} onClose={() => setDone(null)} onSave={() => setStatus(done.d, "delivered", { received_by: done.received_by || null, cash_collected: +done.cash_collected || 0, note: done.note || null })}>
        {done && <div className="grid gap-3">
          <p className="text-sm">{done.d.customer} · {done.d.order_number} · {money(done.d.total)}</p>
          <Field label={t("Received by")}><input className="input" value={done.received_by} onChange={(e) => setDone({ ...done, received_by: e.target.value })} /></Field>
          <Field label={t("Cash collected (0 if none)")}><input className="input" type="number" value={done.cash_collected} onChange={(e) => setDone({ ...done, cash_collected: e.target.value })} /></Field>
          <p className="text-xs text-slate">{t("Cash collected is recorded as a payment on the order's invoice.")}</p>
          {user && <p className="text-xs text-slate">{user.full_name}</p>}
        </div>}
      </Modal>
    </>
  );
}
