"use client";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { API_URL, logoUrl } from "@/lib/api";
import { applyBrand } from "@/lib/brand";
import { money, setFormatCurrency } from "@/lib/format";
import { LangSwitch, useT } from "@/lib/i18n";
import { whatsappLink } from "@/components/money";
import { ErrorNote, Field } from "@/components/ui";

/** Public online shop / catalog: customers pick products and send an order (becomes a quotation for the company). */
export default function Shop() {
  const { t } = useT();
  const { slug } = useParams<{ slug: string }>();
  const [d, setD] = useState<any>(null);
  const [error, setError] = useState(false);
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("");
  const [cart, setCart] = useState<Record<number, number>>({});
  const [checkout, setCheckout] = useState(false);
  const [form, setForm] = useState({ name: "", phone: "", address: "", note: "" });
  const [sendError, setSendError] = useState<string | null>(null);
  const [done, setDone] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetch(`${API_URL}/api/public/shop/${slug}`).then((r) => (r.ok ? r.json() : Promise.reject())).then((x) => {
      setFormatCurrency(x.company.currency); applyBrand(x.company.brand_color); setD(x);
    }).catch(() => setError(true));
    try { const saved = JSON.parse(localStorage.getItem(`cart:${slug}`) ?? "{}"); if (saved && typeof saved === "object") setCart(saved); } catch {}
  }, [slug]);
  useEffect(() => { try { localStorage.setItem(`cart:${slug}`, JSON.stringify(cart)); } catch {} }, [cart, slug]);

  const byId = useMemo(() => Object.fromEntries((d?.products ?? []).map((p: any) => [p.id, p])), [d]);
  const cats = useMemo(() => Array.from(new Set((d?.products ?? []).map((p: any) => p.category).filter(Boolean))) as string[], [d]);
  const lines = Object.entries(cart).filter(([id, n]) => n > 0 && byId[+id]).map(([id, n]) => ({ p: byId[+id], n }));
  const total = lines.reduce((s, l) => s + l.p.price * l.n, 0);
  const count = lines.reduce((s, l) => s + l.n, 0);
  const add = (id: number, n: number) => setCart((c) => ({ ...c, [id]: Math.max(0, (c[id] ?? 0) + n) }));

  const order = async () => {
    setSendError(null); setBusy(true);
    try {
      const r = await fetch(`${API_URL}/api/public/shop/${slug}/order`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...form, items: lines.map((l) => ({ product_id: l.p.id, quantity: l.n })) }) });
      const x = await r.json();
      if (!r.ok) throw new Error(x.detail);
      setDone(x); setCart({}); setCheckout(false);
    } catch (e: any) { setSendError(e.message); } finally { setBusy(false); }
  };

  if (error) return <main className="flex min-h-screen items-center justify-center p-6"><div className="panel max-w-md p-8 text-center text-slate">{t("This shop is not available.")}</div></main>;
  if (!d) return <main className="p-10 text-center text-sm text-slate">{t("Loading…")}</main>;
  const c = d.company;
  const waText = lines.map((l) => `${l.n} × ${l.p.name}`).join("\n") + `\n${t("Total")}: ${money(total, undefined, 2)}`;

  return (
    <main className="min-h-screen pb-28">
      <header className="sticky top-0 z-10 border-b border-line bg-white/95 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-3">
            {c.logo ? <img src={logoUrl(c.id, c.logo_version)} alt="" className="h-10 w-10 rounded-lg object-contain" />
              : <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-signal font-bold text-white">{c.name.slice(0, 1)}</div>}
            <div><div className="font-semibold">{c.name}</div>{c.address && <div className="text-xs text-slate">{c.address}</div>}</div>
          </div>
          <LangSwitch />
        </div>
      </header>
      <div className="mx-auto max-w-5xl px-4 py-5">
        {done && <div className="panel mb-5 border-moss bg-moss-soft p-5 text-moss">
          <div className="text-lg font-semibold">✓ {t("Your order was sent")}</div>
          <p className="text-sm">{t("Order number")} <b dir="ltr">{done.number}</b> · {money(done.total, undefined, 2)}. {t("We'll call you to confirm.")}</p>
        </div>}
        <div className="mb-4 flex flex-wrap gap-2">
          <input className="input max-w-xs" placeholder={t("Search products…")} value={q} onChange={(e) => setQ(e.target.value)} />
          <button onClick={() => setCat("")} className={`rounded-full px-3 py-1.5 text-sm ${!cat ? "bg-signal text-white" : "bg-white text-slate"}`}>{t("All")}</button>
          {cats.map((k) => <button key={k} onClick={() => setCat(k)} className={`rounded-full px-3 py-1.5 text-sm ${cat === k ? "bg-signal text-white" : "bg-white text-slate"}`}>{k}</button>)}
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {d.products.filter((p: any) => (!cat || p.category === cat) && (!q || p.name.toLowerCase().includes(q.toLowerCase()))).map((p: any) => (
            <div key={p.id} className={`panel flex flex-col p-3 ${!p.in_stock ? "opacity-60" : ""}`}>
              <div className="flex-1"><div className="text-sm font-medium leading-snug">{p.name}</div><div className="text-xs text-slate">{p.unit}</div></div>
              <div className="mt-2 font-semibold">{money(p.price, undefined, 2)}</div>
              {!p.in_stock ? <div className="mt-2 text-xs text-rust">{t("Out of stock")}</div>
                : cart[p.id] ? <div className="mt-2 flex items-center justify-between rounded-lg border border-line">
                  <button className="px-3 py-1 text-lg" onClick={() => add(p.id, -1)}>−</button><span className="font-semibold">{cart[p.id]}</span><button className="px-3 py-1 text-lg" onClick={() => add(p.id, 1)}>+</button></div>
                  : <button className="btn-primary mt-2 !py-1.5" onClick={() => add(p.id, 1)}>+ {t("Add")}</button>}
            </div>
          ))}
        </div>
      </div>

      {count > 0 && !checkout && (
        <div className="fixed inset-x-0 bottom-0 border-t border-line bg-white p-3 shadow-lg">
          <div className="mx-auto flex max-w-5xl items-center justify-between gap-3">
            <div><div className="text-xs text-slate">{t("{n} items", { n: count })}</div><div className="text-lg font-bold">{money(total, undefined, 2)}</div></div>
            <button className="btn-primary" onClick={() => setCheckout(true)}>{t("Order now")}</button>
          </div>
        </div>
      )}
      {checkout && (
        <div className="fixed inset-0 z-20 flex items-end justify-center bg-black/30 sm:items-center" onClick={() => setCheckout(false)}>
          <div className="max-h-[90vh] w-full max-w-md overflow-y-auto rounded-t-2xl bg-white p-5 sm:rounded-2xl" onClick={(e) => e.stopPropagation()}>
            <h2 className="mb-3 text-lg font-semibold">{t("Your order")}</h2>
            <ul className="mb-3 text-sm">{lines.map((l) => <li key={l.p.id} className="flex justify-between border-b border-line/60 py-1.5"><span>{l.n} × {l.p.name}</span><span>{money(l.p.price * l.n, undefined, 2)}</span></li>)}
              <li className="flex justify-between py-2 font-bold"><span>{t("Total")}</span><span>{money(total, undefined, 2)}</span></li></ul>
            <ErrorNote error={sendError} />
            <div className="grid gap-2">
              <Field label={t("Your name")}><input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
              <Field label={t("Phone")}><input className="input" dir="ltr" inputMode="tel" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></Field>
              <Field label={t("Address")}><input className="input" value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} /></Field>
              <Field label={t("Note")}><input className="input" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} /></Field>
              <button className="btn-primary mt-1" disabled={busy} onClick={order}>{busy ? "…" : t("Send order")}</button>
              {c.phone && <a className="btn-ghost justify-center" target="_blank" rel="noreferrer" href={whatsappLink(c.phone, waText)}>{t("Or send it on WhatsApp")}</a>}
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
