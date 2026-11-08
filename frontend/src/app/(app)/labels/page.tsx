"use client";
import { useMemo, useState } from "react";
import { useApi } from "@/lib/hooks";
import { money } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { code128Svg } from "@/lib/code128";
import { Field, PageTitle } from "@/components/ui";

const SIZES = { small: { w: 38, h: 25 }, medium: { w: 50, h: 30 }, large: { w: 70, h: 40 } } as const;

export default function Labels() {
  const { t } = useT();
  const { company } = useSession();
  const products = useApi<any[]>("/api/inventory/products");
  const [q, setQ] = useState("");
  const [copies, setCopies] = useState<Record<number, number>>({});
  const [size, setSize] = useState<keyof typeof SIZES>("medium");
  const [show, setShow] = useState({ name: true, price: true, company: false });
  const byId = useMemo(() => Object.fromEntries((products.data ?? []).map((p) => [p.id, p])), [products.data]);
  const labels = Object.entries(copies).flatMap(([id, n]) => Array.from({ length: Math.max(0, n) }, () => byId[+id])).filter(Boolean);
  const dim = SIZES[size];
  const print = () => {
    document.body.classList.add("printing-labels");
    window.print();
    setTimeout(() => document.body.classList.remove("printing-labels"), 500);
  };
  const setAllStock = () => setCopies(Object.fromEntries((products.data ?? []).filter((p) => p.total_stock > 0).map((p) => [p.id, Math.ceil(p.total_stock)])));

  return (
    <>
      <PageTitle title={t("Barcode labels")} help={t("Labels help")} actions={<button className="btn-primary" disabled={!labels.length} onClick={print}>🖨 {t("Print {n} labels", { n: labels.length })}</button>} />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
        <section className="panel p-4 print:hidden">
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("Label size")}><select className="input" value={size} onChange={(e) => setSize(e.target.value as any)}>
              {Object.entries(SIZES).map(([k, v]) => <option key={k} value={k}>{v.w}×{v.h} mm</option>)}</select></Field>
            <div className="flex flex-col justify-end gap-1 text-sm">
              {(["name", "price", "company"] as const).map((k) => <label key={k} className="flex items-center gap-2">
                <input type="checkbox" className="accent-signal" checked={show[k]} onChange={(e) => setShow({ ...show, [k]: e.target.checked })} />
                {t(k === "name" ? "Product name" : k === "price" ? "Price" : "Company name")}</label>)}
            </div>
          </div>
          <div className="mt-4 flex gap-2">
            <input className="input" placeholder={t("Search products…")} value={q} onChange={(e) => setQ(e.target.value)} />
            <button className="btn-ghost shrink-0" onClick={setAllStock}>{t("One per item in stock")}</button>
            <button className="btn-ghost shrink-0" onClick={() => setCopies({})}>{t("Clear")}</button>
          </div>
          <div className="mt-3 max-h-[60vh] overflow-y-auto rounded-lg border border-line">
            {products.data?.filter((p) => !q || `${p.name} ${p.sku} ${p.barcode ?? ""}`.toLowerCase().includes(q.toLowerCase())).map((p) => (
              <div key={p.id} className="flex items-center gap-3 border-b border-line/60 px-3 py-2 text-sm">
                <div className="min-w-0 flex-1"><div className="truncate">{p.name}</div><div className="text-xs text-slate" dir="ltr">{p.barcode || p.sku}</div></div>
                <input className="input !w-20 shrink-0 !py-1 text-center" type="number" min={0} value={copies[p.id] ?? 0} onChange={(e) => setCopies({ ...copies, [p.id]: +e.target.value })} />
              </div>
            ))}
          </div>
          <p className="mt-3 text-xs text-slate">{t("Products without a barcode use their SKU. Works with any label printer or A4 sticker paper.")}</p>
        </section>
        <section>
          {!labels.length && <div className="panel p-10 text-center text-sm text-slate">{t("Choose products and how many labels for each.")}</div>}
          <div className="label-sheet flex flex-wrap gap-[2mm]" dir="ltr">
            {labels.map((p, i) => (
              <div key={i} className="label flex flex-col items-center justify-center overflow-hidden rounded border border-line bg-white text-center text-black"
                style={{ width: `${dim.w}mm`, height: `${dim.h}mm`, padding: "1.5mm" }}>
                {show.company && <div className="w-full truncate text-[7px]">{company?.name}</div>}
                {show.name && <div className="w-full truncate text-[9px] font-semibold leading-tight" dir="auto">{p.name}</div>}
                <div className="w-full flex-1" style={{ minHeight: 0 }} dangerouslySetInnerHTML={{ __html: code128Svg(p.barcode || p.sku, 40).replace("<svg ", '<svg style="width:100%;height:100%" ') }} />
                <div className="flex w-full justify-between text-[8px] leading-tight"><span>{p.barcode || p.sku}</span>{show.price && <b>{money(p.sale_price, undefined, 2)}</b>}</div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </>
  );
}
