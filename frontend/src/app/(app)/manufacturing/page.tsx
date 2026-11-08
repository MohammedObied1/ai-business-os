"use client";
import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { date, money, num } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { ErrorNote, Field, Modal, PageTitle, Status, Table, toast } from "@/components/ui";

export default function Manufacturing() {
  const { t } = useT();
  const { can } = useSession();
  const canWrite = can("inventory:write");
  const boms = useApi<any[]>("/api/manufacturing/boms");
  const orders = useApi<any[]>("/api/manufacturing/orders");
  const products = useApi<any[]>("/api/inventory/products");
  const warehouses = useApi<any[]>("/api/inventory/warehouses");
  const whName = useMemo(() => Object.fromEntries((warehouses.data ?? []).map((w) => [w.id, w.name])), [warehouses.data]);
  const [bom, setBom] = useState<any>(null);
  const [make, setMake] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const saveBom = async () => {
    setError(null);
    try { await api("/api/manufacturing/boms", { method: "POST", json: bom }); setBom(null); toast("Saved"); boms.reload(); } catch (e: any) { setError(e.message); }
  };
  const produce = async () => {
    setError(null);
    try {
      const r = await api(`/api/manufacturing/orders?bom_id=${make.bom.id}&quantity=${make.quantity}&warehouse_id=${make.warehouse_id}`, { method: "POST" });
      setMake(null); toast(t("Produced. Unit cost {c}", { c: money(r.unit_cost, undefined, 2) })); orders.reload(); boms.reload();
    } catch (e: any) { setError(e.message); }
  };

  return (
    <>
      <PageTitle title={t("Manufacturing")} help={t("Manufacturing help")} actions={canWrite && <button className="btn-primary" onClick={() => { setError(null); setBom({ product_id: 0, output_qty: 1, note: "", lines: [{ product_id: 0, quantity: 1 }] }); }}>+ {t("New recipe")}</button>} />
      <h2 className="mb-3 text-lg font-semibold">{t("Recipes (what goes into each product)")}</h2>
      <div className="mb-8 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {boms.data?.length === 0 && <div className="panel p-6 text-sm text-slate md:col-span-2">{t("No recipes yet. Example: 1 box of juice = 12 bottles + 1 carton.")}</div>}
        {boms.data?.map((b) => (
          <div key={b.id} className="panel p-4">
            <div className="flex items-start justify-between gap-2">
              <div><div className="font-semibold">{b.product}</div><div className="text-xs text-slate">{t("Makes {n}", { n: num(b.output_qty, 2) })} · {t("Unit cost")} {money(b.unit_cost, undefined, 2)}</div></div>
              {canWrite && <button className="btn-primary !px-3 !py-1" onClick={() => { setError(null); setMake({ bom: b, quantity: b.output_qty, warehouse_id: warehouses.data?.[0]?.id }); }}>{t("Produce")}</button>}
            </div>
            <ul className="mt-3 space-y-1 text-sm">{b.lines.map((l: any) => <li key={l.product_id} className="flex justify-between border-b border-line/50 py-1"><span>{l.product}</span><span className="num text-slate">× {num(l.quantity, 3)}</span></li>)}</ul>
            {b.note && <p className="mt-2 text-xs text-slate">{b.note}</p>}
          </div>
        ))}
      </div>
      <h2 className="mb-3 text-lg font-semibold">{t("Production history")}</h2>
      <div className="panel"><Table rows={orders.data} cols={[
        { h: t("Number"), c: (o: any) => <span className="font-medium">{o.number}</span> }, { h: t("Date"), c: (o: any) => date(o.done_at ?? o.created_at) },
        { h: t("Product"), c: (o: any) => o.product }, { h: t("Warehouse"), c: (o: any) => whName[o.warehouse_id] ?? "—" },
        { h: t("Quantity"), c: (o: any) => num(o.quantity, 2), end: true }, { h: t("Unit cost"), c: (o: any) => money(o.unit_cost, undefined, 2), end: true },
        { h: t("Status"), c: (o: any) => <Status value={o.status} /> },
      ]} /></div>

      <Modal title={t("New recipe")} open={!!bom} onClose={() => setBom(null)} onSave={saveBom}>
        {bom && <>
          <ErrorNote error={error} />
          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-2"><Field label={t("Finished product")}><select className="input" value={bom.product_id} onChange={(e) => setBom({ ...bom, product_id: +e.target.value })}>
              <option value={0}>{t("Select…")}</option>{products.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field></div>
            <Field label={t("Makes (quantity)")}><input className="input" type="number" value={bom.output_qty} onChange={(e) => setBom({ ...bom, output_qty: +e.target.value })} /></Field>
          </div>
          <p className="mb-2 mt-4 text-sm font-medium">{t("Components")}</p>
          <div className="space-y-2">{bom.lines.map((l: any, i: number) => (
            <div key={i} className="flex gap-2">
              <select className="input" value={l.product_id} onChange={(e) => setBom({ ...bom, lines: bom.lines.map((x: any, j: number) => j === i ? { ...x, product_id: +e.target.value } : x) })}>
                <option value={0}>{t("Select…")}</option>{products.data?.filter((p) => p.id !== bom.product_id).map((p) => <option key={p.id} value={p.id}>{p.name} ({p.unit})</option>)}</select>
              <input className="input !w-28 shrink-0" type="number" value={l.quantity} onChange={(e) => setBom({ ...bom, lines: bom.lines.map((x: any, j: number) => j === i ? { ...x, quantity: +e.target.value } : x) })} />
              <button className="link-danger" onClick={() => setBom({ ...bom, lines: bom.lines.filter((_: any, j: number) => j !== i) })}>✕</button>
            </div>))}
            <button className="link -ms-2" onClick={() => setBom({ ...bom, lines: [...bom.lines, { product_id: 0, quantity: 1 }] })}>+ {t("Add component")}</button>
          </div>
          <div className="mt-3"><Field label={t("Note")}><input className="input" value={bom.note} onChange={(e) => setBom({ ...bom, note: e.target.value })} /></Field></div>
        </>}
      </Modal>

      <Modal title={make ? `${t("Produce")} · ${make.bom.product}` : ""} open={!!make} onClose={() => setMake(null)} onSave={produce} saveLabel={t("Produce")}>
        {make && <>
          <ErrorNote error={error} />
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("Quantity")}><input className="input" type="number" value={make.quantity} onChange={(e) => setMake({ ...make, quantity: +e.target.value })} /></Field>
            <Field label={t("Warehouse")}><select className="input" value={make.warehouse_id} onChange={(e) => setMake({ ...make, warehouse_id: +e.target.value })}>
              {warehouses.data?.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</select></Field>
          </div>
          <p className="mb-1 mt-4 text-sm font-medium">{t("Will be taken from the warehouse")}</p>
          <ul className="text-sm">{make.bom.lines.map((l: any) => <li key={l.product_id} className="flex justify-between border-b border-line/50 py-1">
            <span>{l.product}</span><span className="num">{num((l.quantity * make.quantity) / make.bom.output_qty, 3)}</span></li>)}</ul>
          <p className="mt-3 text-sm">{t("Estimated cost")}: <b>{money(make.bom.unit_cost * make.quantity, undefined, 2)}</b></p>
        </>}
      </Modal>
    </>
  );
}
