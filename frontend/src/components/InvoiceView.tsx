"use client";
import { logoUrl } from "@/lib/api";
import { date, money, num } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { Status } from "./ui";

/** The printable invoice itself. Used inside the app and on the public shared-invoice page. */
export default function InvoiceView({ d }: { d: any }) {
  const { t } = useT();
  const inv = d.invoice;
  const cur = d.currency || d.invoice.currency || d.company.currency;
  const m = (n: number) => money(n, cur, 2);
  const credited = inv.credited_amount || 0;
  const balance = inv.total - inv.paid_amount - credited;
  const orderDiscount = d.items.length ? d.subtotal * (d.order_discount_pct / 100) : 0;
  const inclusiveTax = d.items.length && Math.abs(d.subtotal - orderDiscount - inv.total) < 0.02 && inv.tax_amount > 0;

  return (
    <article className="panel relative mx-auto max-w-3xl overflow-hidden p-8 print:max-w-none print:border-0 print:p-0">
      {inv.status === "cancelled" && <div className="pointer-events-none absolute inset-0 flex items-center justify-center"><span className="-rotate-12 rounded-xl border-4 border-rust/40 px-6 py-2 text-5xl font-bold text-rust/40">{t("cancelled")}</span></div>}
      <header className="flex flex-wrap items-start justify-between gap-6 border-b border-line pb-6">
        <div className="flex items-start gap-4">
          {d.company.logo_path && <img src={logoUrl(d.company.id, d.company.logo_path)} alt="" className="h-16 w-16 object-contain" />}
          <div>
            <div className="text-2xl font-bold">{d.company.name}</div>
            <div className="mt-1 space-y-0.5 text-sm text-slate">
              {d.company.address && <div>{d.company.address}</div>}
              {d.company.phone && <div><span dir="ltr">{d.company.phone}</span></div>}
              {d.company.email && <div><span dir="ltr">{d.company.email}</span></div>}
              {d.company.tax_number && <div>{t("Tax number")}: <span dir="ltr">{d.company.tax_number}</span></div>}
            </div>
          </div>
        </div>
        <div className="text-end">
          <div className="text-3xl font-light tracking-wide text-signal">{inv.tax_amount > 0 ? t("TAX INVOICE") : t("INVOICE")}</div>
          <div className="mt-1 font-semibold" dir="ltr">{inv.number}</div>
          <div className="mt-2"><Status value={inv.status} /></div>
        </div>
      </header>

      <section className="grid gap-6 py-6 sm:grid-cols-2">
        <div>
          <div className="text-xs font-medium text-slate">{t("Bill to")}</div>
          <div className="mt-1 text-lg font-semibold">{d.customer.name}</div>
          <div className="text-sm text-slate">
            {d.customer.address && <div>{d.customer.address}</div>}
            {d.customer.phone && <div><span dir="ltr">{d.customer.phone}</span></div>}
          </div>
        </div>
        <dl className="grid grid-cols-2 gap-y-1 text-sm sm:text-end">
          <dt className="text-slate">{t("Invoice date")}</dt><dd>{date(inv.issue_date)}</dd>
          <dt className="text-slate">{t("Due")}</dt><dd>{date(inv.due_date)}</dd>
          {d.order_number && <><dt className="text-slate">{t("Order")}</dt><dd><span dir="ltr">{d.order_number}</span></dd></>}
        </dl>
      </section>

      {d.items.length > 0 ? (
        <table className="w-full text-sm">
          <thead><tr className="border-y border-line bg-paper/60 text-xs text-slate">
            <th className="px-2 py-2 text-start font-medium">#</th><th className="px-2 py-2 text-start font-medium">{t("Product")}</th>
            <th className="px-2 py-2 text-end font-medium">{t("Qty")}</th><th className="px-2 py-2 text-end font-medium">{t("Price")}</th>
            <th className="px-2 py-2 text-end font-medium">{t("Discount")}</th><th className="px-2 py-2 text-end font-medium">{t("Total")}</th>
          </tr></thead>
          <tbody>{d.items.map((it: any, i: number) => (
            <tr key={i} className="border-b border-line/60">
              <td className="px-2 py-2 text-slate">{i + 1}</td>
              <td className="px-2 py-2"><div className="font-medium">{it.product}</div>{it.sku && <div className="text-xs text-slate" dir="ltr">{it.sku}</div>}</td>
              <td className="num px-2 py-2 text-end">{num(it.quantity, 2)} {it.unit && it.unit !== "unit" ? <span className="text-xs text-slate">{it.unit}</span> : null}</td>
              <td className="num px-2 py-2 text-end">{m(it.unit_price)}</td>
              <td className="num px-2 py-2 text-end">{it.discount_pct ? `${it.discount_pct}%` : "—"}</td><td className="num px-2 py-2 text-end font-medium">{m(it.line_total)}</td>
            </tr>))}</tbody>
        </table>
      ) : <div className="rounded-lg bg-paper p-4 text-sm text-slate">{inv.number.startsWith("OB") ? t("Opening balance carried over from before using the system.") : t("Invoice without item details.")}</div>}

      <section className="mt-6 flex justify-end">
        <dl className="w-full max-w-xs space-y-1.5 text-sm">
          {d.items.length > 0 && <div className="flex justify-between"><dt className="text-slate">{t("Subtotal")}</dt><dd className="num">{m(d.subtotal)}</dd></div>}
          {orderDiscount > 0.009 && <div className="flex justify-between"><dt className="text-slate">{t("Discount")} ({d.order_discount_pct}%)</dt><dd className="num">−{m(orderDiscount)}</dd></div>}
          {inv.tax_amount > 0 && !inclusiveTax && <>
            <div className="flex justify-between"><dt className="text-slate">{t("Total before VAT")}</dt><dd className="num">{m(inv.total - inv.tax_amount)}</dd></div>
            <div className="flex justify-between"><dt className="text-slate">{t("VAT")} ({d.tax_rate}%)</dt><dd className="num">{m(inv.tax_amount)}</dd></div>
          </>}
          <div className="flex justify-between border-t border-line pt-2 text-lg font-bold"><dt>{t("Total")}</dt><dd className="num">{m(inv.total)}</dd></div>
          {inclusiveTax && <div className="flex justify-between text-xs text-slate"><dt>{t("Includes VAT")} ({d.tax_rate}%)</dt><dd className="num">{m(inv.tax_amount)}</dd></div>}
          <div className="flex justify-between"><dt className="text-slate">{t("Paid")}</dt><dd className="num text-moss">{m(inv.paid_amount)}</dd></div>
          {credited > 0 && <div className="flex justify-between"><dt className="text-slate">{t("Returns")}</dt><dd className="num text-moss">{m(credited)}</dd></div>}
          <div className={`flex justify-between rounded-lg px-2 py-1.5 font-semibold ${balance > 0.009 && inv.status !== "cancelled" ? "bg-rust-soft text-rust" : "bg-moss-soft text-moss"}`}><dt>{t("Balance due")}</dt><dd className="num">{m(Math.max(balance, 0))}</dd></div>
        </dl>
      </section>

      {d.payments.length > 0 && (
        <section className="mt-8">
          <h3 className="mb-2 text-sm font-semibold">{t("Payments")}</h3>
          <table className="w-full text-sm"><tbody>{d.payments.map((p: any) => (
            <tr key={p.id} className={`border-b border-line/60 ${p.status === "bounced" ? "text-rust line-through" : ""}`}>
              <td className="py-1.5"><span dir="ltr">{p.number}</span></td><td className="py-1.5">{date(p.paid_at)}</td><td className="py-1.5">{t(p.method)}</td>
              <td className="py-1.5 text-slate">{p.reference ?? ""}</td><td className="num py-1.5 text-end">{m(p.amount)}</td>
            </tr>
          ))}</tbody></table>
        </section>
      )}
      {d.credit_notes?.length > 0 && (
        <section className="mt-6">
          <h3 className="mb-2 text-sm font-semibold">{t("Returns")}</h3>
          <table className="w-full text-sm"><tbody>{d.credit_notes.map((n: any) => (
            <tr key={n.id} className="border-b border-line/60"><td className="py-1.5"><span dir="ltr">{n.number}</span></td><td className="py-1.5">{date(n.note_date)}</td>
              <td className="py-1.5 text-slate">{n.reason ?? ""}</td><td className="num py-1.5 text-end">{m(n.total)}</td></tr>
          ))}</tbody></table>
        </section>
      )}
      {d.installments?.length > 0 && (
        <section className="mt-6">
          <h3 className="mb-2 text-sm font-semibold">{t("Instalment plan")}</h3>
          <table className="w-full text-sm"><tbody>{d.installments.map((s: any) => (
            <tr key={s.seq} className="border-b border-line/60"><td className="py-1.5">#{s.seq}</td><td className="py-1.5">{date(s.due_date)}</td>
              <td className="py-1.5"><Status value={s.status} /></td><td className="num py-1.5 text-end">{m(s.amount)}</td></tr>
          ))}</tbody></table>
        </section>
      )}
      <footer className="mt-10 border-t border-line pt-4 text-center text-xs text-slate">{d.company.invoice_footer || t("Thank you for your business.")}</footer>
    </article>
  );
}
