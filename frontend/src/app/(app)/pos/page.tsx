"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { money, num } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { ErrorNote, Field, Modal, toast } from "@/components/ui";

/** price: null = automatic (price list / offers from the server); a number = the cashier typed it. */
type Line = { key: string; product: any; unit: "unit" | "pack"; qty: number; price: number | null; discount: number };
type Queued = { client_ref: string; payload: any; total: number; at: string; error?: string };

// ---------------------------------------------------------------- offline helpers
const store = {
  get<T>(k: string, fallback: T): T { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : fallback; } catch { return fallback; } },
  set(k: string, v: unknown) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
};
const isNetworkError = (e: unknown) => !(e instanceof ApiError);
const uuid = () => (typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`);

/** GET that falls back to the last good copy when the network is down (products, customers, setup). */
function useCached<T>(path: string, key: string) {
  const [data, setData] = useState<T | null>(null);
  const [offline, setOffline] = useState(false);
  const reload = useCallback(() => {
    api<T>(path).then((d) => { setData(d); setOffline(false); store.set(key, d); })
      .catch((e) => { if (isNetworkError(e)) { setData(store.get<T | null>(key, null)); setOffline(true); } });
  }, [path, key]);
  useEffect(() => { reload(); }, [reload]);
  return { data, offline, reload };
}

export default function POS() {
  const { t, lang } = useT();
  const { company, user } = useSession();
  const uid = user?.id ?? 0;
  const setupQ = useCached<any>("/api/pos/setup", `pos:setup:${uid}`);
  const products = useCached<any[]>("/api/inventory/products", `pos:products:${company?.id}`);
  const customersQ = useCached<any[]>("/api/customers?limit=2000", `pos:customers:${company?.id}`);
  const setup = setupQ.data, customers = customersQ.data;
  const today = useApi<any>("/api/pos/today");
  const shift = useApi<any>("/api/pos/shift");
  const [q, setQ] = useState("");
  const [cart, setCart] = useState<Line[]>([]);
  const [warehouse, setWarehouse] = useState<number>(0);
  const [customer, setCustomer] = useState<number>(0);
  const [discount, setDiscount] = useState(0);
  const [method, setMethod] = useState<"cash" | "card" | "bank" | "credit">("cash");
  const [payCur, setPayCur] = useState<string>("");
  const [received, setReceived] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<any>(null);
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [quote, setQuote] = useState<any>(null);
  const [online, setOnline] = useState(true);
  const [queue, setQueue] = useState<Queued[]>([]);
  const [queueOpen, setQueueOpen] = useState(false);
  const [shiftModal, setShiftModal] = useState<"open" | "close" | null>(null);
  const [shiftForm, setShiftForm] = useState({ amount: "", note: "" });
  const [closed, setClosed] = useState<any>(null);
  const scan = useRef<HTMLInputElement>(null);

  useEffect(() => { if (setup?.warehouses?.length && !warehouse) setWarehouse(setup.warehouses[0].id); }, [setup, warehouse]);
  useEffect(() => { scan.current?.focus(); }, [done]);

  // ---------------- offline queue: sales made without internet are sent when it comes back
  const saveQueue = (qu: Queued[]) => { setQueue(qu); store.set(`pos:queue:${uid}`, qu); };
  const sync = useCallback(async () => {
    const pending = store.get<Queued[]>(`pos:queue:${uid}`, []);
    if (!pending.length) return;
    const left: Queued[] = [];
    let sent = 0;
    for (const s of pending) {
      try { await api("/api/pos/sale", { method: "POST", json: s.payload }); sent++; }
      catch (e: any) { if (isNetworkError(e)) { left.push(s); setOnline(false); } else left.push({ ...s, error: e.message }); }
    }
    saveQueue(left);
    if (sent) { toast(t("{n} offline sales were synced", { n: sent })); products.reload(); today.reload(); shift.reload(); }
  }, [uid]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    setQueue(store.get<Queued[]>(`pos:queue:${uid}`, []));
    setOnline(navigator.onLine);
    const up = () => { setOnline(true); sync(); };
    const down = () => setOnline(false);
    window.addEventListener("online", up); window.addEventListener("offline", down);
    const h = setInterval(() => { if (navigator.onLine) sync(); }, 30000);
    sync();
    return () => { window.removeEventListener("online", up); window.removeEventListener("offline", down); clearInterval(h); };
  }, [uid, sync]);
  const isOffline = !online || products.offline;

  // ---------------- prices: ask the server (price lists, offers, VAT); fall back to a local calculation offline
  const items = cart.map((l) => ({ product_id: l.product.id, quantity: l.qty, unit: l.unit, unit_price: l.price, discount_pct: l.discount }));
  const itemsKey = JSON.stringify([items, customer, discount]);
  useEffect(() => {
    if (!cart.length) { setQuote(null); return; }
    const h = setTimeout(() => {
      api("/api/sales/quote", { method: "POST", json: { customer_id: customer || null, items: items.filter((i) => i.quantity > 0), discount_pct: discount } })
        .then(setQuote).catch(() => setQuote(null));
    }, 250);
    return () => clearTimeout(h);
  }, [itemsKey]); // eslint-disable-line react-hooks/exhaustive-deps
  // quote lines come back in cart order; "free" lines (buy X get Y) follow the line they belong to
  const priced = useMemo(() => {
    const per: { price: number; discount: number; total: number; promo?: string; free: number }[] = [];
    if (quote && cart.every((l) => l.qty > 0)) {
      for (const ln of quote.lines) {
        if (ln.free) { if (per.length) per[per.length - 1].free += ln.quantity; }
        else per.push({ price: ln.price, discount: ln.discount_pct, total: ln.line_total, promo: ln.promo ?? undefined, free: 0 });
      }
    }
    return per.length && per.length === cart.length ? per : null;
  }, [quote, cart]);

  const rate = company?.tax_rate ?? 0;
  const inclusive = !!company?.prices_include_tax;
  const localPrice = (l: Line) => l.price ?? (l.unit === "pack" ? (l.product.pack_price || l.product.sale_price * l.product.pack_size) : l.product.sale_price);
  const lineTotal = (l: Line, i: number) => priced?.[i]?.total ?? l.qty * localPrice(l) * (1 - l.discount / 100);
  const linesSum = cart.reduce((s, l, i) => s + lineTotal(l, i), 0);
  const afterDiscount = linesSum * (1 - discount / 100);
  const localNet = inclusive ? afterDiscount / (1 + rate / 100) : afterDiscount;
  const localTax = inclusive ? afterDiscount - localNet : localNet * rate / 100;
  const total = priced ? quote.total : Math.round((inclusive ? afterDiscount : localNet + localTax) * 100) / 100;
  const tax = priced ? quote.tax : localTax;
  const needsApproval: string[] = priced ? quote.needs_approval ?? [] : [];
  const fx = setup?.currencies?.find((c: any) => c.code === payCur);
  const totalInPayCur = fx ? Math.round((total / fx.rate) * 100) / 100 : total;
  const receivedBase = received ? +received * (fx?.rate ?? 1) : 0;
  const change = method === "cash" && received ? Math.max(receivedBase - total, 0) : 0;

  const visible = useMemo(() => {
    const list = products.data ?? [];
    if (!q.trim()) return list.slice(0, 60);
    const s = q.toLowerCase();
    return list.filter((p) => p.name.toLowerCase().includes(s) || p.sku.toLowerCase().includes(s) || p.barcode === q || p.pack_barcode === q).slice(0, 60);
  }, [products.data, q]);

  const add = (p: any, unit: "unit" | "pack" = "unit") => {
    setCart((c) => {
      const i = c.findIndex((l) => l.product.id === p.id && l.unit === unit);
      if (i >= 0) return c.map((l, j) => (j === i ? { ...l, qty: l.qty + 1 } : l));
      return [...c, { key: `${p.id}-${unit}-${Date.now()}`, product: p, unit, qty: 1, price: null, discount: 0 }];
    });
  };
  const onScan = async () => {
    const code = q.trim();
    if (!code) return;
    const exact = (products.data ?? []).filter((p) => p.barcode === code || p.pack_barcode === code || p.sku === code);
    if (exact.length === 1) { add(exact[0], exact[0].pack_barcode === code && exact[0].pack_size ? "pack" : "unit"); setQ(""); return; }
    if (visible.length === 1) { add(visible[0]); setQ(""); return; }
    try { const r = await api(`/api/inventory/barcode/${encodeURIComponent(code)}`); add(r.product, r.unit); setQ(""); }
    catch { if (!visible.length) toast(t("No product with this barcode"), "bad"); }
  };
  const setLine = (key: string, patch: Partial<Line>) => setCart((c) => c.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  const switchUnit = (l: Line) => setLine(l.key, { unit: l.unit === "unit" ? "pack" : "unit", price: null });

  const reset = () => { setCart([]); setDiscount(0); setReceived(""); setCustomer(0); setMethod("cash"); setPayCur(""); setQuote(null); };
  const pay = async () => {
    if (!cart.length || busy) return;
    if (method === "credit" && !customer) { setError(t("Choose a customer to sell on credit.")); return; }
    if (method === "cash" && received && receivedBase + 0.01 < total) { setError(t("Cash received is less than the total")); return; }
    setBusy(true); setError(null);
    const payload = {
      customer_id: customer || null, warehouse_id: warehouse || null, discount_pct: discount, client_ref: uuid(),
      items: items.map((i) => ({ ...i, unit_price: i.unit_price ?? undefined })),
      payments: method === "credit" ? [] : [{ method, amount: totalInPayCur, currency: payCur || null }],
      cash_received: method === "cash" && received ? Math.round(receivedBase * 100) / 100 : null,
    };
    const receiptBase = { lines: cart.map((l, i) => ({ ...l, total: lineTotal(l, i), free: priced?.[i]?.free ?? 0 })), discount, method, payCur, totalInPayCur,
      received: +received || totalInPayCur, customerName: customers?.find((c) => c.id === customer)?.name };
    try {
      const r = await api("/api/pos/sale", { method: "POST", json: payload });
      setDone({ ...r, ...receiptBase });
      reset(); products.reload(); today.reload(); shift.reload();
    } catch (e: any) {
      if (isNetworkError(e)) {
        // no internet: keep the sale on this device and send it later (the server ignores duplicates)
        saveQueue([...store.get<Queued[]>(`pos:queue:${uid}`, []), { client_ref: payload.client_ref, payload, total, at: new Date().toISOString() }]);
        setOnline(false);
        setDone({ ...receiptBase, offline: true, total, tax_amount: tax, change, invoice_number: `OFFLINE-${payload.client_ref.slice(0, 8).toUpperCase()}` });
        reset();
      } else setError(e.message);
    } finally { setBusy(false); }
  };

  const shiftAction = async () => {
    try {
      if (shiftModal === "open") { await api("/api/pos/shift/open", { method: "POST", json: { opening_float: +shiftForm.amount || 0 } }); toast("Shift opened"); setShiftModal(null); }
      else { const r = await api("/api/pos/shift/close", { method: "POST", json: { counted_cash: +shiftForm.amount || 0, note: shiftForm.note || null } }); setClosed(r); setShiftModal(null); }
      shift.reload();
    } catch (e: any) { toast(e.message, "bad"); }
  };

  const printReceipt = () => {
    document.body.classList.add("printing-receipt");
    window.print();
    setTimeout(() => document.body.classList.remove("printing-receipt"), 500);
  };

  // F9 = pay, Esc = clear search
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === "F9") { e.preventDefault(); pay(); } if (e.key === "Escape") setQ(""); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  });

  return (
    <div className="-mx-4 -my-6 grid min-h-[calc(100vh-1rem)] gap-0 sm:-mx-8 lg:grid-cols-[1fr_420px]">
      <section className="flex flex-col p-4 sm:p-6">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <h1 className="me-auto text-xl font-semibold">{t("Point of sale")}</h1>
          {isOffline && <span className="rounded-full bg-amber-soft px-3 py-1 text-xs font-medium text-amber">⚡ {t("Offline — sales are saved on this device")}</span>}
          {queue.length > 0 && <button className="rounded-full bg-rust-soft px-3 py-1 text-xs font-medium text-rust" onClick={() => setQueueOpen(true)}>{t("{n} sales waiting to sync", { n: queue.length })}</button>}
          {setup?.warehouses?.length > 1 && <select className="input !w-auto" value={warehouse} onChange={(e) => setWarehouse(+e.target.value)}>{setup.warehouses.map((w: any) => <option key={w.id} value={w.id}>{w.name}</option>)}</select>}
          {!shift.loading && !shift.error && !isOffline && (shift.data
            ? <button className="btn-ghost" onClick={() => { shift.reload(); setShiftForm({ amount: "", note: "" }); setShiftModal("close"); }}>🔒 {t("Close shift")}</button>
            : <button className="btn-ghost" onClick={() => { setShiftForm({ amount: "", note: "" }); setShiftModal("open"); }}>🔓 {t("Open shift")}</button>)}
          <button className="btn-ghost" onClick={() => { today.reload(); setSummaryOpen(true); }}>{t("My day")}</button>
        </div>
        <input ref={scan} className="input !py-3 text-base" placeholder={`🔍 ${t("Scan a barcode or type a product name, then Enter")}`} value={q}
          onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && onScan()} />
        <div className="mt-4 grid flex-1 auto-rows-min grid-cols-2 gap-3 overflow-y-auto sm:grid-cols-3 xl:grid-cols-4">
          {visible.map((p) => (
            <button key={p.id} onClick={() => add(p)} className="panel flex flex-col items-start p-3 text-start transition hover:border-signal hover:shadow-sm">
              <span className="line-clamp-2 font-medium leading-snug">{p.name}</span>
              <span className="mt-auto pt-2 text-lg font-semibold text-signal">{money(p.sale_price, undefined, 2)}</span>
              <span className={`text-xs ${p.total_stock <= 0 ? "text-rust" : "text-slate"}`}>{num(p.total_stock)} {t("in stock")}</span>
              {p.pack_size > 0 && <span onClick={(e) => { e.stopPropagation(); add(p, "pack"); }} className="mt-1 rounded bg-paper px-2 py-0.5 text-xs text-signal hover:bg-signal-soft">+ {p.pack_unit || t("pack")} ({num(p.pack_size)})</span>}
            </button>
          ))}
          {products.data && !visible.length && <div className="col-span-full p-6 text-center text-sm text-slate">{t("No products found.")}</div>}
        </div>
      </section>

      <aside className="flex flex-col border-s border-line bg-white">
        <div className="border-b border-line p-4">
          <select className="input" value={customer} onChange={(e) => setCustomer(+e.target.value)}>
            <option value={0}>👤 {t("Walk-in customer")}</option>
            {customers?.filter((c) => c.id !== setup?.walk_in_customer_id).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
        <div className="flex-1 overflow-y-auto">
          {!cart.length && <div className="p-8 text-center text-sm text-slate">{t("The cart is empty. Scan or tap a product.")}</div>}
          {cart.map((l, i) => (
            <div key={l.key} className="border-b border-line/70 px-4 py-3">
              <div className="flex items-start gap-2">
                <div className="min-w-0 flex-1 font-medium leading-snug">{l.product.name}</div>
                <button className="text-slate hover:text-rust" onClick={() => setCart((c) => c.filter((x) => x.key !== l.key))} aria-label={t("Delete")}>✕</button>
              </div>
              <div className="mt-2 flex items-center gap-2">
                <div className="flex items-center rounded-lg border border-line">
                  <button className="px-3 py-1 text-lg" onClick={() => setLine(l.key, { qty: Math.max(l.qty - 1, 1) })}>−</button>
                  <input className="w-12 border-x border-line py-1 text-center" type="number" value={l.qty} onChange={(e) => setLine(l.key, { qty: Math.max(+e.target.value, 0) })} />
                  <button className="px-3 py-1 text-lg" onClick={() => setLine(l.key, { qty: l.qty + 1 })}>+</button>
                </div>
                {l.product.pack_size > 0 && <button className="rounded-md bg-paper px-2 py-1 text-xs" onClick={() => switchUnit(l)}>{l.unit === "pack" ? (l.product.pack_unit || t("pack")) : t("piece")} ⇄</button>}
                <span className="text-xs text-slate">×</span>
                <input className={`input !w-20 !px-2 !py-1 ${l.price === null ? "text-slate" : ""}`} type="number" step="0.01" value={l.price ?? priced?.[i]?.price ?? localPrice(l)}
                  onChange={(e) => setLine(l.key, { price: e.target.value === "" ? null : +e.target.value })} title={t("Type a price to override the automatic price")} />
                <span className="ms-auto font-semibold">{money(lineTotal(l, i), undefined, 2)}</span>
              </div>
              {priced?.[i]?.promo && <div className="mt-1 text-xs text-moss">🏷 {priced[i].promo}{priced[i].discount ? ` (−${priced[i].discount}%)` : ""}</div>}
              {!!priced?.[i]?.free && <div className="mt-1 text-xs font-medium text-moss">🎁 + {num(priced[i].free)} {t("free")}</div>}
            </div>
          ))}
        </div>
        <div className="space-y-3 border-t border-line p-4">
          <div className="space-y-1 text-sm">
            <div className="flex items-center justify-between"><span className="text-slate">{t("Discount %")}</span><input className="input !w-20 !py-1" type="number" value={discount} onChange={(e) => setDiscount(+e.target.value)} /></div>
            {rate > 0 && <div className="flex justify-between text-slate"><span>{inclusive ? t("Includes VAT") : t("VAT")} ({rate}%)</span><span>{money(tax, undefined, 2)}</span></div>}
            <div className="flex justify-between text-2xl font-bold"><span>{t("Total")}</span><span>{money(total, undefined, 2)}</span></div>
            {fx && <div className="flex justify-between text-lg font-semibold text-signal" dir="ltr"><span>{payCur}</span><span>{totalInPayCur.toFixed(2)}</span></div>}
          </div>
          {needsApproval.length > 0 && <div className="rounded-lg bg-amber-soft p-2 text-xs text-amber">{t("Needs a manager's approval")}: {needsApproval.join(" · ")}</div>}
          <div className="grid grid-cols-4 gap-1 rounded-lg bg-paper p-1 text-sm">
            {(["cash", "card", "bank", "credit"] as const).map((m) => (
              <button key={m} onClick={() => setMethod(m)} className={`rounded-md py-2 ${method === m ? "bg-white font-semibold text-signal shadow-sm" : "text-slate"}`}>{t(m === "credit" ? "On account" : m)}</button>
            ))}
          </div>
          {method !== "credit" && !!setup?.currencies?.length && (
            <div className="flex gap-1 text-xs">
              {["", ...setup.currencies.map((c: any) => c.code)].map((c: string) => (
                <button key={c || "base"} onClick={() => setPayCur(c)} className={`rounded-md border px-2 py-1 ${payCur === c ? "border-signal bg-signal-soft text-signal" : "border-line text-slate"}`}>{c || company?.currency}</button>
              ))}
            </div>
          )}
          {method === "cash" && (
            <div className="flex items-center gap-2">
              <input className="input" type="number" step="0.01" placeholder={`${t("Cash received")}${payCur ? ` (${payCur})` : ""}`} value={received} onChange={(e) => setReceived(e.target.value)} onKeyDown={(e) => e.key === "Enter" && pay()} />
              {+received > 0 && <div className="whitespace-nowrap text-sm">{t("Change")}: <b className="text-lg text-moss">{money(change, undefined, 2)}</b></div>}
            </div>
          )}
          <ErrorNote error={error} />
          <button className="btn-primary w-full !py-4 text-lg" disabled={!cart.length || busy} onClick={pay}>{busy ? "…" : `${t("Pay")} ${fx ? `${totalInPayCur.toFixed(2)} ${payCur}` : money(total, undefined, 2)}`} <span className="text-xs opacity-70">F9</span></button>
        </div>
      </aside>

      <Modal title={done?.offline ? t("Saved offline") : t("Sale completed")} open={!!done} onClose={() => setDone(null)}>
        {done && <>
          <div className="text-center">
            <div className="text-4xl">{done.offline ? "📴" : "✅"}</div>
            <div className="mt-2 text-lg font-semibold">{money(done.total, undefined, 2)}</div>
            {done.change > 0 && <div className="mt-1 text-2xl font-bold text-moss">{t("Change")}: {money(done.change, undefined, 2)}</div>}
            {done.balance > 0 && <div className="mt-1 text-sm text-rust">{t("On the customer's account")}: {money(done.balance, undefined, 2)}</div>}
            {done.offline && <div className="mt-2 text-sm text-amber">{t("No internet. The sale is saved on this device and will be sent automatically.")}</div>}
            <div className="mt-1 text-xs text-slate" dir="ltr">{done.invoice_number}</div>
          </div>
          <div className="mt-5 flex justify-center gap-2">
            <button className="btn-ghost" onClick={printReceipt}>🖨 {t("Print receipt")}</button>
            <button className="btn-primary" onClick={() => setDone(null)}>{t("New sale")}</button>
          </div>
          {/* 80mm receipt, only visible when printing */}
          <div className="receipt hidden print:block" dir={lang === "ar" ? "rtl" : "ltr"}>
            <div style={{ textAlign: "center", fontWeight: 700, fontSize: 16 }}>{company?.name}</div>
            {company?.phone && <div style={{ textAlign: "center" }}>{company.phone}</div>}
            {company?.tax_number && <div style={{ textAlign: "center" }}>{t("Tax number")}: {company.tax_number}</div>}
            <div style={{ textAlign: "center", margin: "6px 0" }}>{done.invoice_number} · {new Date().toLocaleString()}</div>
            {done.customerName && <div>{t("Customer")}: {done.customerName}</div>}
            <hr />
            {done.lines.map((l: any) => (
              <div key={l.key}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                  <span>{l.product.name} × {l.qty}{l.unit === "pack" ? ` ${l.product.pack_unit || ""}` : ""}</span><span>{l.total.toFixed(2)}</span>
                </div>
                {l.free > 0 && <div>+ {l.free} {t("free")}</div>}
              </div>
            ))}
            <hr />
            {done.discount > 0 && <div>{t("Discount")}: {done.discount}%</div>}
            {done.tax_amount > 0 && <div style={{ display: "flex", justifyContent: "space-between" }}><span>{t("VAT")}</span><span>{done.tax_amount.toFixed(2)}</span></div>}
            <div style={{ display: "flex", justifyContent: "space-between", fontWeight: 700, fontSize: 15 }}><span>{t("Total")}</span><span>{done.total.toFixed(2)}</span></div>
            {done.payCur && <div style={{ display: "flex", justifyContent: "space-between" }}><span>{t("Paid in")} {done.payCur}</span><span>{done.totalInPayCur.toFixed(2)}</span></div>}
            {done.method === "cash" && <div style={{ display: "flex", justifyContent: "space-between" }}><span>{t("Cash received")}</span><span>{done.received.toFixed(2)}</span></div>}
            {done.change > 0 && <div style={{ display: "flex", justifyContent: "space-between" }}><span>{t("Change")}</span><span>{done.change.toFixed(2)}</span></div>}
            <hr />
            <div style={{ textAlign: "center" }}>{company?.invoice_footer || t("Thank you for your business.")}</div>
            <div style={{ textAlign: "center", fontSize: 10 }}>{user?.full_name}</div>
          </div>
        </>}
      </Modal>

      <Modal title={t("My day")} open={summaryOpen} onClose={() => setSummaryOpen(false)}>
        {today.data && <div className="space-y-2 text-sm">
          <div className="flex justify-between"><span className="text-slate">{t("Sales")}</span><b>{today.data.sales_count}</b></div>
          <div className="flex justify-between"><span className="text-slate">{t("Total")}</span><b>{money(today.data.total, undefined, 2)}</b></div>
          {Object.entries(today.data.by_method).map(([m, v]) => <div key={m} className="flex justify-between"><span className="text-slate">{t(m)}</span><span>{money(v as number, undefined, 2)}</span></div>)}
          {shift.data && <div className="flex justify-between border-t border-line pt-2"><span className="text-slate">{t("Cash expected in the drawer")}</span><b>{money(shift.data.expected_cash, undefined, 2)}</b></div>}
          <p className="pt-2 text-xs text-slate">{t("Count the cash box and compare it with the cash total.")}</p>
        </div>}
      </Modal>

      <Modal title={shiftModal === "open" ? t("Open shift") : t("Close shift")} open={!!shiftModal} onClose={() => setShiftModal(null)} onSave={shiftAction}
        saveLabel={shiftModal === "open" ? t("Open shift") : t("Close shift")}>
        <div className="grid gap-3">
          {shiftModal === "close" && shift.data && <p className="text-sm">{t("Cash expected in the drawer")}: <b>{money(shift.data.expected_cash, undefined, 2)}</b></p>}
          <Field label={shiftModal === "open" ? t("Cash in the drawer at the start") : t("Cash you counted now")}>
            <input className="input" type="number" step="0.01" autoFocus value={shiftForm.amount} onChange={(e) => setShiftForm({ ...shiftForm, amount: e.target.value })} /></Field>
          {shiftModal === "close" && <Field label={t("Note")}><input className="input" value={shiftForm.note} onChange={(e) => setShiftForm({ ...shiftForm, note: e.target.value })} /></Field>}
        </div>
      </Modal>
      <Modal title={t("Shift closed")} open={!!closed} onClose={() => setClosed(null)}>
        {closed && <div className="space-y-2 text-sm">
          <div className="flex justify-between"><span className="text-slate">{t("Expected")}</span><b>{money(closed.expected_cash, undefined, 2)}</b></div>
          <div className="flex justify-between"><span className="text-slate">{t("Counted")}</span><b>{money(closed.counted_cash, undefined, 2)}</b></div>
          <div className={`flex justify-between rounded-lg p-2 text-base font-bold ${Math.abs(closed.difference) < 1 ? "bg-moss-soft text-moss" : "bg-rust-soft text-rust"}`}>
            <span>{t("Difference")}</span><span>{closed.difference > 0 ? "+" : ""}{money(closed.difference, undefined, 2)}</span></div>
          {Math.abs(closed.difference) >= 1 && <p className="text-xs text-slate">{t("The manager was alerted about the difference.")}</p>}
        </div>}
      </Modal>
      <Modal title={t("Sales waiting to sync")} open={queueOpen} onClose={() => setQueueOpen(false)} onSave={() => sync()} saveLabel={t("Try again now")}>
        <ul className="space-y-2 text-sm">{queue.map((s) => (
          <li key={s.client_ref} className="rounded-lg border border-line p-2">
            <div className="flex justify-between"><span>{new Date(s.at).toLocaleString()}</span><b>{money(s.total, undefined, 2)}</b></div>
            {s.error && <div className="mt-1 flex items-center justify-between gap-2 text-xs text-rust"><span>{s.error}</span>
              <button className="link-danger" onClick={() => { if (confirm(t("Delete this sale from the device?"))) saveQueue(queue.filter((x) => x.client_ref !== s.client_ref)); }}>{t("Delete")}</button></div>}
          </li>))}</ul>
      </Modal>
    </div>
  );
}
