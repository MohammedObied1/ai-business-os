"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { useApi, usePaged } from "@/lib/hooks";
import { date, money, num } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { Badge, Drawer, ErrorNote, Field, Modal, PageTitle, PagedTable, Table, Tabs, toast } from "@/components/ui";

const TABS = ["open", "received", "cancelled", "all"] as const;
const STATUS_FILTER: Record<(typeof TABS)[number], string> = { open: "DRAFT,REQUESTED,APPROVED,IN_TRANSIT", received: "RECEIVED", cancelled: "CANCELLED", all: "" };
const TONE: Record<string, any> = { DRAFT: "neutral", REQUESTED: "warn", APPROVED: "info", IN_TRANSIT: "info", RECEIVED: "good", CANCELLED: "bad" };

export default function Transfers() {
  const { t } = useT();
  const { can } = useSession();
  const [tab, setTab] = useState<(typeof TABS)[number]>("open");
  const list = usePaged<any>(`/api/transfers?status=${STATUS_FILTER[tab]}`, [tab]);
  const warehouses = useApi<any[]>("/api/inventory/warehouses");
  const products = useApi<any[]>("/api/inventory/products");
  const [form, setForm] = useState<any>(null);
  const [view, setView] = useState<any>(null);
  const [received, setReceived] = useState<Record<number, string>>({});
  const [error, setError] = useState<string | null>(null);
  const canApprove = can("inventory.approve_adjustment") || can("approvals.approve");

  const create = async (submit: boolean) => {
    setError(null);
    try {
      const r = await api("/api/transfers", { method: "POST", json: { ...form, submit, lines: form.lines.filter((l: any) => l.product_id && +l.quantity > 0) } });
      setForm(null); toast("Saved"); list.reload(); setView(r);
    } catch (e: any) { setError(e.message); }
  };
  const act = async (action: string, body?: any) => {
    try {
      const r = await api(`/api/transfers/${view.id}/${action}`, { method: "POST", json: body ?? {} });
      setView(r); list.reload(); toast("Saved");
    } catch (e: any) { toast(e.message, "bad"); }
  };
  const openNew = () => {
    setError(null);
    setForm({ from_warehouse_id: warehouses.data?.[0]?.id ?? 0, to_warehouse_id: warehouses.data?.[1]?.id ?? 0, note: "", lines: [{ product_id: 0, quantity: 1 }] });
  };

  return (
    <>
      <PageTitle title={t("Warehouse transfers")} help={t("Transfers help")} actions={can("inventory.transfer") && <button className="btn-primary" onClick={openNew}>+ {t("New transfer")}</button>} />
      <Tabs tabs={TABS} value={tab} onChange={setTab} />
      <div className="panel"><PagedTable paged={list} onRow={(r: any) => { setReceived({}); setView(r); }} empty={t("No transfers.")} cols={[
        { h: t("Number"), c: (r: any) => <span className="font-medium" dir="ltr">{r.number}</span> }, { h: t("Date"), c: (r: any) => date(r.created_at) },
        { h: t("From"), c: (r: any) => r.from_warehouse }, { h: t("To"), c: (r: any) => r.to_warehouse },
        { h: t("Items"), c: (r: any) => r.lines.length, end: true },
        { h: t("Status"), c: (r: any) => <Badge tone={TONE[r.status]}>{t(`transfer.${r.status}`)}</Badge> },
      ]} /></div>

      <Drawer title={view ? `${view.number} · ${view.from_warehouse} → ${view.to_warehouse}` : ""} open={!!view} onClose={() => setView(null)}
        actions={view && <>
          {view.status === "DRAFT" && <button className="btn-primary" onClick={() => act("submit")}>{t("Send for approval")}</button>}
          {view.status === "REQUESTED" && canApprove && <button className="btn-primary" onClick={() => act("approve")}>{t("Approve (reserve stock)")}</button>}
          {view.status === "APPROVED" && <button className="btn-primary" onClick={() => act("ship")}>🚚 {t("Ship")}</button>}
          {view.status === "IN_TRANSIT" && <button className="btn-primary" onClick={() => act("receive", { lines: Object.fromEntries(Object.entries(received).filter(([, v]) => v !== "").map(([k, v]) => [k, +v])) })}>✓ {t("Receive")}</button>}
          {["DRAFT", "REQUESTED", "APPROVED", "IN_TRANSIT"].includes(view.status) && <button className="btn-ghost !text-rust" onClick={() => confirm(t("Cancel this transfer? Reserved stock goes back to the source.")) && act("cancel")}>{t("Cancel")}</button>}
        </>}>
        {view && <>
          <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
            <Badge tone={TONE[view.status]}>{t(`transfer.${view.status}`)}</Badge>
            <span className="text-slate">{t("Requested by")} {view.requested_by}</span>
            {view.approved_by && <span className="text-slate">· {t("Approved by")} {view.approved_by}</span>}
            {view.received_by && <span className="text-slate">· {t("Received by")} {view.received_by}</span>}
            {view.value > 0 && <span className="ms-auto font-medium">{t("Value")}: {money(view.value, undefined, 2)}</span>}
          </div>
          <div className="rounded-lg border border-line"><Table rows={view.lines} cols={[
            { h: t("Product"), c: (l: any) => <span>{l.product}{l.batch && <span className="ms-1 text-xs text-slate">({l.batch})</span>}</span> },
            { h: t("Quantity"), c: (l: any) => num(l.quantity, 2), end: true },
            { h: t("Received"), c: (l: any) => view.status === "IN_TRANSIT"
              ? <input className="input !w-24 !py-1 text-end" type="number" placeholder={String(l.quantity)} value={received[l.id] ?? ""} onChange={(e) => setReceived({ ...received, [l.id]: e.target.value })} />
              : l.received_quantity == null ? "—" : <span className={l.received_quantity < l.quantity ? "font-semibold text-rust" : ""}>{num(l.received_quantity, 2)}</span>, end: true },
          ]} /></div>
          {view.status === "IN_TRANSIT" && <p className="mt-2 text-xs text-slate">{t("Leave empty if everything arrived. A smaller quantity writes the missing part off as lost.")}</p>}
          {view.note && <p className="mt-3 rounded-lg bg-paper p-3 text-sm">{view.note}</p>}
        </>}
      </Drawer>

      <Modal title={t("New transfer")} open={!!form} onClose={() => setForm(null)}>
        {form && <>
          <ErrorNote error={error} />
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("From")}><select className="input" value={form.from_warehouse_id} onChange={(e) => setForm({ ...form, from_warehouse_id: +e.target.value })}>
              {warehouses.data?.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</select></Field>
            <Field label={t("To")}><select className="input" value={form.to_warehouse_id} onChange={(e) => setForm({ ...form, to_warehouse_id: +e.target.value })}>
              {warehouses.data?.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</select></Field>
          </div>
          <div className="mt-4 space-y-2">
            {form.lines.map((l: any, i: number) => (
              <div key={i} className="flex gap-2">
                <select className="input" value={l.product_id} onChange={(e) => setForm({ ...form, lines: form.lines.map((x: any, j: number) => j === i ? { ...x, product_id: +e.target.value } : x) })}>
                  <option value={0}>{t("Product…")}</option>{products.data?.map((p) => <option key={p.id} value={p.id}>{p.name} ({num(p.total_stock)})</option>)}</select>
                <input className="input !w-24 shrink-0" type="number" value={l.quantity} onChange={(e) => setForm({ ...form, lines: form.lines.map((x: any, j: number) => j === i ? { ...x, quantity: e.target.value } : x) })} />
                <button className="link-danger" onClick={() => setForm({ ...form, lines: form.lines.filter((_: any, j: number) => j !== i) })}>✕</button>
              </div>))}
            <button className="link -ms-2" onClick={() => setForm({ ...form, lines: [...form.lines, { product_id: 0, quantity: 1 }] })}>{t("+ Add product")}</button>
          </div>
          <div className="mt-3"><Field label={t("Note")}><input className="input" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} /></Field></div>
          <div className="mt-5 flex justify-end gap-2">
            <button className="btn-ghost" onClick={() => create(false)}>{t("Save as draft")}</button>
            <button className="btn-primary" onClick={() => create(true)}>{t("Send for approval")}</button>
          </div>
        </>}
      </Modal>
    </>
  );
}
