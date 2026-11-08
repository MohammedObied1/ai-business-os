"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { applyBrand } from "@/lib/brand";
import { useApi } from "@/lib/hooks";
import { date } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { LimitBars, SUB_TONE } from "./SubscriptionPanel";
import { Badge, ErrorNote, Field, Table, toast } from "./ui";

/** Extra company settings: other currencies, brand & online shop, approval limits, subscription bills. */
export function CompanyExtras() {
  const { t } = useT();
  const { company, reloadCompany, can } = useSession();
  const editable = can("settings:write");
  const cur = useApi<any>("/api/currencies");
  const tzList = useApi<string[]>("/api/auth/timezones");
  const sub = useApi<any>(editable ? "/api/subscription" : null);
  const [rate, setRate] = useState({ code: "USD", rate: "" });
  const [f, setF] = useState<any>(null);
  const [domainInput, setDomainInput] = useState("");
  const [domainRecord, setDomainRecord] = useState<any>(null);
  const [domainError, setDomainError] = useState<string | null>(null);
  const [domainBusy, setDomainBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (company) setF({ brand_color: company.brand_color ?? "#0f766e", slug: company.slug ?? "", catalog_enabled: !!company.catalog_enabled,
      payment_instructions: company.payment_instructions ?? "", approval_discount_pct: company.approval_discount_pct ?? 0, approval_expense_amount: company.approval_expense_amount ?? 0,
      costing_method: company.costing_method ?? "average", portal_orders_enabled: company.portal_orders_enabled ?? true, online_order_status: company.online_order_status ?? "quotation",
      timezone: company.timezone ?? "Asia/Hebron" });
  }, [company]);
  if (!f) return null;
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.type === "number" ? +e.target.value : e.target.value });

  const save = async () => {
    setError(null);
    try { await api("/api/auth/company", { method: "PATCH", json: { ...f, slug: f.slug || null } }); reloadCompany(); applyBrand(f.brand_color); toast("Saved"); } catch (e: any) { setError(e.message); }
  };
  const saveRate = async () => {
    try { await api("/api/currencies", { method: "PUT", json: { code: rate.code, rate: +rate.rate } }); setRate({ code: "USD", rate: "" }); cur.reload(); toast("Saved"); } catch (e: any) { toast(e.message, "bad"); }
  };
  const shopUrl = typeof window !== "undefined" && f.slug ? `${window.location.origin}/shop/${f.slug}` : "";
  const startDomain = async () => {
    setDomainError(null); setDomainBusy(true);
    try { const r = await api("/api/auth/company/domain/start", { method: "POST", json: { domain: domainInput } }); setDomainRecord(r); }
    catch (e: any) { setDomainError(e.message); } finally { setDomainBusy(false); }
  };
  const verifyDomain = async () => {
    setDomainError(null); setDomainBusy(true);
    try { await api("/api/auth/company/domain/verify", { method: "POST" }); toast("Domain verified"); setDomainRecord(null); setDomainInput(""); reloadCompany(); }
    catch (e: any) { setDomainError(e.message); } finally { setDomainBusy(false); }
  };
  const removeDomain = async () => {
    if (!confirm(t("Remove this custom domain?"))) return;
    try { await api("/api/auth/company/domain", { method: "DELETE" }); toast("Removed"); reloadCompany(); } catch (e: any) { toast(e.message, "bad"); }
  };

  return (
    <>
      <section className="panel p-5">
        <h2 className="text-base font-semibold">{t("Other currencies")}</h2>
        <p className="mb-3 mt-1 text-sm text-slate">{t("Exchange rate = how much of your main currency ({c}) one unit is worth. Update it when the rate changes.", { c: cur.data?.base ?? company.currency })}</p>
        <div className="rounded-lg border border-line"><Table rows={cur.data?.items ?? null} empty={t("Only the main currency. Add USD or JOD if you sell or buy with them.")} cols={[
          { h: t("Currency"), c: (x: any) => <span className="font-medium" dir="ltr">{x.code}</span> },
          { h: t("Rate"), c: (x: any) => <span dir="ltr">1 {x.code} = {x.rate} {cur.data?.base}</span> },
          { h: t("Updated"), c: (x: any) => date(x.updated_at) },
          { h: "", c: (x: any) => editable && <button className="link" onClick={() => setRate({ code: x.code, rate: String(x.rate) })}>{t("Edit")}</button> },
        ]} /></div>
        {editable && <div className="mt-3 flex flex-wrap items-end gap-2">
          <Field label={t("Code")}><input className="input !w-24 uppercase" dir="ltr" maxLength={3} value={rate.code} onChange={(e) => setRate({ ...rate, code: e.target.value.toUpperCase() })} /></Field>
          <Field label={t("Rate")}><input className="input !w-32" type="number" step="0.0001" value={rate.rate} onChange={(e) => setRate({ ...rate, rate: e.target.value })} /></Field>
          <button className="btn-ghost" disabled={!(+rate.rate > 0)} onClick={saveRate}>{t("Save rate")}</button>
        </div>}
      </section>

      <section className="panel p-5">
        <h2 className="mb-4 text-base font-semibold">{t("Brand, online shop & customer portal")}</h2>
        <ErrorNote error={error} />
        <fieldset disabled={!editable} className="grid gap-3 sm:grid-cols-2">
          <Field label={t("Brand colour")}><div className="flex items-center gap-2"><input type="color" className="h-10 w-14 rounded border border-line" value={f.brand_color} onChange={set("brand_color")} />
            <span dir="ltr" className="font-mono text-sm">{f.brand_color}</span></div></Field>
          <Field label={t("Shop link name")}><input className="input" dir="ltr" placeholder="my-shop" value={f.slug} onChange={(e) => setF({ ...f, slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "") })} /></Field>
          <label className="flex items-center gap-2 text-sm sm:col-span-2"><input type="checkbox" className="h-4 w-4 accent-signal" checked={f.catalog_enabled} onChange={set("catalog_enabled")} />
            {t("Open the online shop (customers order from a link)")}</label>
          <label className="flex items-center gap-2 text-sm sm:col-span-2"><input type="checkbox" className="h-4 w-4 accent-signal" checked={f.portal_orders_enabled} onChange={set("portal_orders_enabled")} />
            {t("Customers can request orders from their portal")}</label>
          <Field label={t("Orders from the shop and the portal arrive as")}><select className="input" value={f.online_order_status} onChange={set("online_order_status")}>
            <option value="quotation">{t("Quotation (price offer)")}</option><option value="draft">{t("Draft sales order")}</option></select></Field>
          <p className="self-end text-xs text-slate">{t("Either way, your team confirms the order before stock is taken.")}</p>
          {f.catalog_enabled && shopUrl && <div className="sm:col-span-2 rounded-lg bg-paper p-3 text-sm"><a className="text-signal" dir="ltr" href={shopUrl} target="_blank" rel="noreferrer">{shopUrl}</a>
            <button type="button" className="link ms-2" onClick={() => { navigator.clipboard?.writeText(shopUrl); toast("Copied"); }}>{t("Copy")}</button></div>}
          <div className="sm:col-span-2"><Field label={t("How customers can pay you (shown in the customer portal)")}>
            <textarea className="input h-20" placeholder={t("e.g. Bank of Palestine, account 123456, IBAN …")} value={f.payment_instructions} onChange={set("payment_instructions")} /></Field></div>
        </fieldset>

        <h3 className="mb-2 mt-5 text-sm font-semibold">{t("Custom domain")}</h3>
        <p className="mb-2 text-sm text-slate">{t("Custom domain help")}</p>
        {editable && <>
          <ErrorNote error={domainError} />
          {company.custom_domain ? <div className="flex flex-wrap items-center gap-2 rounded-lg bg-paper p-3 text-sm">
            <span dir="ltr" className="font-mono">{company.custom_domain}</span>
            {company.domain_verified_at ? <Badge tone="good">✓ {t("Verified")}</Badge> : <Badge tone="warn">{t("Not verified yet")}</Badge>}
            <button className="link-danger ms-auto text-xs" onClick={removeDomain}>{t("Remove")}</button>
          </div> : !domainRecord && <div className="flex gap-2">
            <input className="input" dir="ltr" placeholder="erp.yourcompany.com" value={domainInput} onChange={(e) => setDomainInput(e.target.value)} />
            <button className="btn-ghost shrink-0" disabled={domainBusy || !domainInput} onClick={startDomain}>{t("Start")}</button>
          </div>}
          {domainRecord && <div className="mt-2 rounded-lg bg-paper p-3 text-sm">
            <p className="mb-2">{t("Add this DNS record at your domain provider, then click Verify:")}</p>
            <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 font-mono text-xs" dir="ltr">
              <span className="text-slate">TYPE</span><span>TXT</span>
              <span className="text-slate">NAME</span><span>{domainRecord.record_name}</span>
              <span className="text-slate">VALUE</span><span>{domainRecord.record_value}</span>
            </div>
            <div className="mt-3 flex gap-2">
              <button className="btn-primary" disabled={domainBusy} onClick={verifyDomain}>{domainBusy ? "…" : t("Verify")}</button>
              <button className="btn-ghost" onClick={() => setDomainRecord(null)}>{t("Cancel")}</button>
            </div>
          </div>}
        </>}

        <h3 className="mb-2 mt-5 text-sm font-semibold">{t("Timezone")}</h3>
        <p className="mb-2 text-sm text-slate">{t("Timezone help")}</p>
        <fieldset disabled={!editable}><Field label={t("Timezone")}><select className="input max-w-sm" dir="ltr" value={f.timezone} onChange={set("timezone")}>
          {tzList.data?.map((z: string) => <option key={z} value={z}>{z}</option>)}</select></Field></fieldset>

        <h3 className="mb-2 mt-5 text-sm font-semibold">{t("Inventory costing")}</h3>
        <fieldset disabled={!editable} className="grid gap-2 sm:grid-cols-2">
          {(["average", "fifo"] as const).map((m) => (
            <label key={m} className={`flex cursor-pointer items-start gap-2 rounded-lg border p-3 text-sm ${f.costing_method === m ? "border-signal bg-signal-soft/50" : "border-line"}`}>
              <input type="radio" className="mt-0.5 accent-signal" checked={f.costing_method === m} onChange={() => setF({ ...f, costing_method: m })} />
              <span><b>{t(m === "average" ? "Weighted average" : "FIFO (first in, first out)")}</b>
                <span className="block text-xs text-slate">{t(m === "average" ? "Costing average help" : "Costing fifo help")}</span></span>
            </label>))}
        </fieldset>
        <p className="mt-1 text-xs text-slate">{t("Batches and expiry dates always keep their own cost. Changing the method affects stock that leaves from now on.")}</p>
        <h3 className="mb-3 mt-5 text-sm font-semibold">{t("Manager approval")}</h3>
        <fieldset disabled={!editable} className="grid gap-3 sm:grid-cols-2">
          <Field label={t("Discount above % needs approval (0 = off)")}><input className="input" type="number" value={f.approval_discount_pct} onChange={set("approval_discount_pct")} /></Field>
          <Field label={t("Expense above amount needs approval (0 = off)")}><input className="input" type="number" value={f.approval_expense_amount} onChange={set("approval_expense_amount")} /></Field>
        </fieldset>
        <p className="mt-2 text-xs text-slate">{t("Selling below cost always needs approval. Managers approve from the Approvals page.")}</p>
        {editable && <div className="mt-4 flex justify-end"><button className="btn-primary" onClick={save}>{t("Save changes")}</button></div>}
      </section>

      {editable && sub.data && <section className="panel p-5">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <h2 className="text-base font-semibold">{t("Subscription")}</h2>
          <Badge tone={SUB_TONE[sub.data.status]}>{t(`sub.${sub.data.status}`)}</Badge>
          {sub.data.plan && <span className="text-sm text-slate">{sub.data.plan} · {t(sub.data.interval)}</span>}
          {sub.data.access_until && <span className="ms-auto text-sm text-slate">{t("Access until")} {date(sub.data.access_until)}</span>}
        </div>
        {["grace", "past_due"].includes(sub.data.status) && <p className="mb-4 rounded-lg bg-amber-soft p-3 text-sm text-amber">{t("A subscription bill is unpaid. Access continues until the date above, then the account is paused.")}</p>}
        <LimitBars limits={sub.data.limits} />
        <h3 className="mb-2 mt-5 text-sm font-semibold">{t("Bills")}</h3>
        <div className="rounded-lg border border-line"><Table rows={sub.data.invoices ?? []} empty={t("No bills.")} cols={[
          { h: t("Number"), c: (i: any) => <span dir="ltr">{i.number}</span> }, { h: t("Period"), c: (i: any) => i.period_start ? `${date(i.period_start)} → ${date(i.period_end)}` : "—" },
          { h: t("Due"), c: (i: any) => date(i.due_date) }, { h: t("Amount"), c: (i: any) => `$${i.amount}`, end: true },
          { h: t("Status"), c: (i: any) => <Badge tone={i.status === "paid" ? "good" : i.status === "void" ? "neutral" : "warn"}>{t(`bill.${i.status}`)}</Badge> },
        ]} /></div>
      </section>}
    </>
  );
}
