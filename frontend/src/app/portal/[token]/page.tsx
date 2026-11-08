"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { API_URL, logoUrl } from "@/lib/api";
import { applyBrand } from "@/lib/brand";
import { date, money, setFormatCurrency } from "@/lib/format";
import { LangSwitch, useT } from "@/lib/i18n";
import { Badge, ErrorNote, Field, Status, Table, Tabs, toast } from "@/components/ui";

const TABS = ["invoices", "orders", "installments", "statement", "payments i sent", "new order"] as const;

/** Customer self-service page (link sent by the company). No login needed. */
export default function Portal() {
  const { t } = useT();
  const { token } = useParams<{ token: string }>();
  const [d, setD] = useState<any>(null);
  const [error, setError] = useState<false | "invalid" | "expired">(false);
  const [tab, setTab] = useState<(typeof TABS)[number]>("invoices");
  const [pay, setPay] = useState({ amount: "", reference: "", note: "" });
  const [file, setFile] = useState<File | null>(null);
  const [sendError, setSendError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [catalog, setCatalog] = useState<any[] | null>(null);
  const [cart, setCart] = useState<Record<number, number>>({});
  const [orderNote, setOrderNote] = useState("");
  const [search, setSearch] = useState("");

  const load = useCallback(() => {
    fetch(`${API_URL}/api/public/portal/${token}`).then((r) => (r.ok ? r.json() : Promise.reject(r.status))).then((x) => {
      setFormatCurrency(x.company.currency); applyBrand(x.company.brand_color); setD(x);
    }).catch((status) => setError(status === 410 ? "expired" : "invalid"));
  }, [token]);
  useEffect(load, [load]);

  const send = async () => {
    setSendError(null);
    if (!(+pay.amount > 0)) { setSendError(t("Write the amount you paid")); return; }
    setBusy(true);
    const fd = new FormData();
    fd.append("amount", pay.amount);
    if (pay.reference) fd.append("reference", pay.reference);
    if (pay.note) fd.append("note", pay.note);
    if (file) fd.append("file", file);
    try {
      const r = await fetch(`${API_URL}/api/public/portal/${token}/payment-proof`, { method: "POST", body: fd });
      if (!r.ok) throw new Error((await r.json()).detail);
      toast(t("Sent. We'll confirm it after checking."));
      setPay({ amount: "", reference: "", note: "" }); setFile(null); load(); setTab("payments i sent");
    } catch (e: any) { setSendError(e.message); } finally { setBusy(false); }
  };

  useEffect(() => {
    if (tab !== "new order" || catalog) return;
    fetch(`${API_URL}/api/public/portal/${token}/catalog`).then((r) => (r.ok ? r.json() : [])).then(setCatalog).catch(() => setCatalog([]));
  }, [tab, catalog, token]);

  const sendOrder = async () => {
    const items = Object.entries(cart).filter(([, q]) => q > 0).map(([product_id, quantity]) => ({ product_id: +product_id, quantity }));
    if (!items.length) { toast(t("Choose at least one product"), "bad"); return; }
    setBusy(true);
    try {
      const r = await fetch(`${API_URL}/api/public/portal/${token}/order`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ items, note: orderNote || null }) });
      const x = await r.json();
      if (!r.ok) throw new Error(x.detail);
      toast(t("Order {n} sent. We'll contact you to confirm.", { n: x.number }));
      setCart({}); setOrderNote(""); load(); setTab("orders");
    } catch (e: any) { toast(e.message, "bad"); } finally { setBusy(false); }
  };

  if (error) return <main className="flex min-h-screen items-center justify-center p-6"><div className="panel max-w-md p-8 text-center text-slate">
    {error === "expired" ? t("This link has expired. Ask the company for a new one.") : t("This link is not valid.")}</div></main>;
  if (!d) return <main className="p-10 text-center text-sm text-slate">{t("Loading…")}</main>;
  const c = d.company;

  return (
    <main className="min-h-screen px-4 py-6">
      <div className="mx-auto max-w-4xl">
        <header className="mb-6 flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            {c.logo ? <img src={logoUrl(c.id, c.logo_version)} alt="" className="h-12 w-12 rounded-xl object-contain" />
              : <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-signal text-xl font-bold text-white">{c.name.slice(0, 1)}</div>}
            <div><div className="text-lg font-semibold">{c.name}</div>{c.phone && <a className="text-sm text-slate" dir="ltr" href={`tel:${c.phone}`}>{c.phone}</a>}</div>
          </div>
          <div className="flex items-center gap-2 print:hidden"><button className="btn-ghost" onClick={() => window.print()}>🖨 {t("Print / PDF")}</button><LangSwitch /></div>
        </header>
        <div className="grid gap-4 md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
          <section className="panel p-5">
            <div className="text-sm text-slate">{t("Hello")} {d.customer.name}</div>
            <div className="mt-2 text-sm text-slate">{t("Your balance")}</div>
            <div className={`text-3xl font-bold ${d.balance > 0 ? "text-rust" : "text-moss"}`}>{money(d.balance, undefined, 2)}</div>
            <p className="mt-1 text-xs text-slate">{d.balance > 0 ? t("This is what you owe us.") : t("You owe nothing. Thank you!")}</p>
          </section>
          <section className="panel p-5">
            <h2 className="text-base font-semibold">{t("I paid — tell the company")}</h2>
            {c.payment_instructions && <p className="mt-1 whitespace-pre-line rounded-lg bg-paper p-2 text-xs">{c.payment_instructions}</p>}
            <ErrorNote error={sendError} />
            <div className="mt-3 grid gap-2">
              <div className="grid grid-cols-2 gap-2">
                <Field label={t("Amount")}><input className="input" type="number" inputMode="decimal" value={pay.amount} onChange={(e) => setPay({ ...pay, amount: e.target.value })} /></Field>
                <Field label={t("Transfer number")}><input className="input" dir="ltr" value={pay.reference} onChange={(e) => setPay({ ...pay, reference: e.target.value })} /></Field>
              </div>
              <Field label={t("Receipt photo (optional)")}><input className="input !py-1.5 text-sm" type="file" accept="image/*,application/pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></Field>
              <button className="btn-primary" disabled={busy} onClick={send}>{busy ? "…" : t("Send")}</button>
            </div>
          </section>
        </div>
        <div className="mt-6"><Tabs tabs={TABS.filter((x) => (x !== "new order" || d.can_order) && (x !== "installments" || d.installments.length))} value={tab} onChange={setTab} /></div>
        {tab === "orders" && <div className="panel"><Table rows={d.orders} empty={t("No orders yet.")} cols={[
          { h: t("Number"), c: (o: any) => <span className="font-medium">{o.number}</span> }, { h: t("Date"), c: (o: any) => date(o.date) },
          { h: t("Total"), c: (o: any) => money(o.total, undefined, 2), end: true }, { h: t("Status"), c: (o: any) => <Status value={o.status} /> },
        ]} /></div>}
        {tab === "installments" && <div className="panel"><Table rows={d.installments} cols={[
          { h: t("Invoice"), c: (s: any) => s.invoice }, { h: "#", c: (s: any) => s.seq }, { h: t("Due"), c: (s: any) => date(s.due_date) },
          { h: t("Amount"), c: (s: any) => money(s.amount, undefined, 2), end: true }, { h: t("Remaining"), c: (s: any) => money(s.remaining, undefined, 2), end: true },
          { h: t("Status"), c: (s: any) => <Badge tone={s.status === "late" ? "bad" : s.status === "partial" ? "warn" : "neutral"}>{t(`inst.${s.status}`)}</Badge> },
        ]} /></div>}
        {tab === "new order" && <div className="panel p-4">
          <p className="mb-3 text-sm text-slate">{t("Choose what you need. The company confirms prices and availability before delivering.")}</p>
          <input className="input mb-3" placeholder={t("Search")} value={search} onChange={(e) => setSearch(e.target.value)} />
          <div className="max-h-[50vh] divide-y divide-line overflow-y-auto">{(catalog ?? []).filter((p) => !search || p.name.toLowerCase().includes(search.toLowerCase())).map((p) => (
            <div key={p.id} className="flex items-center justify-between gap-3 py-2">
              <div><div className="font-medium">{p.name}</div><div className="text-xs text-slate">{money(p.price, undefined, 2)} / {p.unit}</div></div>
              <input className="input !w-24" type="number" min={0} inputMode="decimal" value={cart[p.id] ?? ""} onChange={(e) => setCart({ ...cart, [p.id]: +e.target.value })} />
            </div>))}</div>
          <textarea className="input mt-3 h-16" placeholder={t("Notes (delivery time, address…)")} value={orderNote} onChange={(e) => setOrderNote(e.target.value)} />
          <div className="mt-3 flex items-center justify-between gap-3">
            <span className="text-sm text-slate">{t("Estimated total")}: <b>{money((catalog ?? []).reduce((a, p) => a + (cart[p.id] || 0) * p.price, 0), undefined, 2)}</b></span>
            <button className="btn-primary" disabled={busy} onClick={sendOrder}>{busy ? "…" : t("Send order")}</button>
          </div>
        </div>}
        {tab === "invoices" && <div className="panel"><Table rows={d.invoices} cols={[
          { h: t("Number"), c: (i: any) => i.token ? <Link className="font-medium text-signal" href={`/i/${i.token}`}>{i.number}</Link> : i.number },
          { h: t("Date"), c: (i: any) => date(i.date) }, { h: t("Due"), c: (i: any) => date(i.due) },
          { h: t("Total"), c: (i: any) => money(i.total, i.currency, 2), end: true }, { h: t("Remaining"), c: (i: any) => money(i.balance, i.currency, 2), end: true },
          { h: t("Status"), c: (i: any) => <Status value={i.status} /> },
        ]} /></div>}
        {tab === "statement" && <div className="panel"><Table rows={[...d.statement].reverse()} cols={[
          { h: t("Date"), c: (r: any) => date(r.date) }, { h: t("Document"), c: (r: any) => <span>{t(r.kind)} · {r.number}</span> },
          { h: t("Debit"), c: (r: any) => r.debit ? money(r.debit, undefined, 2) : "", end: true }, { h: t("Credit"), c: (r: any) => r.credit ? money(r.credit, undefined, 2) : "", end: true },
          { h: t("Balance"), c: (r: any) => money(r.balance, undefined, 2), end: true },
        ]} /></div>}
        {tab === "payments i sent" && <div className="panel"><Table rows={d.proofs} empty={t("You haven't sent any payment notices.")} cols={[
          { h: t("Date"), c: (p: any) => date(p.created_at) }, { h: t("Reference"), c: (p: any) => <span dir="ltr">{p.reference ?? "—"}</span> },
          { h: t("Amount"), c: (p: any) => money(p.amount, undefined, 2), end: true },
          { h: t("Status"), c: (p: any) => <Badge tone={p.status === "confirmed" ? "good" : p.status === "rejected" ? "bad" : "warn"}>{t(`proof.${p.status}`)}</Badge> },
        ]} /></div>}
      </div>
    </main>
  );
}
