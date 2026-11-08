"use client";
import Link from "next/link";
import { useRef, useState } from "react";
import { api, upload } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { date, money, num } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { PaymentFields, PaymentValue, emptyPayment, paymentPayload } from "@/components/money";
import { Drawer, ErrorNote, Field, InfoList, Modal, PageTitle, Status, Table, Tabs, toast, useForm } from "@/components/ui";

const EMPTY_SUPPLIER = { name: "", email: "", phone: "", address: "", tax_number: "", lead_time_days: 7, payment_terms_days: 30, opening_balance: 0 };
type Line = { product_id: number; quantity: number; unit_cost: number | ""; unit: "unit" | "pack"; note?: string };
const EMPTY_LINE: Line = { product_id: 0, quantity: 1, unit_cost: "", unit: "unit" };

export default function Purchasing() {
  const { t } = useT();
  const { can, company } = useSession();
  const [tab, setTab] = useState<"purchases" | "suppliers" | "payments" | "returns to suppliers">("purchases");
  const supReturns = useApi<any[]>(tab === "returns to suppliers" ? "/api/supplier-returns" : null, [tab]);
  const [sr, setSr] = useState<any>(null);
  const pos = useApi<any[]>("/api/purchasing/orders?limit=2000");
  const suppliers = useApi<any[]>("/api/purchasing/suppliers");
  const payments = useApi<any[]>("/api/purchasing/payments");
  const { data: products } = useApi<any[]>("/api/inventory/products?include_archived=true");
  const { data: warehouses } = useApi<any[]>("/api/inventory/warehouses");
  const [open, setOpen] = useState<"po" | "supplier" | "pay" | "receive" | null>(null);
  const [editing, setEditing] = useState<any>(null);
  const [view, setView] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const s = useForm(EMPTY_SUPPLIER);
  const [supplier, setSupplier] = useState(0);
  const [warehouse, setWarehouse] = useState(0);
  const [notes, setNotes] = useState("");
  const [withTax, setWithTax] = useState(true);
  const [currency, setCurrency] = useState("");
  const { data: currencies } = useApi<any>("/api/currencies");
  const [items, setItems] = useState<Line[]>([EMPTY_LINE]);
  const [payAmount, setPayAmount] = useState(0);
  const [pay, setPay] = useState<PaymentValue>(emptyPayment());
  const [paySupplier, setPaySupplier] = useState(0);
  const [receiveWh, setReceiveWh] = useState(0);
  const [receiveNo, setReceiveNo] = useState("");
  const [batches, setBatches] = useState<Record<number, { batch: string; expiry_date: string }>>({});
  const [reading, setReading] = useState(false);
  const photo = useRef<HTMLInputElement>(null);
  const sname = (id: number) => suppliers.data?.find((x) => x.id === id)?.name ?? `#${id}`;
  const prod = (id: number) => products?.find((x) => x.id === id);
  const lineCost = (it: Line) => { if (it.unit_cost !== "") return +it.unit_cost; const p = prod(it.product_id); return p ? p.cost_price * (it.unit === "pack" && p.pack_size ? p.pack_size : 1) : 0; };
  const subtotal = items.reduce((sum, it) => sum + (it.product_id ? lineCost(it) * it.quantity : 0), 0);
  const rate = company?.tax_rate ?? 0;
  const total = subtotal * (1 + (withTax ? rate : 0) / 100);

  const refresh = async (id?: number) => { pos.reload(); suppliers.reload(); payments.reload(); if (id) setView(await api(`/api/purchasing/orders/${id}`)); };
  const act = async (fn: () => Promise<any>, ok: string, id?: number) => {
    setError(null);
    try { await fn(); setOpen(null); toast(ok); refresh(id); } catch (e: any) { setError(e.message); if (!open) toast(e.message, "bad"); }
  };
  const transition = (po: any, status: string) => act(() => api(status === "approved" ? `/api/purchasing/orders/${po.id}/approve` : `/api/purchasing/orders/${po.id}/status?status=${status}`, { method: "POST" }), "Saved", po.id);
  const openPo = (prefill?: { supplier_id?: number | null; lines?: Line[]; notes?: string }) => {
    setError(null); setSupplier(prefill?.supplier_id ?? 0); setWarehouse(warehouses?.[0]?.id ?? 0); setNotes(prefill?.notes ?? ""); setWithTax(true); setCurrency("");
    setItems(prefill?.lines?.length ? prefill.lines : [EMPTY_LINE]); setOpen("po");
  };
  const openSupplier = (x: any = null) => { setError(null); setEditing(x); s.setV(x ? { ...EMPTY_SUPPLIER, ...Object.fromEntries(Object.entries(x).map(([k, v]) => [k, v ?? ""])) } : EMPTY_SUPPLIER); setOpen("supplier"); };
  const removeSupplier = async (x: any) => { if (!confirm(t("Delete {x}?", { x: x.name }))) return; try { await api(`/api/purchasing/suppliers/${x.id}`, { method: "DELETE" }); toast("Deleted"); suppliers.reload(); } catch (e: any) { toast(e.message, "bad"); } };
  const openPay = (supplierId: number, amount: number) => { setError(null); setPaySupplier(supplierId); setPayAmount(+amount.toFixed(2)); setPay(emptyPayment()); setOpen("pay"); };
  const openReceive = (po: any) => {
    setError(null); setReceiveWh(po.warehouse_id ?? warehouses?.[0]?.id ?? 0); setReceiveNo("");
    setBatches(Object.fromEntries(po.items.map((i: any) => [i.id, { batch: "", expiry_date: "" }]))); setOpen("receive");
  };
  const readInvoice = async (f: File | undefined) => {
    if (!f) return;
    setReading(true);
    try {
      const r = await upload("/api/ai/read-invoice", f);
      const lines: Line[] = r.lines.filter((l: any) => l.product_id).map((l: any) => ({ product_id: l.product_id, quantity: l.quantity || 1, unit_cost: l.unit_cost || "", unit: "unit" }));
      const unknown = r.lines.filter((l: any) => !l.product_id).map((l: any) => `${l.name} × ${l.quantity} @ ${l.unit_cost}`);
      openPo({ supplier_id: r.supplier_id, lines, notes: [r.supplier_invoice_no && `${t("Supplier invoice")}: ${r.supplier_invoice_no}`, unknown.length ? `${t("Not matched")}: ${unknown.join("; ")}` : ""].filter(Boolean).join(" — ") });
      toast(t("Read {n} lines from the invoice", { n: r.lines.length }));
    } catch (e: any) { toast(e.message, "bad"); } finally { setReading(false); if (photo.current) photo.current.value = ""; }
  };
  const lineLabel = (l: any) => `${prod(l.product_id)?.name ?? `#${l.product_id}`}${l.uom_label ? ` (${num(l.uom_qty)} ${l.uom_label})` : ""}`;

  return (
    <>
      <PageTitle title={t("Purchasing")} help={t("Purchasing help")} actions={can("purchasing:write") && <>
        <input ref={photo} type="file" accept="image/*,.pdf" className="hidden" onChange={(e) => readInvoice(e.target.files?.[0])} />
        <button className="btn-ghost" disabled={reading} onClick={() => photo.current?.click()}>{reading ? t("Reading…") : `📷 ${t("Read supplier invoice")}`}</button>
        <button className="btn-ghost" onClick={() => openSupplier()}>+ {t("New supplier")}</button><button className="btn-primary" onClick={() => openPo()}>+ {t("New purchase request")}</button></>} />
      <Tabs tabs={["purchases", "suppliers", "payments", "returns to suppliers"] as const} value={tab} onChange={setTab} />
      {tab === "returns to suppliers" && can("purchasing:write") && <div className="mb-3 flex justify-end">
        <button className="btn-primary" onClick={() => { setError(null); setSr({ supplier_id: suppliers.data?.[0]?.id ?? 0, warehouse_id: warehouses?.[0]?.id ?? 0, reason: "", lines: [{ product_id: 0, quantity: 1, unit_price: "", state: "available" }] }); }}>+ {t("Return to supplier")}</button></div>}
      <div className="panel">
        {tab === "purchases" && <Table rows={pos.data} onRow={setView} empty={t("No purchases yet.")} cols={[
          { h: t("Number"), c: (r: any) => <span className="font-medium" dir="ltr">{r.number}</span> }, { h: t("Date"), c: (r: any) => date(r.order_date) }, { h: t("Supplier"), c: (r: any) => sname(r.supplier_id) },
          { h: t("Requested by"), c: (r: any) => <span className={r.requested_by?.startsWith("AI") ? "text-signal" : ""}>{r.requested_by ?? "—"}</span> },
          { h: t("Total"), c: (r: any) => money(r.total, r.currency ?? undefined, 2), end: true }, { h: t("Paid"), c: (r: any) => money(r.paid_amount, r.currency ?? undefined, 2), end: true },
          { h: t("Status"), c: (r: any) => <Status value={r.status} /> },
        ]} />}
        {tab === "suppliers" && <Table rows={suppliers.data} empty={t("No suppliers yet.")} cols={[
          { h: t("Supplier"), c: (r: any) => <span className="font-medium">{r.name}</span> }, { h: t("Phone"), c: (r: any) => <span dir="ltr">{r.phone || "—"}</span> },
          { h: t("Delivers in"), c: (r: any) => t("{n} days", { n: r.lead_time_days }), end: true }, { h: t("Pays within"), c: (r: any) => t("{n} days", { n: r.payment_terms_days }), end: true },
          { h: "", c: (r: any) => <div className="flex justify-end gap-1 whitespace-nowrap">
              <Link className="link" href={`/purchasing/suppliers/${r.id}`}>{t("Account statement")}</Link>
              {can("payments:write") && <button className="link" onClick={() => openPay(r.id, 0)}>{t("Pay supplier")}</button>}
              {can("purchasing:write") && <><button className="link" onClick={() => openSupplier(r)}>{t("Edit")}</button><button className="link-danger" onClick={() => removeSupplier(r)}>{t("Delete")}</button></>}
            </div> },
        ]} />}
        {tab === "returns to suppliers" && <Table rows={supReturns.data} empty={t("No returns to suppliers.")} cols={[
          { h: t("Number"), c: (r: any) => <span className="font-medium" dir="ltr">{r.number}</span> }, { h: t("Date"), c: (r: any) => date(r.return_date) },
          { h: t("Supplier"), c: (r: any) => r.supplier }, { h: t("Items"), c: (r: any) => <span className="text-xs">{r.lines.map((l: any) => `${num(l.quantity)} × ${l.product}${l.state !== "available" ? ` (${t(`state.${l.state}`)})` : ""}`).join(" · ")}</span> },
          { h: t("Reason"), c: (r: any) => r.reason ?? "—" }, { h: t("Credit"), c: (r: any) => money(r.total, undefined, 2), end: true },
        ]} />}
        {tab === "payments" && <Table rows={payments.data} empty={t("No payments yet.")} cols={[
          { h: t("Voucher"), c: (r: any) => <Link className="link -ms-2" href={`/vouchers/${r.number}`} dir="ltr">{r.number}</Link> }, { h: t("Date"), c: (r: any) => date(r.paid_at) },
          { h: t("Supplier"), c: (r: any) => sname(r.supplier_id) }, { h: t("Method"), c: (r: any) => t(r.method) }, { h: t("Reference"), c: (r: any) => r.reference ?? "—" },
          { h: t("Amount"), c: (r: any) => <span className={r.status === "bounced" ? "text-rust line-through" : ""}>{money(r.amount, undefined, 2)}</span>, end: true },
        ]} />}
      </div>

      <Drawer title={view ? `${t("Purchase")} ${view.number}` : ""} open={!!view} onClose={() => setView(null)}>
        {view && <>
          <InfoList items={[[t("Supplier"), sname(view.supplier_id)], [t("Date"), date(view.order_date)], [t("Status"), <Status value={view.status} />], [t("Requested by"), view.requested_by],
            [t("Total"), money(view.total, undefined, 2)], [t("VAT"), money(view.tax_amount, undefined, 2)], [t("Paid"), money(view.paid_amount, undefined, 2)],
            [t("Supplier invoice"), view.supplier_invoice_no]]} />
          {view.notes && <p className="mt-4 rounded-lg bg-paper p-3 text-sm">{view.notes}</p>}
          <h3 className="mb-2 mt-6 font-semibold">{t("Items")}</h3>
          <div className="rounded-lg border border-line"><Table rows={view.items} cols={[
            { h: t("Product"), c: (r: any) => lineLabel(r) }, { h: t("Qty"), c: (r: any) => num(r.quantity), end: true },
            { h: t("Cost"), c: (r: any) => money(r.unit_cost, undefined, 2), end: true }, { h: t("Batch"), c: (r: any) => r.batch ? `${r.batch}${r.expiry_date ? ` · ${date(r.expiry_date)}` : ""}` : "—" },
            { h: t("Total"), c: (r: any) => money(r.line_total, undefined, 2), end: true },
          ]} /></div>
          <div className="mt-6 flex flex-wrap gap-2">
            {view.status === "request" && can("purchasing:approve") && <><button className="btn-primary" onClick={() => transition(view, "approved")}>{t("Approve")}</button><button className="btn-ghost !text-rust" onClick={() => transition(view, "cancelled")}>{t("Reject")}</button></>}
            {view.status === "approved" && can("purchasing:write") && <button className="btn-primary" onClick={() => transition(view, "ordered")}>{t("Mark as ordered")}</button>}
            {view.status === "ordered" && can("purchasing:write") && <button className="btn-primary" onClick={() => openReceive(view)}>{t("Goods arrived")}</button>}
            {["approved", "ordered"].includes(view.status) && can("purchasing:write") && <button className="btn-ghost !text-rust" onClick={() => confirm(t("Cancel this purchase?")) && transition(view, "cancelled")}>{t("Cancel")}</button>}
            {view.status !== "cancelled" && view.paid_amount < view.total && can("payments:write") && <button className="btn-ghost" onClick={() => openPay(view.supplier_id, view.total - view.paid_amount)}>{t("Pay supplier")}</button>}
          </div>
        </>}
      </Drawer>

      <Modal title={t("New purchase request")} open={open === "po"} onClose={() => setOpen(null)} saveLabel={t("Submit request")}
        onSave={() => act(() => api("/api/purchasing/orders", { method: "POST", json: { supplier_id: supplier, warehouse_id: warehouse || null, notes: notes || null, include_tax: withTax, currency: currency || null,
          items: items.filter((i) => i.product_id).map((i) => ({ ...i, unit_cost: i.unit_cost === "" ? null : +i.unit_cost })) } }), "Request sent for approval")}>
        <ErrorNote error={error} />
        <div className="grid grid-cols-2 gap-3">
          <Field label={`${t("Supplier")} *`}><select className="input" value={supplier} onChange={(e) => setSupplier(+e.target.value)}><option value={0}>{t("Select…")}</option>{suppliers.data?.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></Field>
          <Field label={t("Deliver to")}><select className="input" value={warehouse} onChange={(e) => setWarehouse(+e.target.value)}><option value={0}>{t("Select…")}</option>{warehouses?.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></Field>
          {!!currencies?.items?.length && <Field label={t("Currency")}><select className="input" value={currency} onChange={(e) => { setCurrency(e.target.value); setItems(items.map((i) => ({ ...i, unit_cost: "" }))); }}>
            <option value="">{currencies.base}</option>{currencies.items.map((c: any) => <option key={c.code} value={c.code}>{c.code} ({c.rate})</option>)}</select></Field>}
        </div>
        {currency && <p className="mt-2 text-xs text-amber">{t("Write the costs in {c}. Product costs are converted to {b} when the goods arrive.", { c: currency, b: currencies?.base ?? "" })}</p>}
        <div className="mt-4 space-y-2">
          <div className="flex gap-2 text-xs text-slate"><span className="flex-1">{t("Product")}</span><span className="w-20">{t("Qty")}</span><span className="w-24">{t("Cost")}</span><span className="w-6" /></div>
          {items.map((it, i) => {
            const p = prod(it.product_id);
            const set = (patch: Partial<Line>) => setItems(items.map((x, j) => (j === i ? { ...x, ...patch } : x)));
            return (
              <div key={i}>
                <div className="flex items-center gap-2">
                  <select className="input" value={it.product_id} onChange={(e) => set({ product_id: +e.target.value, unit_cost: "", unit: "unit" })}><option value={0}>{t("Product…")}</option>{products?.filter((x) => x.is_active).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select>
                  <input className="input w-20 !px-2" type="number" min={1} value={it.quantity} onChange={(e) => set({ quantity: +e.target.value })} />
                  <input className="input w-24 !px-2" type="number" step="0.01" placeholder={it.product_id ? String(lineCost({ ...it, unit_cost: "" })) : ""} value={it.unit_cost} onChange={(e) => set({ unit_cost: e.target.value === "" ? "" : +e.target.value })} />
                  <button className="w-6 text-slate hover:text-rust" onClick={() => setItems(items.length > 1 ? items.filter((_, j) => j !== i) : items)} aria-label={t("Delete")}>✕</button>
                </div>
                {p?.pack_size > 0 && <div className="mt-1 flex gap-1 text-xs">
                  {(["unit", "pack"] as const).map((u) => <button key={u} onClick={() => set({ unit: u, unit_cost: "" })} className={`rounded px-2 py-0.5 ${it.unit === u ? "bg-signal text-white" : "bg-paper text-slate"}`}>{u === "unit" ? t("piece") : `${p.pack_unit || t("pack")} (${num(p.pack_size)})`}</button>)}
                </div>}
              </div>
            );
          })}
          <button className="link -ms-2" onClick={() => setItems([...items, EMPTY_LINE])}>{t("+ Add product")}</button>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-3">
          <Field label={t("Notes")}><input className="input" value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
          {rate > 0 && <label className="flex items-end gap-2 pb-2 text-sm"><input type="checkbox" className="h-4 w-4 accent-signal" checked={withTax} onChange={(e) => setWithTax(e.target.checked)} />{t("Supplier charges VAT")} ({rate}%)</label>}
        </div>
        <div className="num mt-4 flex items-center justify-between rounded-lg bg-paper px-3 py-2"><span className="text-slate">{t("Total")}</span><span className="text-lg font-semibold">{money(total, undefined, 2)}</span></div>
      </Modal>

      <Modal title={editing ? t("Edit supplier") : t("New supplier")} open={open === "supplier"} onClose={() => setOpen(null)} saveLabel={t("Save supplier")}
        onSave={() => act(() => editing ? api(`/api/purchasing/suppliers/${editing.id}`, { method: "PATCH", json: s.v }) : api("/api/purchasing/suppliers", { method: "POST", json: s.v }), "Saved")}>
        <ErrorNote error={error} />
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2"><Field label={`${t("Name")} *`}><input className="input" value={s.v.name} onChange={s.set("name")} /></Field></div>
          <Field label={t("Phone")}><input className="input" dir="ltr" value={s.v.phone} onChange={s.set("phone")} /></Field><Field label={t("Email")}><input className="input" dir="ltr" value={s.v.email} onChange={s.set("email")} /></Field>
          <Field label={t("City / address")}><input className="input" value={s.v.address} onChange={s.set("address")} /></Field><Field label={t("Tax number")}><input className="input" dir="ltr" value={s.v.tax_number} onChange={s.set("tax_number")} /></Field>
          <Field label={t("Delivery time (days)")}><input className="input" type="number" value={s.v.lead_time_days} onChange={s.set("lead_time_days")} /></Field><Field label={t("Payment within (days)")}><input className="input" type="number" value={s.v.payment_terms_days} onChange={s.set("payment_terms_days")} /></Field>
          <div className="col-span-2"><Field label={t("What we owed them before using the system")}><input className="input" type="number" step="0.01" value={s.v.opening_balance} onChange={s.set("opening_balance")} /></Field></div>
        </div>
      </Modal>

      <Modal title={t("Pay supplier")} open={open === "pay"} onClose={() => setOpen(null)} saveLabel={t("Save")}
        onSave={() => act(() => api("/api/purchasing/payments", { method: "POST", json: { supplier_id: paySupplier, amount: payAmount, po_id: view && view.supplier_id === paySupplier && view.paid_amount < view.total ? view.id : null, ...paymentPayload(pay) } }), "Payment recorded", view?.id)}>
        <ErrorNote error={error} />
        <p className="mb-3 text-sm font-medium">{sname(paySupplier)}</p>
        <div className="mb-3"><Field label={t("Amount")}><input className="input" type="number" step="0.01" value={payAmount} onChange={(e) => setPayAmount(+e.target.value)} /></Field></div>
        <PaymentFields value={pay} onChange={setPay} direction="out" />
      </Modal>

      <Modal title={t("Goods arrived")} open={open === "receive"} onClose={() => setOpen(null)} saveLabel={t("Add to stock")}
        onSave={() => act(() => api(`/api/purchasing/orders/${view.id}/receive`, { method: "POST", json: { warehouse_id: receiveWh || null, supplier_invoice_no: receiveNo || null,
          lines: Object.entries(batches).filter(([, b]) => b.batch || b.expiry_date).map(([k, b]) => ({ item_id: +k, batch: b.batch, expiry_date: b.expiry_date || null })) } }), "Stock updated", view?.id)}>
        <ErrorNote error={error} />
        <div className="grid grid-cols-2 gap-3">
          <Field label={t("Which warehouse did the goods go to?")}><select className="input" value={receiveWh} onChange={(e) => setReceiveWh(+e.target.value)}><option value={0}>{t("Select…")}</option>{warehouses?.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></Field>
          <Field label={t("Supplier invoice number")}><input className="input" dir="ltr" value={receiveNo} onChange={(e) => setReceiveNo(e.target.value)} /></Field>
        </div>
        <p className="mb-2 mt-4 text-sm text-slate">{t("Batch help")}</p>
        <div className="space-y-2">
          {view?.items.map((l: any) => (
            <div key={l.id} className="grid grid-cols-[1fr_7rem_9rem] items-center gap-2">
              <span className="text-sm">{lineLabel(l)}</span>
              <input className="input !px-2" placeholder={t("Batch")} value={batches[l.id]?.batch ?? ""} onChange={(e) => setBatches({ ...batches, [l.id]: { ...batches[l.id], batch: e.target.value } })} />
              <input className="input !px-2" type="date" value={batches[l.id]?.expiry_date ?? ""} onChange={(e) => setBatches({ ...batches, [l.id]: { ...batches[l.id], expiry_date: e.target.value } })} />
            </div>
          ))}
        </div>
      </Modal>
      <Modal title={t("Return to supplier")} open={!!sr} onClose={() => setSr(null)} saveLabel={t("Save return")}
        onSave={() => act(() => api("/api/supplier-returns", { method: "POST", json: { ...sr, lines: sr.lines.filter((l: any) => l.product_id && +l.quantity > 0)
          .map((l: any) => ({ ...l, quantity: +l.quantity, unit_price: l.unit_price === "" ? null : +l.unit_price })) } }).then(() => { setSr(null); supReturns.reload(); }), "Return saved")}>
        {sr && <>
          <ErrorNote error={error} />
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("Supplier")}><select className="input" value={sr.supplier_id} onChange={(e) => setSr({ ...sr, supplier_id: +e.target.value })}>
              {suppliers.data?.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></Field>
            <Field label={t("From warehouse")}><select className="input" value={sr.warehouse_id} onChange={(e) => setSr({ ...sr, warehouse_id: +e.target.value })}>
              {warehouses?.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></Field>
          </div>
          <div className="mt-4 space-y-2">
            <div className="flex gap-2 text-xs text-slate"><span className="flex-1">{t("Product")}</span><span className="w-20">{t("Qty")}</span><span className="w-24">{t("Credit per unit")}</span><span className="w-28">{t("From stock")}</span></div>
            {sr.lines.map((l: any, i: number) => {
              const set = (patch: any) => setSr({ ...sr, lines: sr.lines.map((x: any, j: number) => (j === i ? { ...x, ...patch } : x)) });
              return (
                <div key={i} className="flex gap-2">
                  <select className="input" value={l.product_id} onChange={(e) => set({ product_id: +e.target.value })}><option value={0}>{t("Product…")}</option>
                    {products?.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select>
                  <input className="input !w-20 shrink-0" type="number" value={l.quantity} onChange={(e) => set({ quantity: e.target.value })} />
                  <input className="input !w-24 shrink-0" type="number" placeholder={t("cost")} value={l.unit_price} onChange={(e) => set({ unit_price: e.target.value })} />
                  <select className="input !w-28 shrink-0 !px-2" value={l.state} onChange={(e) => set({ state: e.target.value })}>
                    <option value="available">{t("Available")}</option><option value="damaged">{t("state.damaged")}</option><option value="expired">{t("state.expired")}</option></select>
                </div>);
            })}
            <button className="link -ms-2" onClick={() => setSr({ ...sr, lines: [...sr.lines, { product_id: 0, quantity: 1, unit_price: "", state: "available" }] })}>{t("+ Add product")}</button>
          </div>
          <div className="mt-3"><Field label={t("Reason")}><input className="input" value={sr.reason} onChange={(e) => setSr({ ...sr, reason: e.target.value })} /></Field></div>
          <p className="mt-2 text-xs text-slate">{t("The supplier's balance goes down by the credit; the stock leaves at its cost.")}</p>
        </>}
      </Modal>
    </>
  );
}
