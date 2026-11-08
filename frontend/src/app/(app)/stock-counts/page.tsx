"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { date, money, num } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { Badge, Drawer, Field, Modal, PageTitle, StatCard, Status, Table, toast } from "@/components/ui";

export default function StockCounts() {
  const { t } = useT();
  const { can } = useSession();
  const canWrite = can("inventory:write");
  const list = useApi<any[]>("/api/stock-counts");
  const warehouses = useApi<any[]>("/api/inventory/warehouses");
  const products = useApi<any[]>("/api/inventory/products");
  const whName = useMemo(() => Object.fromEntries((warehouses.data ?? []).map((w) => [w.id, w.name])), [warehouses.data]);
  const [startOpen, setStartOpen] = useState(false);
  const [wh, setWh] = useState<number | "">("");
  const [note, setNote] = useState("");
  const [count, setCount] = useState<any>(null);
  const [edits, setEdits] = useState<Record<number, string>>({});
  const [filter, setFilter] = useState<"all" | "diff" | "todo">("all");
  const [scan, setScan] = useState("");
  const [flash, setFlash] = useState<number | null>(null);
  const scanRef = useRef<HTMLInputElement>(null);

  const open = async (id: number) => { setEdits({}); setFilter("all"); setCount(await api(`/api/stock-counts/${id}`)); };
  const start = async () => {
    if (!wh) return;
    try { const c = await api(`/api/stock-counts?warehouse_id=${wh}${note ? `&note=${encodeURIComponent(note)}` : ""}`, { method: "POST" }); setStartOpen(false); list.reload(); setEdits({}); setCount(c); }
    catch (e: any) { toast(e.message, "bad"); }
  };
  const save = async () => {
    const lines = Object.entries(edits).map(([pid, v]) => ({ product_id: +pid, counted: v === "" ? null : +v }));
    if (!lines.length) return count;
    const c = await api(`/api/stock-counts/${count.id}/lines`, { method: "PUT", json: lines });
    setEdits({}); setCount(c); return c;
  };
  const apply = async () => {
    try {
      const c = await save();
      if (!confirm(t("Set the warehouse stock to the counted quantities ({n} products)?", { n: c.counted_lines }))) return;
      setCount(await api(`/api/stock-counts/${count.id}/apply`, { method: "POST" })); list.reload(); toast("Stock updated");
    } catch (e: any) { toast(e.message, "bad"); }
  };
  // barcode scanner: each scan adds 1 to the counted quantity of that product
  const onScan = () => {
    const code = scan.trim();
    setScan("");
    if (!code || !count) return;
    const p = products.data?.find((x) => x.barcode === code || x.sku === code || x.pack_barcode === code);
    if (!p) { toast(t("No product with this barcode"), "bad"); return; }
    const step = p.pack_barcode === code && p.pack_size ? p.pack_size : 1;
    const line = count.lines.find((l: any) => l.product_id === p.id);
    const current = edits[p.id] !== undefined ? +edits[p.id] || 0 : line?.counted ?? 0;
    setEdits({ ...edits, [p.id]: String(current + step) });
    setFlash(p.id);
  };
  useEffect(() => { if (flash) { const h = setTimeout(() => setFlash(null), 900); return () => clearTimeout(h); } }, [flash]);

  const rows = (count?.lines ?? []).map((l: any) => {
    const v = edits[l.product_id];
    const counted = v !== undefined ? (v === "" ? null : +v) : l.counted;
    return { ...l, counted, difference: counted == null ? null : counted - l.expected, value: counted == null ? null : (counted - l.expected) * l.unit_cost };
  }).filter((l: any) => filter === "all" || (filter === "todo" ? l.counted == null : l.difference != null && Math.abs(l.difference) > 1e-9));
  const isOpen = count?.status === "open";

  return (
    <>
      <PageTitle title={t("Stock count")} help={t("Stock count help")} actions={canWrite && <button className="btn-primary" onClick={() => { setWh(warehouses.data?.[0]?.id ?? ""); setNote(""); setStartOpen(true); }}>+ {t("Start a count")}</button>} />
      <div className="panel"><Table rows={list.data} empty={t("No counts yet.")} onRow={(c: any) => open(c.id)} cols={[
        { h: t("Number"), c: (c: any) => <span className="font-medium">{c.number}</span> }, { h: t("Warehouse"), c: (c: any) => whName[c.warehouse_id] ?? "—" },
        { h: t("Started"), c: (c: any) => date(c.created_at) }, { h: t("Applied"), c: (c: any) => date(c.applied_at) },
        { h: t("Status"), c: (c: any) => <Status value={c.status} /> },
      ]} /></div>

      <Modal title={t("Start a count")} open={startOpen} onClose={() => setStartOpen(false)} onSave={start} saveLabel={t("Start")}>
        <div className="grid gap-3">
          <Field label={t("Warehouse")}><select className="input" value={wh} onChange={(e) => setWh(+e.target.value)}>{warehouses.data?.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</select></Field>
          <Field label={t("Note")}><input className="input" value={note} onChange={(e) => setNote(e.target.value)} /></Field>
          <p className="text-xs text-slate">{t("The system takes a snapshot of the current stock. Staff then write what they actually find on the shelves.")}</p>
        </div>
      </Modal>

      <Drawer title={count ? `${count.number} · ${whName[count.warehouse_id] ?? ""}` : ""} open={!!count} onClose={() => setCount(null)}
        actions={isOpen && canWrite && <>
          <button className="btn-ghost" onClick={() => save().then(() => toast("Saved")).catch((e) => toast(e.message, "bad"))}>{t("Save")}</button>
          <button className="btn-primary" onClick={apply}>{t("Apply to stock")}</button></>}>
        {count && <>
          <div className="mb-4 grid grid-cols-3 gap-3">
            <StatCard label={t("Counted")} value={`${count.counted_lines} / ${count.lines.length}`} />
            <StatCard label={t("Shortage")} value={money(count.shortage_value)} tone={count.shortage_value < 0 ? "bad" : "neutral"} />
            <StatCard label={t("Surplus")} value={money(count.surplus_value)} tone={count.surplus_value > 0 ? "good" : "neutral"} />
          </div>
          {isOpen && <div className="mb-3 flex gap-2">
            <input ref={scanRef} autoFocus className="input" dir="ltr" placeholder={`▮▯▮ ${t("Scan a barcode (adds 1)")}`} value={scan} onChange={(e) => setScan(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); onScan(); } }} />
          </div>}
          <div className="mb-2 flex gap-1 text-sm">
            {(["all", "todo", "diff"] as const).map((f) => <button key={f} onClick={() => setFilter(f)} className={`rounded-md px-3 py-1 ${filter === f ? "bg-signal text-white" : "text-slate hover:bg-paper"}`}>
              {t(f === "all" ? "All" : f === "todo" ? "Not counted" : "With difference")}</button>)}
          </div>
          <div className="rounded-lg border border-line"><Table rows={rows} pageSize={400} cols={[
            { h: t("Product"), c: (l: any) => <span className={flash === l.product_id ? "rounded bg-signal-soft px-1 font-semibold" : ""}>{l.product}</span> },
            { h: t("System"), c: (l: any) => num(l.expected, 2), end: true },
            { h: t("Counted"), c: (l: any) => isOpen ? <input className="input !w-24 !py-1 text-end" type="number" value={edits[l.product_id] ?? (l.counted ?? "")}
                onChange={(e) => setEdits({ ...edits, [l.product_id]: e.target.value })} /> : num(l.counted, 2), end: true },
            { h: t("Difference"), c: (l: any) => l.difference == null ? "—" : <Badge tone={l.difference < 0 ? "bad" : l.difference > 0 ? "good" : "neutral"}>{l.difference > 0 ? "+" : ""}{num(l.difference, 2)}</Badge>, end: true },
            { h: t("Value"), c: (l: any) => l.value == null ? "—" : money(l.value, undefined, 2), end: true },
          ]} /></div>
        </>}
      </Drawer>
    </>
  );
}
