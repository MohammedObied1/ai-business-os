"use client";
import { useState } from "react";
import { api, download } from "@/lib/api";
import { useApi, usePaged } from "@/lib/hooks";
import { date, money, num } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { Drawer, ErrorNote, Field, InfoList, Modal, PageTitle, Status, PagedTable, Table, Tabs, toast, useForm } from "@/components/ui";

const EMPTY_PRODUCT = { sku: "", barcode: "", name: "", category: "", unit: "unit", cost_price: 0, sale_price: 0, min_stock: 0, supplier_lead_time_days: 7, opening_stock: 0, warehouse_id: 0,
  pack_unit: "", pack_size: 0, pack_price: "" as number | "", pack_barcode: "" };

export default function Inventory() {
  const { t, lang } = useT();
  const { can } = useSession();
  const canWrite = can("inventory:write");
  const [tab, setTab] = useState<"products" | "running out" | "movements" | "warehouses">("products");
  const [q, setQ] = useState("");
  const products = useApi<any[]>(`/api/inventory/products${q ? `?q=${encodeURIComponent(q)}` : ""}`, [q]);
  const forecast = useApi<any[]>("/api/inventory/forecast?only_risky=true");
  const movements = usePaged<any>(tab === "movements" ? "/api/inventory/movements" : null, [tab]);
  const warehouses = useApi<any[]>("/api/inventory/warehouses");
  const [open, setOpen] = useState<"product" | "adjust" | "transfer" | "warehouse" | null>(null);
  const [editing, setEditing] = useState<any>(null); // product or warehouse being edited
  const [detailId, setDetailId] = useState<number | null>(null);
  const detail = useApi<any>(detailId ? `/api/inventory/products/${detailId}` : null, [detailId]);
  const [error, setError] = useState<string | null>(null);
  const p = useForm(EMPTY_PRODUCT);
  const a = useForm({ product_id: 0, warehouse_id: 0, quantity: 0, reference: "", batch: "", expiry_date: "" });
  const tr = useForm({ product_id: 0, from_warehouse_id: 0, to_warehouse_id: 0, quantity: 0 });
  const w = useForm({ name: "", location: "" });
  const pname = (id: number) => products.data?.find((x) => x.id === id)?.name ?? `#${id}`;
  const wname = (id: number | null) => warehouses.data?.find((x) => x.id === id)?.name ?? "—";
  const reloadAll = () => { products.reload(); forecast.reload(); movements.reload(); warehouses.reload(); if (detailId) detail.reload(); };

  const show = (m: typeof open, item: any = null) => {
    setError(null); setEditing(item);
    if (m === "product") p.setV(item ? { ...EMPTY_PRODUCT, ...item, category: item.category ?? "", barcode: item.barcode ?? "", pack_unit: item.pack_unit ?? "", pack_price: item.pack_price ?? "",
      pack_barcode: item.pack_barcode ?? "", opening_stock: 0, warehouse_id: 0 } : { ...EMPTY_PRODUCT, warehouse_id: warehouses.data?.[0]?.id ?? 0 });
    if (m === "warehouse") w.setV(item ? { name: item.name, location: item.location ?? "" } : { name: "", location: "" });
    if (m === "adjust") a.setV({ product_id: item?.id ?? 0, warehouse_id: warehouses.data?.[0]?.id ?? 0, quantity: 0, reference: "", batch: "", expiry_date: "" });
    if (m === "transfer") tr.setV({ product_id: item?.id ?? 0, from_warehouse_id: 0, to_warehouse_id: 0, quantity: 0 });
    setOpen(m);
  };
  const submit = async (fn: () => Promise<any>, ok: string) => {
    setError(null);
    try { const r = await fn(); setOpen(null); toast(r?.pending_approval ? "Sent to a manager for approval" : ok); reloadAll(); } catch (e: any) { setError(e.message); }
  };
  const saveProduct = () => {
    const { opening_stock, warehouse_id, ...fields } = p.v;
    const rest = { ...fields, barcode: fields.barcode || null, pack_barcode: fields.pack_barcode || null, pack_unit: fields.pack_unit || null,
      pack_price: fields.pack_price === "" ? null : +fields.pack_price, pack_size: +fields.pack_size || 0 };
    return submit(() => editing
      ? api(`/api/inventory/products/${editing.id}`, { method: "PATCH", json: rest })
      : api("/api/inventory/products", { method: "POST", json: { ...rest, opening_stock: +opening_stock || 0, warehouse_id: +warehouse_id || null } }), "Saved");
  };
  const removeProduct = async (prod: any) => {
    if (!confirm(t("Delete {x}?", { x: prod.name }))) return;
    try { const r = await api(`/api/inventory/products/${prod.id}`, { method: "DELETE" }); toast(r.archived ? "Archived (it has history)" : "Deleted"); setDetailId(null); reloadAll(); }
    catch (e: any) { toast(e.message, "bad"); }
  };
  const removeWarehouse = async (wh: any) => {
    if (!confirm(t("Delete {x}?", { x: wh.name }))) return;
    try { await api(`/api/inventory/warehouses/${wh.id}`, { method: "DELETE" }); toast("Deleted"); reloadAll(); } catch (e: any) { toast(e.message, "bad"); }
  };

  const productOptions = <><option value={0}>{t("Select…")}</option>{products.data?.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</>;
  const warehouseOptions = <><option value={0}>{t("Select…")}</option>{warehouses.data?.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</>;
  const d = detail.data;
  const noWarehouses = warehouses.data && !warehouses.data.length;

  return (
    <>
      <PageTitle title={t("Inventory")} help={t("Inventory help")} actions={<>
        <button className="btn-ghost" onClick={() => download(`/api/data/export/products?lang=${lang}`).catch((e) => toast(e.message, "bad"))}>⬇ {t("Excel")}</button>
        {canWrite && <>
          <button className="btn-ghost" onClick={() => show("adjust")}>{t("Add / remove stock")}</button>
          <button className="btn-ghost" onClick={() => show("transfer")}>{t("Move between warehouses")}</button>
          <button className="btn-primary" onClick={() => show("product")}>+ {t("New product")}</button>
        </>}</>} />

      {noWarehouses && canWrite && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber/40 bg-amber-soft p-4 text-sm">
          <span>{t("You have no warehouse yet. Add one first so you can record stock.")}</span>
          <button className="btn-primary" onClick={() => show("warehouse")}>+ {t("New warehouse")}</button>
        </div>
      )}

      <Tabs tabs={["products", "running out", "movements", "warehouses"] as const} value={tab} onChange={setTab} />
      {tab === "products" && <input className="input mb-3 max-w-sm" placeholder={`🔍 ${t("Search by name or code")}`} value={q} onChange={(e) => setQ(e.target.value)} />}
      <div className="panel">
        {tab === "products" && <Table rows={products.data} onRow={(r: any) => setDetailId(r.id)} empty={t("No products yet. Add one, or import them from Excel.")} cols={[
          { h: t("Product"), c: (r: any) => <div><div className="font-medium">{r.name}</div><div className="text-xs text-slate" dir="ltr">{r.sku}</div></div> },
          { h: t("Category"), c: (r: any) => r.category ?? "—" },
          { h: t("Cost"), c: (r: any) => money(r.cost_price, undefined, 2), end: true },
          { h: t("Price"), c: (r: any) => money(r.sale_price, undefined, 2), end: true },
          { h: t("Stock"), c: (r: any) => <span className={r.total_stock < r.min_stock ? "font-semibold text-rust" : ""}>{num(r.total_stock)}</span>, end: true },
          { h: t("Min"), c: (r: any) => num(r.min_stock), end: true },
        ]} />}
        {tab === "running out" && <Table rows={forecast.data} empty={t("Nothing is about to run out.")} onRow={(r: any) => setDetailId(r.product_id)} cols={[
          { h: t("Product"), c: (r: any) => <span className="font-medium">{r.product_name}</span> }, { h: t("Stock"), c: (r: any) => num(r.current_stock), end: true },
          { h: t("Sells / day"), c: (r: any) => num(r.avg_daily_sales, 1), end: true }, { h: t("Days left"), c: (r: any) => r.days_of_cover ?? "∞", end: true },
          { h: t("Risk"), c: (r: any) => <Status value={r.risk} /> }, { h: t("Suggested order"), c: (r: any) => r.recommended_order_qty ? <span className="font-semibold">{num(r.recommended_order_qty)}</span> : "—", end: true },
        ]} />}
        {tab === "movements" && <PagedTable paged={movements} cols={[
          { h: t("When"), c: (r: any) => date(r.occurred_at) }, { h: t("Product"), c: (r: any) => pname(r.product_id) }, { h: t("Warehouse"), c: (r: any) => wname(r.warehouse_id) },
          { h: t("Type"), c: (r: any) => t(r.movement_type) }, { h: t("Note"), c: (r: any) => <span className="text-slate">{r.reference ?? ""}</span> },
          { h: t("Quantity"), c: (r: any) => <span dir="ltr" className={r.quantity < 0 ? "text-rust" : "text-moss"}>{r.quantity > 0 ? "+" : ""}{num(r.quantity)}</span>, end: true },
        ]} />}
        {tab === "warehouses" && <>
          {canWrite && <div className="flex justify-end p-3"><button className="btn-ghost" onClick={() => show("warehouse")}>+ {t("New warehouse")}</button></div>}
          <Table rows={warehouses.data} empty={t("No warehouses yet.")} cols={[
            { h: t("Warehouse"), c: (r: any) => <span className="font-medium">{r.name}</span> }, { h: t("Location"), c: (r: any) => r.location ?? "—" },
            { h: "", c: (r: any) => canWrite && <div className="flex justify-end gap-1"><button className="link" onClick={() => show("warehouse", r)}>{t("Edit")}</button><button className="link-danger" onClick={() => removeWarehouse(r)}>{t("Delete")}</button></div> },
          ]} />
        </>}
      </div>

      <Drawer title={d?.name ?? "…"} open={!!detailId} onClose={() => setDetailId(null)} actions={d && canWrite && <>
        <button className="btn-ghost !px-3 !py-1" onClick={() => show("product", d)}>{t("Edit")}</button>
        <button className="btn-ghost !px-3 !py-1 !text-rust" onClick={() => removeProduct(d)}>{t("Delete")}</button></>}>
        {!d ? <div className="text-sm text-slate">{t("Loading…")}</div> : <>
          <InfoList items={[
            [t("SKU / code"), <span dir="ltr">{d.sku}</span>], [t("Category"), d.category], [t("Cost price"), money(d.cost_price, undefined, 2)], [t("Sale price"), money(d.sale_price, undefined, 2)],
            [t("Stock"), <span className={d.total_stock < d.min_stock ? "text-rust" : ""}>{num(d.total_stock)} {d.unit}</span>], [t("Minimum stock"), num(d.min_stock)],
            [t("Profit per unit"), money(d.sale_price - d.cost_price, undefined, 2)], [t("Supplier delivery (days)"), d.supplier_lead_time_days],
            [t("Barcode"), d.barcode ? <span dir="ltr">{d.barcode}</span> : "—"], [t("Pack"), d.pack_size ? `${d.pack_unit || t("pack")} = ${num(d.pack_size)}` : "—"],
          ]} />
          {canWrite && <div className="mt-4 flex gap-2"><button className="btn-ghost" onClick={() => show("adjust", d)}>{t("Add / remove stock")}</button><button className="btn-ghost" onClick={() => show("transfer", d)}>{t("Move between warehouses")}</button></div>}
          <h3 className="mb-2 mt-6 font-semibold">{t("Stock per warehouse")}</h3>
          <div className="rounded-lg border border-line"><Table rows={d.by_warehouse} empty={t("No stock recorded yet.")} cols={[{ h: t("Warehouse"), c: (r: any) => r.warehouse }, { h: t("Quantity"), c: (r: any) => num(r.quantity), end: true }]} /></div>
          <h3 className="mb-2 mt-6 font-semibold">{t("Latest movements")}</h3>
          <div className="rounded-lg border border-line"><Table rows={d.movements} empty={t("No movements yet.")} cols={[
            { h: t("When"), c: (r: any) => date(r.occurred_at) }, { h: t("Type"), c: (r: any) => t(r.movement_type) }, { h: t("Note"), c: (r: any) => <span className="text-slate">{r.reference ?? ""}</span> },
            { h: t("Quantity"), c: (r: any) => <span dir="ltr" className={r.quantity < 0 ? "text-rust" : "text-moss"}>{r.quantity > 0 ? "+" : ""}{num(r.quantity)}</span>, end: true },
          ]} /></div>
        </>}
      </Drawer>

      <Modal title={editing ? t("Edit product") : t("New product")} open={open === "product"} onClose={() => setOpen(null)} onSave={saveProduct} saveLabel={t("Save product")}>
        <ErrorNote error={error} />
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2"><Field label={`${t("Name")} *`}><input className="input" value={p.v.name} onChange={p.set("name")} /></Field></div>
          <Field label={t("SKU / code")}><input className="input" dir="ltr" placeholder={t("Automatic if empty")} value={p.v.sku} onChange={p.set("sku")} /></Field>
          <Field label={t("Barcode")}><input className="input" dir="ltr" placeholder={t("Scan or type")} value={p.v.barcode} onChange={p.set("barcode")} /></Field>
          <Field label={t("Category")}><input className="input" value={p.v.category} onChange={p.set("category")} /></Field>
          <Field label={t("Cost price")}><input className="input" type="number" step="0.01" value={p.v.cost_price} onChange={p.set("cost_price")} /></Field>
          <Field label={t("Sale price")}><input className="input" type="number" step="0.01" value={p.v.sale_price} onChange={p.set("sale_price")} /></Field>
          <Field label={t("Unit")}><input className="input" value={p.v.unit} onChange={p.set("unit")} /></Field>
          <Field label={t("Minimum stock")}><input className="input" type="number" value={p.v.min_stock} onChange={p.set("min_stock")} /></Field>
          <Field label={t("Supplier delivery (days)")}><input className="input" type="number" value={p.v.supplier_lead_time_days} onChange={p.set("supplier_lead_time_days")} /></Field>
          <div className="col-span-2 mt-2 rounded-lg bg-paper p-3">
            <div className="mb-2 text-sm font-medium">{t("Selling by the carton / box")} <span className="font-normal text-slate">({t("optional")})</span></div>
            <div className="grid grid-cols-2 gap-3">
              <Field label={t("Pack name")}><input className="input" placeholder={t("e.g. carton")} value={p.v.pack_unit} onChange={p.set("pack_unit")} /></Field>
              <Field label={t("Pieces in one pack")}><input className="input" type="number" value={p.v.pack_size} onChange={p.set("pack_size")} /></Field>
              <Field label={t("Pack price (if different)")}><input className="input" type="number" step="0.01" value={p.v.pack_price} onChange={p.set("pack_price")} /></Field>
              <Field label={t("Pack barcode")}><input className="input" dir="ltr" value={p.v.pack_barcode} onChange={p.set("pack_barcode")} /></Field>
            </div>
          </div>
          {!editing && <>
            <Field label={t("Opening stock")}><input className="input" type="number" value={p.v.opening_stock} onChange={p.set("opening_stock")} /></Field>
            <Field label={t("In warehouse")}><select className="input" value={p.v.warehouse_id} onChange={p.set("warehouse_id")}>{warehouseOptions}</select></Field>
          </>}
        </div>
      </Modal>
      <Modal title={t("Add / remove stock")} open={open === "adjust"} onClose={() => setOpen(null)} saveLabel={t("Apply")}
        onSave={() => submit(() => api("/api/inventory/stock/adjust", { method: "POST", json: { ...a.v, product_id: +a.v.product_id, warehouse_id: +a.v.warehouse_id, expiry_date: a.v.expiry_date || null } }), "Stock updated")}>
        <ErrorNote error={error} />
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2"><Field label={t("Product")}><select className="input" value={a.v.product_id} onChange={a.set("product_id")}>{productOptions}</select></Field></div>
          <Field label={t("Warehouse")}><select className="input" value={a.v.warehouse_id} onChange={a.set("warehouse_id")}>{warehouseOptions}</select></Field>
          <Field label={t("Quantity (+ add / − remove)")}><input className="input" type="number" value={a.v.quantity} onChange={a.set("quantity")} /></Field>
          {+a.v.quantity > 0 && <>
            <Field label={`${t("Batch")} (${t("optional")})`}><input className="input" value={a.v.batch} onChange={a.set("batch")} /></Field>
            <Field label={`${t("Expiry date")} (${t("optional")})`}><input className="input" type="date" value={a.v.expiry_date} onChange={a.set("expiry_date")} /></Field>
          </>}
          <div className="col-span-2"><Field label={t("Note")}><input className="input" placeholder={t("e.g. stock count, damaged goods")} value={a.v.reference} onChange={a.set("reference")} /></Field></div>
        </div>
      </Modal>
      <Modal title={t("Move between warehouses")} open={open === "transfer"} onClose={() => setOpen(null)} saveLabel={t("Move")}
        onSave={() => submit(() => api("/api/inventory/stock/transfer", { method: "POST", json: { product_id: +tr.v.product_id, from_warehouse_id: +tr.v.from_warehouse_id, to_warehouse_id: +tr.v.to_warehouse_id, quantity: +tr.v.quantity } }), "Moved")}>
        <ErrorNote error={error} />
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2"><Field label={t("Product")}><select className="input" value={tr.v.product_id} onChange={tr.set("product_id")}>{productOptions}</select></Field></div>
          <Field label={t("From")}><select className="input" value={tr.v.from_warehouse_id} onChange={tr.set("from_warehouse_id")}>{warehouseOptions}</select></Field>
          <Field label={t("To")}><select className="input" value={tr.v.to_warehouse_id} onChange={tr.set("to_warehouse_id")}>{warehouseOptions}</select></Field>
          <Field label={t("Quantity")}><input className="input" type="number" value={tr.v.quantity} onChange={tr.set("quantity")} /></Field>
        </div>
      </Modal>
      <Modal title={editing ? t("Edit warehouse") : t("New warehouse")} open={open === "warehouse"} onClose={() => setOpen(null)} saveLabel={t("Save warehouse")}
        onSave={() => submit(() => editing ? api(`/api/inventory/warehouses/${editing.id}`, { method: "PATCH", json: w.v }) : api("/api/inventory/warehouses", { method: "POST", json: w.v }), "Saved")}>
        <ErrorNote error={error} />
        <div className="grid gap-3"><Field label={t("Name")}><input className="input" value={w.v.name} onChange={w.set("name")} /></Field><Field label={t("Location")}><input className="input" value={w.v.location} onChange={w.set("location")} /></Field></div>
      </Modal>
    </>
  );
}
