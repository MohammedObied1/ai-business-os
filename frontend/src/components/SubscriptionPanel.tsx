"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { date } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { Badge, ErrorNote, Field, Modal, Table, toast } from "./ui";

const usd = (n: number) => `$${(n ?? 0).toLocaleString("en", { maximumFractionDigits: 2 })}`;
export const SUB_TONE: Record<string, any> = { active: "good", trialing: "info", past_due: "warn", grace: "warn", suspended: "bad", cancelled: "neutral" };

/** Usage vs limits bars (company view and platform view). */
export function LimitBars({ limits }: { limits: { key: string; limit: number; used: number }[] }) {
  const { t } = useT();
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {limits.map((l) => {
        const pct = l.limit ? Math.min(100, (l.used / l.limit) * 100) : 0;
        return <div key={l.key} className="text-sm">
          <div className="flex justify-between"><span>{t(`limit.${l.key}`)}</span><span className="text-slate">{l.used.toLocaleString()} / {l.limit ? l.limit.toLocaleString() : "∞"}</span></div>
          <div className="mt-1 h-2 rounded-full bg-paper"><div className={`h-2 rounded-full ${pct >= 90 ? "bg-rust" : pct >= 70 ? "bg-amber" : "bg-signal"}`} style={{ width: `${l.limit ? pct : 4}%` }} /></div>
        </div>;
      })}
    </div>
  );
}

/** Platform admin: one company's subscription — plan, interval, trial, coupon, add-ons, bills and payments. */
export function SubscriptionPanel({ cid }: { cid: number }) {
  const { t } = useT();
  const sub = useApi<any>(`/api/platform/companies/${cid}/subscription`, [cid], { platform: true });
  const cat = useApi<any>("/api/platform/billing/catalog", [], { platform: true });
  const [f, setF] = useState<any>(null);
  const [pay, setPay] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { if (sub.data) setF({ plan_id: sub.data.plan_id ?? 0, interval: sub.data.interval, coupon: "", grace_days: sub.data.grace_days ?? "", items: sub.data.items, notes: sub.data.notes ?? "" }); }, [sub.data]);
  const d = sub.data;

  const update = async (body: any, msg = "Saved") => {
    setError(null);
    try { const r = await api(`/api/platform/companies/${cid}/subscription`, { method: "PUT", json: body, platform: true });
      toast(r.change?.applied === "at_period_end" ? t("Downgrade scheduled for the end of the period") : r.change?.invoice ? `${t(msg)} · ${r.change.invoice}` : msg); sub.reload(); }
    catch (e: any) { setError(e.message); toast(e.message, "bad"); }
  };
  const recordPayment = async () => {
    setError(null);
    try { await api(`/api/platform/billing/${pay.id}/payments`, { method: "POST", json: { amount: +pay.amount, method: pay.method, reference: pay.reference || null }, platform: true });
      setPay(null); toast("Payment recorded"); sub.reload(); }
    catch (e: any) { setError(e.message); }
  };
  const invoiceNow = async () => { try { const r = await api(`/api/platform/companies/${cid}/subscription/invoice`, { method: "POST", platform: true }); toast(`${r.number} · ${usd(r.amount)}`); sub.reload(); } catch (e: any) { toast(e.message, "bad"); } };
  if (!d || !f) return <div className="text-sm text-slate">{t("Loading…")}</div>;

  return (
    <section className="panel p-5">
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <h2 className="text-base font-semibold">{t("Subscription")}</h2>
        <Badge tone={SUB_TONE[d.status]}>{t(`sub.${d.status}`)}</Badge>
        {d.plan && <span className="text-sm text-slate">{d.plan} · {t(d.interval)}</span>}
        {d.pending_plan && <Badge tone="info">{t("From next period")}: {d.pending_plan}</Badge>}
        {d.cancel_at_period_end && <Badge tone="warn">{t("Cancels at period end")}</Badge>}
      </div>
      <div className="mb-4 grid gap-2 text-sm sm:grid-cols-3">
        <div><span className="text-slate">{t("Paid until")}:</span> {date(d.current_period_end)}</div>
        <div><span className="text-slate">{t("Access until (with grace)")}:</span> {date(d.access_until)}</div>
        {d.trial_ends_at && <div><span className="text-slate">{t("Trial ends")}:</span> {date(d.trial_ends_at)}</div>}
        {d.next && <div><span className="text-slate">{t("Next bill")}:</span> <b>{usd(d.next.total)}</b></div>}
      </div>
      <ErrorNote error={error} />
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label={t("Plan")}><select className="input" value={f.plan_id} onChange={(e) => setF({ ...f, plan_id: +e.target.value })}>
          {cat.data?.plans?.map((p: any) => <option key={p.id} value={p.id}>{p.name} · {usd(p.price_monthly)}</option>)}</select></Field>
        <Field label={t("Billing")}><select className="input" value={f.interval} onChange={(e) => setF({ ...f, interval: e.target.value })}>
          <option value="monthly">{t("monthly")}</option><option value="yearly">{t("yearly")}</option></select></Field>
        <div className="flex items-end gap-2">
          <button className="btn-primary" onClick={() => update({ plan_id: f.plan_id, interval: f.interval })}>{t("Change plan")}</button>
        </div>
        <Field label={t("Coupon")}><div className="flex gap-2"><input className="input uppercase" dir="ltr" value={f.coupon} onChange={(e) => setF({ ...f, coupon: e.target.value.toUpperCase() })} />
          <button className="btn-ghost" disabled={!f.coupon} onClick={() => update({ coupon: f.coupon })}>{t("Apply")}</button></div></Field>
        <Field label={t("Grace days (empty = plan's)")}><div className="flex gap-2"><input className="input" type="number" value={f.grace_days} onChange={(e) => setF({ ...f, grace_days: e.target.value })} />
          <button className="btn-ghost" onClick={() => update({ grace_days: f.grace_days === "" ? null : +f.grace_days })}>{t("Save")}</button></div></Field>
        <Field label={t("Free trial from today (days)")}><div className="flex gap-2"><input className="input" type="number" id="trial" defaultValue={14} />
          <button className="btn-ghost" onClick={() => update({ trial_days: +(document.getElementById("trial") as HTMLInputElement).value })}>{t("Start")}</button></div></Field>
      </div>
      <div className="mt-4">
        <div className="mb-1 text-sm font-medium">{t("Add-ons")}</div>
        <div className="flex flex-wrap gap-2">{cat.data?.addons?.filter((a: any) => a.is_active).map((a: any) => {
          const it = f.items.find((x: any) => x.addon_id === a.id);
          return <label key={a.id} className="flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-sm">
            <input type="checkbox" className="accent-signal" checked={!!it} onChange={() => setF({ ...f, items: it ? f.items.filter((x: any) => x.addon_id !== a.id) : [...f.items, { addon_id: a.id, quantity: 1 }] })} />
            {a.name} ({usd(a.price_monthly)})
            {it && <input className="input !w-14 !px-1 !py-0.5" type="number" min={1} value={it.quantity} onChange={(e) => setF({ ...f, items: f.items.map((x: any) => x.addon_id === a.id ? { ...x, quantity: +e.target.value } : x) })} />}
          </label>;
        })}</div>
        <button className="link -ms-2 mt-1" onClick={() => update({ addons: f.items })}>{t("Save add-ons")}</button>
      </div>
      <div className="mt-4 flex flex-wrap gap-2 border-t border-line pt-4">
        <button className="btn-ghost" onClick={invoiceNow}>{t("Bill the next period now")}</button>
        {d.cancel_at_period_end ? <button className="btn-ghost" onClick={() => update({ cancel_at_period_end: false })}>{t("Keep subscription")}</button>
          : <button className="btn-ghost" onClick={() => confirm(t("Cancel at the end of the paid period?")) && update({ cancel_at_period_end: true })}>{t("Cancel at period end")}</button>}
        {d.status !== "suspended" ? <button className="btn-ghost !text-rust" onClick={() => confirm(t("Suspend now?")) && update({ status: "suspended" })}>{t("Suspend now")}</button>
          : <button className="btn-ghost" onClick={() => update({ status: "active" })}>{t("Reactivate")}</button>}
      </div>
      <h3 className="mb-2 mt-6 text-sm font-semibold">{t("Bills")}</h3>
      <div className="rounded-lg border border-line"><Table rows={sub.data.invoices} pageSize={8} empty={t("No bills.")} cols={[
        { h: t("Number"), c: (i: any) => <span dir="ltr">{i.number}</span> }, { h: t("Period"), c: (i: any) => i.period_start ? `${date(i.period_start)} → ${date(i.period_end)}` : "—" },
        { h: t("Amount"), c: (i: any) => usd(i.amount), end: true }, { h: t("Paid"), c: (i: any) => usd(i.paid_amount ?? 0), end: true },
        { h: t("Status"), c: (i: any) => <Badge tone={i.status === "paid" ? "good" : i.status === "void" ? "neutral" : "warn"}>{t(`bill.${i.status}`)}</Badge> },
        { h: "", c: (i: any) => i.status === "unpaid" && <button className="link" onClick={() => { setError(null); setPay({ id: i.id, number: i.number, amount: +(i.amount - (i.paid_amount ?? 0)).toFixed(2), method: "bank", reference: "" }); }}>{t("Record payment")}</button> },
      ]} /></div>
      <Modal title={pay ? `${t("Record payment")} · ${pay.number}` : ""} open={!!pay} onClose={() => setPay(null)} onSave={recordPayment}>
        {pay && <div className="grid grid-cols-2 gap-3">
          <ErrorNote error={error} />
          <Field label={t("Amount") + " ($)"}><input className="input" type="number" value={pay.amount} onChange={(e) => setPay({ ...pay, amount: e.target.value })} /></Field>
          <Field label={t("Method")}><select className="input" value={pay.method} onChange={(e) => setPay({ ...pay, method: e.target.value })}>{["bank", "cash", "card", "cheque"].map((m) => <option key={m} value={m}>{t(m)}</option>)}</select></Field>
          <div className="col-span-2"><Field label={t("Reference")}><input className="input" value={pay.reference} onChange={(e) => setPay({ ...pay, reference: e.target.value })} /></Field></div>
          <p className="col-span-2 text-xs text-slate">{t("When the bill is fully paid, the subscription moves to the paid period automatically.")}</p>
        </div>}
      </Modal>
    </section>
  );
}
