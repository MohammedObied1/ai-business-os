"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, download } from "@/lib/api";
import { useApi, usePaged } from "@/lib/hooks";
import { date, money, num } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { PaymentFields, PaymentValue, emptyPayment, paymentPayload } from "@/components/money";
import { Badge, Drawer, ErrorNote, Field, InfoList, Modal, PageTitle, PagedTable, Status, Table, Tabs, toast } from "@/components/ui";

type Item = { product_id: number; quantity: number; discount_pct: number; unit_price: number | ""; unit: "unit" | "pack" };
const EMPTY_ITEM: Item = { product_id: 0, quantity: 1, discount_pct: 0, unit_price: "", unit: "unit" };
const TABS = ["orders", "invoices", "payments", "returns", "instalments", "recurring"] as const;
const EMPTY_REC = { id: 0, customer_id: 0, description: "", amount: "", interval_months: 1, next_date: new Date().toISOString().slice(0, 10), end_date: "", due_days: 14, send_email: false, is_active: true };

export default function Sales() {
  const { t, lang, tx } = useT();
  const router = useRouter();
  const { can, company } = useSession();
  const [tab, setTab] = useState<(typeof TABS)[number]>("orders");
  const [q, setQ] = useState("");
  const [qq, setQq] = useState("");
  useEffect(() => { const h = setTimeout(() => setQq(q.trim()), 300); return () => clearTimeout(h); }, [q]);
  const qs = qq ? `?q=${encodeURIComponent(qq)}` : "";
  const orders = usePaged<any>(tab === "orders" ? `/api/sales/orders${qs}` : null, [tab, qq]);
  const invoices = usePaged<any>(tab === "invoices" ? `/api/sales/invoices${qs}` : null, [tab, qq]);
  const payments = usePaged<any>(tab === "payments" ? `/api/sales/payments${qs}` : null, [tab, qq]);
  const returns = usePaged<any>(tab === "returns" ? `/api/sales/returns${qs}` : null, [tab, qq]);
  const instalments = useApi<any[]>(tab === "instalments" ? "/api/sales/installments/due?days=30" : null, [tab]);
  const recurring = useApi<any[]>(tab === "recurring" ? "/api/sales/recurring" : null, [tab]);
  const { data: customers } = useApi<any[]>("/api/customers?limit=5000");
  const { data: products } = useApi<any[]>("/api/inventory/products?include_archived=true");
  const { data: warehouses } = useApi<any[]>("/api/inventory/warehouses");
  const { data: currencies } = useApi<any>("/api/currencies");
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [customer, setCustomer] = useState<number | "">("");
  const [warehouse, setWarehouse] = useState<number | "">("");
  const [status, setStatus] = useState("confirmed");
  const [discount, setDiscount] = useState(0);
  const [currency, setCurrency] = useState("");
  const [invoiceNow, setInvoiceNow] = useState(true);
  const [items, setItems] = useState<Item[]>([EMPTY_ITEM]);
  const [quote, setQuote] = useState<any>(null);
  const [payFor, setPayFor] = useState<any>(null);
  const [payAmount, setPayAmount] = useState(0);
  const [pay, setPay] = useState<PaymentValue>(emptyPayment());
  const [orderView, setOrderView] = useState<any>(null);
  const [returnFor, setReturnFor] = useState<any>(null);
  const [returnQty, setReturnQty] = useState<Record<number, number>>({});
  const [returnReason, setReturnReason] = useState("");
  const [returnCond, setReturnCond] = useState<Record<number, string>>({});
  const [exchange, setExchange] = useState(false);
  const [rec, setRec] = useState<any>(null);

  const cname = (r: any) => r.customer_name ?? customers?.find((c) => c.id === r.customer_id)?.name ?? `#${r.customer_id}`;
  const prod = (id: number) => products?.find((x) => x.id === id);
  const lineName = (l: any) => `${prod(l.product_id)?.name ?? `#${l.product_id}`}${l.uom_label ? ` (${num(l.uom_qty)} ${l.uom_label})` : ""}`;
  const setItem = (i: number, patch: Partial<Item>) => setItems(items.map((x, j) => (j === i ? { ...x, ...patch } : x)));
  const cur = currency || undefined;

  // live pricing from the server (customer's price list, offers, VAT, currency)
  const quoteKey = JSON.stringify([items, customer, discount, currency, open]);
  useEffect(() => {
    const valid = items.filter((i) => i.product_id && i.quantity > 0);
    if (!open || !valid.length) { setQuote(null); return; }
    const h = setTimeout(() => {
      api("/api/sales/quote", { method: "POST", json: { customer_id: customer || null, discount_pct: discount, currency: currency || null,
        items: valid.map((i) => ({ ...i, unit_price: i.unit_price === "" ? null : +i.unit_price })) } }).then(setQuote).catch(() => setQuote(null));
    }, 250);
    return () => clearTimeout(h);
  }, [quoteKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const openNew = (customerId?: number) => {
    setError(null); setCustomer(customerId ?? ""); setDiscount(0); setStatus("confirmed"); setInvoiceNow(true); setItems([EMPTY_ITEM]); setCurrency("");
    setWarehouse(warehouses?.[0]?.id ?? ""); setOpen(true);
  };
  const save = async () => {
    setError(null);
    try {
      const o = await api("/api/sales/orders", { method: "POST", json: {
        customer_id: customer, warehouse_id: warehouse || null, status, discount_pct: discount, currency: currency || null,
        items: items.filter((i) => i.product_id).map((i) => ({ ...i, unit_price: i.unit_price === "" ? null : +i.unit_price })),
      } });
      setOpen(false); orders.reload();
      if (o.status === "pending_approval") { toast(t("Saved. Waiting for a manager's approval.")); return; }
      if (invoiceNow && status !== "quotation") {
        const inv = await api("/api/sales/invoices", { method: "POST", json: { customer_id: o.customer_id, order_id: o.id } });
        toast("Order and invoice created"); router.push(`/sales/invoices/${inv.id}`);
      } else toast("Order saved");
    } catch (e: any) { setError(e.message); }
  };
  const makeInvoice = async (o: any) => {
    try { const inv = await api("/api/sales/invoices", { method: "POST", json: { customer_id: o.customer_id, order_id: o.id } }); toast("Invoice created"); router.push(`/sales/invoices/${inv.id}`); }
    catch (e: any) { toast(e.message, "bad"); }
  };
  const setOrderStatus = async (o: any, s: string) => {
    try { await api(`/api/sales/orders/${o.id}/status?status=${s}`, { method: "POST" }); toast("Saved"); orders.reload(); setOrderView(null); } catch (e: any) { toast(e.message, "bad"); }
  };
  const approve = async (o: any) => {
    try { await api(`/api/sales/orders/${o.id}/approve`, { method: "POST" }); toast("Approved"); orders.reload(); setOrderView(null); } catch (e: any) { toast(e.message, "bad"); }
  };
  const recordPayment = async () => {
    setError(null);
    try {
      const p = await api("/api/sales/payments", { method: "POST", json: { invoice_id: payFor.id, amount: payAmount, ...paymentPayload(pay) } });
      toast("Payment recorded"); setPayFor(null); invoices.reload();
      router.push(`/vouchers/${p.number}`);
    } catch (e: any) { setError(e.message); }
  };
  const openReturn = (o: any, asExchange = false) => { setError(null); setReturnReason(""); setReturnQty({}); setReturnCond({}); setExchange(asExchange); setReturnFor(o); };
  // deep links: /sales?return=<order id> (from the invoice page), ?order=<id> (approvals), ?new=1&customer=<id> (field sales)
  useEffect(() => {
    const sp = new URLSearchParams(window.location.search);
    const ret = sp.get("return"), ord = sp.get("order");
    if (ret || ord) api(`/api/sales/orders/${ret || ord}`).then((o) => (ret ? openReturn(o) : setOrderView(o))).catch(() => {});
    if (sp.get("new") && warehouses) openNew(sp.get("customer") ? +sp.get("customer")! : undefined);
    if (ret || ord || sp.get("new")) window.history.replaceState(null, "", "/sales");
  }, [warehouses]); // eslint-disable-line react-hooks/exhaustive-deps
  const saveReturn = async () => {
    setError(null);
    try {
      const r = await api("/api/sales/returns", { method: "POST", json: { order_id: returnFor.id, reason: returnReason || null,
        items: Object.entries(returnQty).filter(([, v]) => v > 0).map(([k, v]) => ({ order_item_id: +k, quantity: v, condition: returnCond[+k] ?? "good" })) } });
      toast(r?.pending_approval ? "Sent to a manager for approval" : "Return saved"); returns.reload(); orders.reload();
      const customerId = returnFor.customer_id;
      setReturnFor(null); setOrderView(null);
      if (exchange && !r?.pending_approval) openNew(customerId);  // exchange = return + a new sale for the same customer
    } catch (e: any) { setError(e.message); }
  };
  const saveRec = async () => {
    setError(null);
    const { id, ...body } = rec;
    try {
      await api(id ? `/api/sales/recurring/${id}` : "/api/sales/recurring", { method: id ? "PATCH" : "POST", json: { ...body, amount: +body.amount, end_date: body.end_date || null } });
      setRec(null); toast("Saved"); recurring.reload();
    } catch (e: any) { setError(e.message); }
  };
  const runRec = async () => {
    try { const r = await api("/api/sales/recurring/run", { method: "POST" }); toast(t("{n} invoices created", { n: r.created })); recurring.reload(); } catch (e: any) { toast(e.message, "bad"); }
  };
  const balance = (r: any) => r.total - r.paid_amount - (r.credited_amount || 0);

  return (
    <>
      <PageTitle title={t("Sales & invoices")} help={t("Sales help")} actions={<>
        <button className="btn-ghost" onClick={() => download(`/api/data/export/${tab === "invoices" ? "invoices" : "sales"}?lang=${lang}`).catch((e) => toast(e.message, "bad"))}>⬇ {t("Excel")}</button>
        {can("pos:use") && <Link className="btn-ghost" href="/pos">{t("Point of sale")}</Link>}
        {can("sales:write") && <button className="btn-primary" onClick={() => openNew()}>+ {t("New sale")}</button>}</>} />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs tabs={TABS} value={tab} onChange={setTab} />
        {["orders", "invoices", "payments", "returns"].includes(tab) && <input className="input mb-4 max-w-xs" placeholder={`🔍 ${t("Search by number or customer")}`} value={q} onChange={(e) => setQ(e.target.value)} />}
        {tab === "recurring" && can("invoices:create") && <div className="mb-4 flex gap-2">
          <button className="btn-ghost" onClick={runRec}>{t("Create due invoices now")}</button>
          <button className="btn-primary" onClick={() => { setError(null); setRec({ ...EMPTY_REC }); }}>+ {t("New recurring invoice")}</button></div>}
      </div>
      <div className="panel">
        {tab === "orders" && <PagedTable paged={orders} onRow={setOrderView} empty={t("No sales yet.")} cols={[
          { h: t("Number"), c: (r: any) => <span className="font-medium" dir="ltr">{r.number}</span> }, { h: t("Date"), c: (r: any) => date(r.order_date) }, { h: t("Customer"), c: cname },
          { h: t("Total"), c: (r: any) => money(r.total, r.currency ?? undefined, 2), end: true },
          { h: t("Status"), c: (r: any) => <div className="flex gap-1"><Status value={r.status} />{r.source === "pos" && <span className="rounded bg-paper px-1.5 text-xs text-slate">POS</span>}{r.source === "online" && <span className="rounded bg-signal-soft px-1.5 text-xs text-signal">{t("Online")}</span>}</div> },
          { h: t("Invoice"), c: (r: any) => r.invoice_id ? <span className="text-xs text-moss">✓ {t("Invoiced")}</span> : ["confirmed", "delivered"].includes(r.status) && can("invoices:create")
              ? <button className="link" onClick={(e) => { e.stopPropagation(); makeInvoice(r); }}>{t("Make invoice")}</button> : null },
        ]} />}
        {tab === "invoices" && <PagedTable paged={invoices} onRow={(r: any) => router.push(`/sales/invoices/${r.id}`)} empty={t("No invoices yet.")} cols={[
          { h: t("Number"), c: (r: any) => <span className="font-medium" dir="ltr">{r.number}</span> }, { h: t("Customer"), c: cname }, { h: t("Due"), c: (r: any) => date(r.due_date) },
          { h: t("Total"), c: (r: any) => money(r.total, r.currency ?? undefined, 2), end: true }, { h: t("Balance"), c: (r: any) => money(balance(r), r.currency ?? undefined, 2), end: true },
          { h: t("Status"), c: (r: any) => <Status value={r.status} /> },
          { h: "", c: (r: any) => !["paid", "cancelled"].includes(r.status) && can("payments:write") && <div className="flex justify-end"><button className="link whitespace-nowrap" onClick={(e) => { e.stopPropagation(); setError(null); setPayFor(r); setPay(emptyPayment()); setPayAmount(+balance(r).toFixed(2)); }}>{t("Record payment")}</button></div> },
        ]} />}
        {tab === "payments" && <PagedTable paged={payments} empty={t("No payments yet.")} onRow={(r: any) => r.number && router.push(`/vouchers/${r.number}`)} cols={[
          { h: t("Voucher"), c: (r: any) => <span dir="ltr">{r.number ?? "—"}</span> }, { h: t("Date"), c: (r: any) => date(r.paid_at) }, { h: t("Customer"), c: cname },
          { h: t("Method"), c: (r: any) => t(r.method) }, { h: t("Reference"), c: (r: any) => r.reference ?? "—" },
          { h: t("Amount"), c: (r: any) => <span className={r.status === "bounced" ? "text-rust line-through" : ""}>{money(r.amount, undefined, 2)}</span>, end: true },
        ]} />}
        {tab === "returns" && <PagedTable paged={returns} empty={t("No returns yet.")} onRow={(r: any) => r.invoice_id && router.push(`/sales/invoices/${r.invoice_id}`)} cols={[
          { h: t("Number"), c: (r: any) => <span className="font-medium" dir="ltr">{r.number}</span> }, { h: t("Date"), c: (r: any) => date(r.note_date) }, { h: t("Customer"), c: cname },
          { h: t("Reason"), c: (r: any) => r.reason ?? "—" }, { h: t("Total"), c: (r: any) => money(r.total, undefined, 2), end: true },
          { h: t("Refunded"), c: (r: any) => r.refunded ? money(r.refunded, undefined, 2) : "—", end: true },
        ]} />}
        {tab === "instalments" && <Table rows={instalments.data} empty={t("No instalments due in the next 30 days.")} onRow={(r: any) => router.push(`/sales/invoices/${r.invoice_id}`)} cols={[
          { h: t("Due"), c: (r: any) => <span className={r.due_date < new Date().toISOString().slice(0, 10) ? "font-semibold text-rust" : ""}>{date(r.due_date)}</span> },
          { h: t("Customer"), c: (r: any) => r.customer }, { h: t("Invoice"), c: (r: any) => <span dir="ltr">{r.invoice}</span> },
          { h: t("Instalment"), c: (r: any) => `#${r.seq}` }, { h: t("Remaining"), c: (r: any) => money(r.remaining, undefined, 2), end: true },
          { h: t("Status"), c: (r: any) => <Status value={r.status} /> },
        ]} />}
        {tab === "recurring" && <Table rows={recurring.data} empty={t("No recurring invoices. Use them for monthly rent, subscriptions or maintenance contracts.")}
          onRow={can("invoices:create") ? (r: any) => { setError(null); setRec({ ...r, amount: String(r.amount), end_date: r.end_date ?? "" }); } : undefined} cols={[
          { h: t("Customer"), c: (r: any) => r.customer }, { h: t("Description"), c: (r: any) => r.description },
          { h: t("Every"), c: (r: any) => t("{n} month(s)", { n: r.interval_months }) }, { h: t("Next invoice"), c: (r: any) => date(r.next_date) },
          { h: t("Amount"), c: (r: any) => money(r.amount, undefined, 2), end: true },
          { h: t("Status"), c: (r: any) => <Badge tone={r.is_active ? "good" : "neutral"}>{r.is_active ? t("Active") : t("Stopped")}</Badge> },
        ]} />}
      </div>

      <Drawer title={orderView ? `${t("Order")} ${orderView.number}` : ""} open={!!orderView} onClose={() => setOrderView(null)}>
        {orderView && <>
          <InfoList items={[[t("Customer"), cname(orderView)], [t("Date"), date(orderView.order_date)], [t("Status"), <Status value={orderView.status} />],
            [t("Order discount %"), `${orderView.discount_pct}%`], ...(orderView.currency ? [[t("Currency"), `${orderView.currency} (${orderView.exchange_rate})`] as [string, string]] : [])]} />
          {orderView.status === "pending_approval" && <div className="mt-4 rounded-lg bg-amber-soft p-3 text-sm text-amber">
            <b>{t("Needs a manager's approval")}:</b> {(orderView.approval_reason ?? "").split("\n").map((r: string) => tx(r)).join(" · ")}
            {can("approvals:approve") && <div className="mt-2"><button className="btn-primary !py-1.5" onClick={() => approve(orderView)}>{t("Approve")}</button></div>}
          </div>}
          <h3 className="mb-2 mt-6 font-semibold">{t("Items")}</h3>
          <div className="rounded-lg border border-line"><Table rows={orderView.items} cols={[
            { h: t("Product"), c: (r: any) => lineName(r) }, { h: t("Qty"), c: (r: any) => num(r.quantity), end: true },
            { h: t("Price"), c: (r: any) => money(r.unit_price, orderView.currency ?? undefined, 2), end: true }, { h: t("Discount"), c: (r: any) => `${r.discount_pct}%`, end: true }, { h: t("Total"), c: (r: any) => money(r.line_total, orderView.currency ?? undefined, 2), end: true },
          ]} /></div>
          <div className="mt-4 space-y-1 text-sm">
            <div className="flex justify-between"><span className="text-slate">{t("Subtotal")}</span><span>{money(orderView.subtotal, orderView.currency ?? undefined, 2)}</span></div>
            {orderView.tax_amount > 0 && <div className="flex justify-between"><span className="text-slate">{t("VAT")} ({orderView.tax_rate}%)</span><span>{money(orderView.tax_amount, orderView.currency ?? undefined, 2)}</span></div>}
            <div className="flex justify-between text-lg font-semibold"><span>{t("Total")}</span><span>{money(orderView.total, orderView.currency ?? undefined, 2)}</span></div>
          </div>
          {can("sales:write") && <div className="mt-6 flex flex-wrap gap-2">
            {orderView.status === "quotation" && <button className="btn-primary" onClick={() => setOrderStatus(orderView, "confirmed")}>{t("Confirm")}</button>}
            {orderView.status === "confirmed" && <button className="btn-ghost" onClick={() => setOrderStatus(orderView, "delivered")}>{t("Mark delivered")}</button>}
            {!orderView.invoice_id && ["confirmed", "delivered"].includes(orderView.status) && <button className="btn-primary" onClick={() => makeInvoice(orderView)}>{t("Make invoice")}</button>}
            {orderView.invoice_id && <Link className="btn-ghost" href={`/sales/invoices/${orderView.invoice_id}`}>{t("Open invoice")}</Link>}
            {can("returns:create") && orderView.invoice_id && <button className="btn-ghost" onClick={() => openReturn(orderView)}>↩ {t("Return items")}</button>}
            {can("returns:create") && can("sales:write") && orderView.invoice_id && <button className="btn-ghost" onClick={() => openReturn(orderView, true)}>⇄ {t("Exchange")}</button>}
            {orderView.status !== "cancelled" && !orderView.invoice_id && <button className="btn-ghost !text-rust" onClick={() => confirm(t("Cancel this order? Stock will be returned.")) && setOrderStatus(orderView, "cancelled")}>{t("Cancel order")}</button>}
          </div>}
        </>}
      </Drawer>

      <Modal title={t("New sale")} open={open} onClose={() => setOpen(false)} onSave={save} saveLabel={t("Save")}>
        <ErrorNote error={error} />
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2"><Field label={`${t("Customer")} *`}><select className="input" value={customer} onChange={(e) => setCustomer(+e.target.value)}><option value="">{t("Select…")}</option>{customers?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field></div>
          <Field label={t("Type")}><select className="input" value={status} onChange={(e) => setStatus(e.target.value)}><option value="quotation">{t("Quotation")}</option><option value="confirmed">{t("Confirmed order")}</option><option value="delivered">{t("Delivered")}</option></select></Field>
          <Field label={t("Take stock from")}><select className="input" value={warehouse} onChange={(e) => setWarehouse(+e.target.value)}><option value="">{t("None")}</option>{warehouses?.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</select></Field>
          {!!currencies?.items?.length && <Field label={t("Currency")}><select className="input" value={currency} onChange={(e) => { setCurrency(e.target.value); setItems(items.map((i) => ({ ...i, unit_price: "" }))); }}>
            <option value="">{currencies.base}</option>{currencies.items.map((c: any) => <option key={c.code} value={c.code}>{c.code} ({c.rate})</option>)}</select></Field>}
        </div>
        <div className="mt-4 space-y-2">
          <div className="flex gap-2 text-xs text-slate"><span className="flex-1">{t("Product")}</span><span className="w-16">{t("Qty")}</span><span className="w-20">{t("Price")}</span><span className="w-14">{t("Disc. %")}</span><span className="w-6" /></div>
          {items.map((it, i) => {
            const p = prod(it.product_id);
            const ql = quote?.lines?.filter((l: any) => !l.free)?.[items.slice(0, i).filter((x) => x.product_id && x.quantity > 0).length];
            return (
              <div key={i}>
                <div className="flex items-center gap-2">
                  <select className="input" value={it.product_id} onChange={(e) => setItem(i, { product_id: +e.target.value, unit_price: "", unit: "unit" })}><option value={0}>{t("Product…")}</option>{products?.filter((x) => x.is_active).map((x) => <option key={x.id} value={x.id}>{x.name} ({num(x.total_stock)})</option>)}</select>
                  <input className="input w-16 !px-2" type="number" min={1} value={it.quantity} onChange={(e) => setItem(i, { quantity: +e.target.value })} />
                  <input className="input w-20 !px-2" type="number" step="0.01" placeholder={it.product_id && ql ? String(ql.price) : ""} value={it.unit_price} onChange={(e) => setItem(i, { unit_price: e.target.value === "" ? "" : +e.target.value })} />
                  <input className="input w-14 !px-2" type="number" value={it.discount_pct} onChange={(e) => setItem(i, { discount_pct: +e.target.value })} />
                  <button className="w-6 text-slate hover:text-rust" onClick={() => setItems(items.length > 1 ? items.filter((_, j) => j !== i) : [EMPTY_ITEM])} aria-label={t("Delete")}>✕</button>
                </div>
                {p?.pack_size > 0 && <div className="mt-1 flex gap-1 text-xs">
                  {(["unit", "pack"] as const).map((u) => <button key={u} onClick={() => setItem(i, { unit: u, unit_price: "" })} className={`rounded px-2 py-0.5 ${it.unit === u ? "bg-signal text-white" : "bg-paper text-slate"}`}>{u === "unit" ? t("piece") : `${p.pack_unit || t("pack")} (${num(p.pack_size)})`}</button>)}
                </div>}
                {ql?.promo && <div className="mt-1 text-xs text-moss">🏷 {ql.promo}</div>}
              </div>
            );
          })}
          <button className="link -ms-2" onClick={() => setItems([...items, EMPTY_ITEM])}>{t("+ Add product")}</button>
          {quote?.lines?.filter((l: any) => l.free).map((l: any, i: number) => <div key={i} className="text-xs font-medium text-moss">🎁 {num(l.quantity)} × {l.name} {t("free")}</div>)}
        </div>
        <div className="mt-3 grid grid-cols-2 gap-3">
          <Field label={t("Order discount %")}><input className="input" type="number" value={discount} onChange={(e) => setDiscount(+e.target.value)} /></Field>
          {status !== "quotation" && <label className="flex items-end gap-2 pb-2 text-sm"><input type="checkbox" className="h-4 w-4 accent-signal" checked={invoiceNow} onChange={(e) => setInvoiceNow(e.target.checked)} />{t("Create the invoice right away")}</label>}
        </div>
        <div className="num mt-4 space-y-1 rounded-lg bg-paper px-3 py-2">
          {quote && quote.tax > 0 && <div className="flex justify-between text-sm text-slate"><span>{company?.prices_include_tax ? t("Includes VAT") : t("VAT")} ({company?.tax_rate}%)</span><span>{money(quote.tax, cur, 2)}</span></div>}
          <div className="flex items-center justify-between"><span className="text-slate">{t("Total")}</span><span className="text-lg font-semibold">{money(quote?.total ?? 0, cur, 2)}</span></div>
          {!!quote?.needs_approval?.length && <div className="text-xs text-amber">{t("Needs a manager's approval")}: {quote.needs_approval.map((r: string) => tx(r)).join(" · ")}</div>}
        </div>
      </Modal>

      <Modal title={`${t("Record payment")} · ${payFor?.number ?? ""}`} open={!!payFor} onClose={() => setPayFor(null)} onSave={recordPayment} saveLabel={t("Record payment")}>
        <ErrorNote error={error} />
        <div className="mb-3"><Field label={`${t("Amount")}${payFor?.currency ? ` (${payFor.currency})` : ""}`}><input className="input" type="number" step="0.01" value={payAmount} onChange={(e) => setPayAmount(+e.target.value)} /></Field></div>
        <PaymentFields value={pay} onChange={setPay} />
      </Modal>

      <Modal title={returnFor ? `${exchange ? t("Exchange") : t("Return items")} · ${returnFor.number}` : ""} open={!!returnFor} onClose={() => setReturnFor(null)} onSave={saveReturn} saveLabel={t("Save return")}>
        <ErrorNote error={error} />
        <p className="mb-3 text-sm text-slate">{t("Return help")}</p>
        <div className="space-y-2">
          {returnFor?.items.map((l: any) => (
            <div key={l.id} className="flex items-center gap-3">
              <span className="flex-1 text-sm">{lineName(l)} <span className="text-slate">({t("sold")} {num(l.quantity)})</span></span>
              <input className="input !w-24" type="number" min={0} max={l.quantity} value={returnQty[l.id] ?? 0} onChange={(e) => setReturnQty({ ...returnQty, [l.id]: +e.target.value })} />
              <select className="input !w-28 !px-2" value={returnCond[l.id] ?? "good"} onChange={(e) => setReturnCond({ ...returnCond, [l.id]: e.target.value })}>
                <option value="good">{t("Good")}</option><option value="damaged">{t("state.damaged")}</option><option value="expired">{t("state.expired")}</option></select>
            </div>
          ))}
        </div>
        <div className="mt-3"><Field label={t("Reason")}><input className="input" value={returnReason} onChange={(e) => setReturnReason(e.target.value)} /></Field></div>
      </Modal>

      <Modal title={rec?.id ? t("Recurring invoice") : t("New recurring invoice")} open={!!rec} onClose={() => setRec(null)} onSave={saveRec}>
        {rec && <>
          <ErrorNote error={error} />
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2"><Field label={t("Customer")}><select className="input" value={rec.customer_id} onChange={(e) => setRec({ ...rec, customer_id: +e.target.value })}>
              <option value={0}>{t("Select…")}</option>{customers?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field></div>
            <div className="col-span-2"><Field label={t("Description")}><input className="input" placeholder={t("e.g. Monthly maintenance")} value={rec.description} onChange={(e) => setRec({ ...rec, description: e.target.value })} /></Field></div>
            <Field label={t("Amount")}><input className="input" type="number" value={rec.amount} onChange={(e) => setRec({ ...rec, amount: e.target.value })} /></Field>
            <Field label={t("Every (months)")}><input className="input" type="number" min={1} value={rec.interval_months} onChange={(e) => setRec({ ...rec, interval_months: +e.target.value })} /></Field>
            <Field label={t("Next invoice")}><input className="input" type="date" value={rec.next_date} onChange={(e) => setRec({ ...rec, next_date: e.target.value })} /></Field>
            <Field label={t("Stop after (optional)")}><input className="input" type="date" value={rec.end_date} onChange={(e) => setRec({ ...rec, end_date: e.target.value })} /></Field>
            <Field label={t("Payment due after (days)")}><input className="input" type="number" value={rec.due_days} onChange={(e) => setRec({ ...rec, due_days: +e.target.value })} /></Field>
          </div>
          <div className="mt-3 space-y-2 text-sm">
            <label className="flex items-center gap-2"><input type="checkbox" className="accent-signal" checked={rec.send_email} onChange={(e) => setRec({ ...rec, send_email: e.target.checked })} />{t("Email the invoice to the customer")}</label>
            <label className="flex items-center gap-2"><input type="checkbox" className="accent-signal" checked={rec.is_active} onChange={(e) => setRec({ ...rec, is_active: e.target.checked })} />{t("Active")}</label>
          </div>
        </>}
      </Modal>
    </>
  );
}
