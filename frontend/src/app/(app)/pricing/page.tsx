"use client";
import { useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { date, money } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { Badge, ErrorNote, Field, Modal, PageTitle, Table, Tabs, toast } from "@/components/ui";

const TABS = ["price lists", "promotions"] as const;
const emptyPromo = { id: 0, name: "", kind: "percent", product_id: null as number | null, category: "", percent: 10, buy_qty: 2, free_qty: 1, starts_on: "", ends_on: "", is_active: true };

export default function Pricing() {
  const { t } = useT();
  const { can } = useSession();
  const canWrite = can("settings:write");
  const [tab, setTab] = useState<(typeof TABS)[number]>("price lists");
  const lists = useApi<any[]>("/api/price-lists");
  const promos = useApi<any[]>("/api/promotions");
  const products = useApi<any[]>("/api/inventory/products");
  const productName = useMemo(() => Object.fromEntries((products.data ?? []).map((p) => [p.id, p.name])), [products.data]);
  const categories = useMemo(() => Array.from(new Set((products.data ?? []).map((p) => p.category).filter(Boolean))) as string[], [products.data]);
  const [pl, setPl] = useState<any>(null);
  const [plFilter, setPlFilter] = useState("");
  const [promo, setPromo] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const savePl = async () => {
    setError(null);
    const items = Object.entries(pl.prices as Record<string, string>).filter(([, v]) => v !== "" && v != null).map(([k, v]) => ({ product_id: +k, price: +v }));
    const body = { name: pl.name, discount_pct: +pl.discount_pct || 0, is_active: pl.is_active, items };
    try {
      await api(pl.id ? `/api/price-lists/${pl.id}` : "/api/price-lists", { method: pl.id ? "PUT" : "POST", json: body });
      setPl(null); toast("Saved"); lists.reload();
    } catch (e: any) { setError(e.message); }
  };
  const savePromo = async () => {
    setError(null);
    const { id, ...rest } = promo;
    const body = { ...rest, product_id: rest.product_id || null, category: rest.product_id ? null : rest.category || null, starts_on: rest.starts_on || null, ends_on: rest.ends_on || null };
    try {
      await api(id ? `/api/promotions/${id}` : "/api/promotions", { method: id ? "PUT" : "POST", json: body });
      setPromo(null); toast("Saved"); promos.reload();
    } catch (e: any) { setError(e.message); }
  };
  const openPl = (x?: any) => {
    setError(null); setPlFilter("");
    setPl(x ? { ...x, prices: Object.fromEntries(x.items.map((i: any) => [i.product_id, String(i.price)])) } : { id: 0, name: "", discount_pct: 0, is_active: true, prices: {} });
  };
  const promoText = (p: any) => p.kind === "percent" ? t("{n}% off", { n: p.percent }) : t("Buy {a} get {b} free", { a: p.buy_qty, b: p.free_qty });

  return (
    <>
      <PageTitle title={t("Prices & offers")} help={t("Pricing help")} actions={canWrite && (tab === "price lists"
        ? <button className="btn-primary" onClick={() => openPl()}>+ {t("New price list")}</button>
        : <button className="btn-primary" onClick={() => { setError(null); setPromo({ ...emptyPromo }); }}>+ {t("New offer")}</button>)} />
      <Tabs tabs={TABS} value={tab} onChange={setTab} />

      {tab === "price lists" && <div className="panel"><Table rows={lists.data} empty={t("No price lists yet. Make one for wholesale customers, for example.")}
        onRow={canWrite ? openPl : undefined} cols={[
          { h: t("Name"), c: (x: any) => <span className="font-medium">{x.name}</span> },
          { h: t("General discount"), c: (x: any) => x.discount_pct ? `${x.discount_pct}%` : "—" },
          { h: t("Special prices"), c: (x: any) => x.items.length },
          { h: t("Customers"), c: (x: any) => x.customers },
          { h: t("Status"), c: (x: any) => <Badge tone={x.is_active ? "good" : "neutral"}>{x.is_active ? t("Active") : t("Stopped")}</Badge> },
        ]} /></div>}

      {tab === "promotions" && <div className="panel"><Table rows={promos.data} empty={t("No offers yet.")} onRow={canWrite ? (p: any) => { setError(null); setPromo({ ...emptyPromo, ...p, category: p.category ?? "", starts_on: p.starts_on ?? "", ends_on: p.ends_on ?? "" }); } : undefined} cols={[
        { h: t("Name"), c: (p: any) => <span className="font-medium">{p.name}</span> },
        { h: t("Offer"), c: (p: any) => <Badge tone="info">{promoText(p)}</Badge> },
        { h: t("Applies to"), c: (p: any) => p.product_id ? productName[p.product_id] ?? "—" : `${t("Category")}: ${p.category}` },
        { h: t("Period"), c: (p: any) => p.starts_on || p.ends_on ? `${date(p.starts_on)} → ${date(p.ends_on)}` : t("Always") },
        { h: t("Status"), c: (p: any) => <Badge tone={p.is_active ? "good" : "neutral"}>{p.is_active ? t("Active") : t("Stopped")}</Badge> },
      ]} /></div>}

      <Modal title={pl?.id ? pl.name : t("New price list")} open={!!pl} onClose={() => setPl(null)} onSave={savePl}>
        {pl && <>
          <ErrorNote error={error} />
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("Name")}><input className="input" placeholder={t("e.g. Wholesale")} value={pl.name} onChange={(e) => setPl({ ...pl, name: e.target.value })} /></Field>
            <Field label={t("General discount %")}><input className="input" type="number" value={pl.discount_pct} onChange={(e) => setPl({ ...pl, discount_pct: e.target.value })} /></Field>
          </div>
          <label className="mt-3 flex items-center gap-2 text-sm"><input type="checkbox" className="accent-signal" checked={pl.is_active} onChange={(e) => setPl({ ...pl, is_active: e.target.checked })} />{t("Active")}</label>
          <p className="mt-4 text-xs text-slate">{t("Special price per product (leave empty to use the normal price minus the general discount).")}</p>
          <input className="input mt-2" placeholder={t("Search products…")} value={plFilter} onChange={(e) => setPlFilter(e.target.value)} />
          <div className="mt-2 max-h-72 overflow-y-auto rounded-lg border border-line">
            {products.data?.filter((p) => !plFilter || p.name.toLowerCase().includes(plFilter.toLowerCase()) || p.sku.toLowerCase().includes(plFilter.toLowerCase())).map((p) => (
              <div key={p.id} className="flex items-center gap-3 border-b border-line/60 px-3 py-1.5 text-sm">
                <span className="flex-1 truncate">{p.name}</span>
                <span className="text-xs text-slate">{money(p.sale_price, undefined, 2)}</span>
                <input className="input !w-24 shrink-0 !py-1" type="number" placeholder="—" value={pl.prices[p.id] ?? ""} onChange={(e) => setPl({ ...pl, prices: { ...pl.prices, [p.id]: e.target.value } })} />
              </div>
            ))}
          </div>
          <p className="mt-3 text-xs text-slate">{t("Give a customer this list from their customer card.")}</p>
        </>}
      </Modal>

      <Modal title={promo?.id ? promo.name : t("New offer")} open={!!promo} onClose={() => setPromo(null)} onSave={savePromo}>
        {promo && <>
          <ErrorNote error={error} />
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2"><Field label={t("Name")}><input className="input" placeholder={t("e.g. Summer offer")} value={promo.name} onChange={(e) => setPromo({ ...promo, name: e.target.value })} /></Field></div>
            <Field label={t("Type")}><select className="input" value={promo.kind} onChange={(e) => setPromo({ ...promo, kind: e.target.value })}>
              <option value="percent">{t("Percent discount")}</option><option value="bxgy">{t("Buy X get Y free")}</option></select></Field>
            {promo.kind === "percent"
              ? <Field label={t("Discount %")}><input className="input" type="number" value={promo.percent} onChange={(e) => setPromo({ ...promo, percent: +e.target.value })} /></Field>
              : <div className="grid grid-cols-2 gap-2">
                <Field label={t("Buy")}><input className="input" type="number" value={promo.buy_qty} onChange={(e) => setPromo({ ...promo, buy_qty: +e.target.value })} /></Field>
                <Field label={t("Free")}><input className="input" type="number" value={promo.free_qty} onChange={(e) => setPromo({ ...promo, free_qty: +e.target.value })} /></Field>
              </div>}
            <Field label={t("Product")}><select className="input" value={promo.product_id ?? ""} onChange={(e) => setPromo({ ...promo, product_id: e.target.value ? +e.target.value : null })}>
              <option value="">{t("— or pick a category —")}</option>{products.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
            <Field label={t("Category")}><select className="input" disabled={!!promo.product_id} value={promo.category} onChange={(e) => setPromo({ ...promo, category: e.target.value })}>
              <option value="">—</option>{categories.map((c) => <option key={c} value={c}>{c}</option>)}</select></Field>
            <Field label={t("From")}><input className="input" type="date" value={promo.starts_on} onChange={(e) => setPromo({ ...promo, starts_on: e.target.value })} /></Field>
            <Field label={t("To")}><input className="input" type="date" value={promo.ends_on} onChange={(e) => setPromo({ ...promo, ends_on: e.target.value })} /></Field>
          </div>
          <label className="mt-3 flex items-center gap-2 text-sm"><input type="checkbox" className="accent-signal" checked={promo.is_active} onChange={(e) => setPromo({ ...promo, is_active: e.target.checked })} />{t("Active")}</label>
          <p className="mt-3 text-xs text-slate">{t("Offers apply automatically at the cashier and in new sales.")}</p>
        </>}
      </Modal>
    </>
  );
}
