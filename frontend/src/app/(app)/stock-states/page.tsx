"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { date, money, num } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { Badge, ErrorNote, Field, Modal, PageTitle, StatCard, Table, Tabs, toast } from "@/components/ui";

const TABS = ["damaged", "expired", "reserved", "in_transit"] as const;

export default function StockStates() {
  const { t } = useT();
  const { can } = useSession();
  const [tab, setTab] = useState<(typeof TABS)[number]>("damaged");
  const data = useApi<any>(`/api/stock-states?state=${tab}`, [tab]);
  const all = useApi<any>("/api/stock-states");
  const warehouses = useApi<any[]>("/api/inventory/warehouses");
  const products = useApi<any[]>("/api/inventory/products");
  const [form, setForm] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const editable = can("inventory.adjust");

  const run = async (action: "mark" | "restore" | "dispose", body: any) => {
    setError(null);
    try { const r = await api(`/api/stock-states/${action}`, { method: "POST", json: body }); toast(r.value ? `${t("Saved")} · ${money(r.value, undefined, 2)}` : "Saved"); setForm(null); data.reload(); all.reload(); }
    catch (e: any) { setError(e.message); toast(e.message, "bad"); }
  };
  const rowAction = (row: any, action: "restore" | "dispose") => {
    const q = prompt(t(action === "restore" ? "How many are good again?" : "How many to throw away?"), String(row.quantity));
    if (!q || !(+q > 0)) return;
    run(action, { product_id: row.product_id, warehouse_id: row.warehouse_id, quantity: +q, state: row.state, batch: row.batch, reason: action });
  };
  const s = all.data?.summary ?? {};

  return (
    <>
      <PageTitle title={t("Damaged, expired & held stock")} help={t("Stock states help")}
        actions={editable && <button className="btn-primary" onClick={() => { setError(null); setForm({ product_id: 0, warehouse_id: warehouses.data?.[0]?.id ?? 0, quantity: 1, state: "damaged", reason: "" }); }}>+ {t("Mark damaged / expired")}</button>} />
      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        {TABS.map((k) => <StatCard key={k} label={t(`state.${k}`)} value={money(s[k]?.value ?? 0)} note={`${num(s[k]?.quantity ?? 0)} ${t("items")}`} tone={k === "damaged" || k === "expired" ? (s[k]?.value ? "bad" : "neutral") : "neutral"} />)}
      </div>
      <Tabs tabs={TABS} value={tab} onChange={setTab} />
      <div className="panel"><Table rows={data.data?.rows ?? null} empty={t("Nothing here.")} cols={[
        { h: t("Product"), c: (r: any) => <span className="font-medium">{r.product}</span> }, { h: t("Warehouse"), c: (r: any) => r.warehouse },
        { h: t("Batch"), c: (r: any) => r.batch || "—" }, { h: t("Expiry date"), c: (r: any) => date(r.expiry_date) },
        { h: t("Quantity"), c: (r: any) => num(r.quantity, 2), end: true }, { h: t("Value at cost"), c: (r: any) => money(r.value, undefined, 2), end: true },
        { h: "", c: (r: any) => editable && ["damaged", "expired"].includes(r.state) && <div className="flex justify-end gap-1">
          <button className="link" onClick={() => rowAction(r, "restore")}>{t("Back to stock")}</button>
          <button className="link-danger" onClick={() => rowAction(r, "dispose")}>{t("Dispose")}</button></div> },
      ]} /></div>
      {(tab === "damaged" || tab === "expired") && <p className="mt-2 text-xs text-slate">{t("Damaged and expired stock is written off (stock adjustments expense). Sending it back to the supplier from Purchasing recovers its credit.")}</p>}

      <Modal title={t("Mark damaged / expired")} open={!!form} onClose={() => setForm(null)}
        onSave={() => run("mark", { ...form, product_id: +form.product_id, warehouse_id: +form.warehouse_id, quantity: +form.quantity })}>
        {form && <>
          <ErrorNote error={error} />
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2"><Field label={t("Product")}><select className="input" value={form.product_id} onChange={(e) => setForm({ ...form, product_id: e.target.value })}>
              <option value={0}>{t("Select…")}</option>{products.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field></div>
            <Field label={t("Warehouse")}><select className="input" value={form.warehouse_id} onChange={(e) => setForm({ ...form, warehouse_id: e.target.value })}>
              {warehouses.data?.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</select></Field>
            <Field label={t("Quantity")}><input className="input" type="number" value={form.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })} /></Field>
            <Field label={t("Condition")}><select className="input" value={form.state} onChange={(e) => setForm({ ...form, state: e.target.value })}>
              <option value="damaged">{t("state.damaged")}</option><option value="expired">{t("state.expired")}</option></select></Field>
            <Field label={t("Reason")}><input className="input" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} /></Field>
          </div>
          <p className="mt-3 text-xs text-slate"><Badge tone="warn">{t("Write-off")}</Badge> {t("The cost of this stock is recorded as a loss.")}</p>
        </>}
      </Modal>
    </>
  );
}
