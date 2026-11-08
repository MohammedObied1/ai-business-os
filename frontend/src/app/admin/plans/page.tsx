"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { date } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { Badge, ErrorNote, Field, Modal, PageTitle, Table, Tabs, toast } from "@/components/ui";

const TABS = ["plans", "add-ons", "coupons"] as const;
const usd = (n: number) => `$${(n ?? 0).toLocaleString("en", { maximumFractionDigits: 2 })}`;
const EMPTY_PLAN = { name: "", price_monthly: 0, price_yearly: 0, max_users: 5, max_branches: 1, max_warehouses: 0, max_storage_mb: 0, max_ai_requests: 0,
  max_api_requests: 0, trial_days: 14, grace_days: 7, features: [] as string[], description: "", is_active: true };
const EMPTY_ADDON = { code: "", name: "", price_monthly: 0, price_yearly: 0, grants: {} as Record<string, number>, features: [] as string[], is_active: true };
const EMPTY_COUPON = { code: "", percent_off: 10, amount_off: 0, duration: "once", cycles: null as number | null, max_redemptions: null as number | null, valid_until: "", is_active: true };

/** Plans, add-ons and coupons the platform sells. Prices live here (in the database), never in code. */
export default function Plans() {
  const { t } = useT();
  const [tab, setTab] = useState<(typeof TABS)[number]>("plans");
  const cat = useApi<any>("/api/platform/billing/catalog", [], { platform: true });
  const [plan, setPlan] = useState<any>(null);
  const [addon, setAddon] = useState<any>(null);
  const [coupon, setCoupon] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const features: string[] = cat.data?.features ?? [];
  const limits: string[] = cat.data?.limits ?? [];

  const save = async (path: string, id: number | undefined, body: any, done: () => void) => {
    setError(null);
    try { await api(id ? `${path}/${id}` : path, { method: id ? "PUT" : "POST", json: body, platform: true }); done(); toast("Saved"); cat.reload(); }
    catch (e: any) { setError(e.message); }
  };
  const toggleIn = (list: string[], x: string) => (list.includes(x) ? list.filter((y) => y !== x) : [...list, x]);
  const lim = (n: number) => (n ? n.toLocaleString() : "∞");

  return (
    <>
      <PageTitle title={t("Plans & pricing")} help={t("Plans help")} actions={
        tab === "plans" ? <button className="btn-primary" onClick={() => { setError(null); setPlan({ ...EMPTY_PLAN }); }}>+ {t("New plan")}</button>
          : tab === "add-ons" ? <button className="btn-primary" onClick={() => { setError(null); setAddon({ ...EMPTY_ADDON }); }}>+ {t("New add-on")}</button>
            : <button className="btn-primary" onClick={() => { setError(null); setCoupon({ ...EMPTY_COUPON }); }}>+ {t("New coupon")}</button>} />
      <Tabs tabs={TABS} value={tab} onChange={setTab} />

      {tab === "plans" && <div className="panel"><Table rows={cat.data?.plans ?? null} onRow={(p: any) => { setError(null); setPlan({ ...EMPTY_PLAN, ...p, description: p.description ?? "" }); }} cols={[
        { h: t("Plan"), c: (p: any) => <span className="font-medium">{p.name}</span> },
        { h: t("Monthly"), c: (p: any) => usd(p.price_monthly), end: true }, { h: t("Yearly"), c: (p: any) => p.price_yearly ? usd(p.price_yearly) : "—", end: true },
        { h: t("Users"), c: (p: any) => lim(p.max_users), end: true }, { h: t("Warehouses"), c: (p: any) => lim(p.max_warehouses), end: true },
        { h: t("AI / month"), c: (p: any) => lim(p.max_ai_requests), end: true }, { h: t("Trial"), c: (p: any) => p.trial_days ? t("{n} days", { n: p.trial_days }) : "—" },
        { h: t("Features"), c: (p: any) => p.features.length ? <span className="text-xs">{p.features.map((f: string) => t(`feature.${f}`)).join(" · ")}</span> : <Badge tone="good">{t("All")}</Badge> },
        { h: t("Status"), c: (p: any) => <Badge tone={p.is_active ? "good" : "neutral"}>{p.is_active ? t("Active") : t("Stopped")}</Badge> },
      ]} /></div>}
      {tab === "add-ons" && <div className="panel"><Table rows={cat.data?.addons ?? null} empty={t("No add-ons yet.")} onRow={(a: any) => { setError(null); setAddon({ ...a }); }} cols={[
        { h: t("Code"), c: (a: any) => <span dir="ltr" className="font-mono text-xs">{a.code}</span> }, { h: t("Name"), c: (a: any) => a.name },
        { h: t("Monthly"), c: (a: any) => usd(a.price_monthly), end: true },
        { h: t("Gives"), c: (a: any) => <span className="text-xs">{Object.entries(a.grants).map(([k, v]) => `+${v} ${t(`limit.${k}`)}`).concat(a.features.map((f: string) => t(`feature.${f}`))).join(" · ")}</span> },
      ]} /></div>}
      {tab === "coupons" && <div className="panel"><Table rows={cat.data?.coupons ?? null} empty={t("No coupons yet.")} onRow={(c: any) => { setError(null); setCoupon({ ...c, valid_until: c.valid_until ?? "" }); }} cols={[
        { h: t("Code"), c: (c: any) => <span dir="ltr" className="font-mono">{c.code}</span> },
        { h: t("Discount"), c: (c: any) => [c.percent_off ? `${c.percent_off}%` : "", c.amount_off ? usd(c.amount_off) : ""].filter(Boolean).join(" + ") },
        { h: t("For"), c: (c: any) => c.duration === "repeating" ? t("{n} bills", { n: c.cycles }) : t(`coupon.${c.duration}`) },
        { h: t("Used"), c: (c: any) => `${c.redeemed}${c.max_redemptions ? ` / ${c.max_redemptions}` : ""}` }, { h: t("Valid until"), c: (c: any) => date(c.valid_until) },
      ]} /></div>}

      <Modal title={plan?.id ? plan.name : t("New plan")} open={!!plan} onClose={() => setPlan(null)} onSave={() => save("/api/platform/billing/plans", plan.id, { ...plan, id: undefined }, () => setPlan(null))}>
        {plan && <>
          <ErrorNote error={error} />
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2"><Field label={t("Name")}><input className="input" value={plan.name} onChange={(e) => setPlan({ ...plan, name: e.target.value })} /></Field></div>
            <Field label={t("Monthly price ($)")}><input className="input" type="number" value={plan.price_monthly} onChange={(e) => setPlan({ ...plan, price_monthly: +e.target.value })} /></Field>
            <Field label={t("Yearly price ($, 0 = 12 × monthly)")}><input className="input" type="number" value={plan.price_yearly} onChange={(e) => setPlan({ ...plan, price_yearly: +e.target.value })} /></Field>
            {limits.map((k) => <Field key={k} label={`${t(`limit.${k}`)} (0 = ∞)`}><input className="input" type="number" value={plan[k]} onChange={(e) => setPlan({ ...plan, [k]: +e.target.value })} /></Field>)}
            <Field label={t("Free trial (days)")}><input className="input" type="number" value={plan.trial_days} onChange={(e) => setPlan({ ...plan, trial_days: +e.target.value })} /></Field>
            <Field label={t("Grace after an unpaid bill (days)")}><input className="input" type="number" value={plan.grace_days} onChange={(e) => setPlan({ ...plan, grace_days: +e.target.value })} /></Field>
          </div>
          <p className="mb-1 mt-4 text-sm font-medium">{t("Features (none ticked = all)")}</p>
          <div className="flex flex-wrap gap-2">{features.map((f) => <label key={f} className="flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-sm">
            <input type="checkbox" className="accent-signal" checked={plan.features.includes(f)} onChange={() => setPlan({ ...plan, features: toggleIn(plan.features, f) })} />{t(`feature.${f}`)}</label>)}</div>
          <label className="mt-3 flex items-center gap-2 text-sm"><input type="checkbox" className="accent-signal" checked={plan.is_active} onChange={(e) => setPlan({ ...plan, is_active: e.target.checked })} />{t("Active")}</label>
        </>}
      </Modal>

      <Modal title={addon?.id ? addon.name : t("New add-on")} open={!!addon} onClose={() => setAddon(null)} onSave={() => save("/api/platform/billing/addons", addon.id, { ...addon, id: undefined }, () => setAddon(null))}>
        {addon && <>
          <ErrorNote error={error} />
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("Code")}><input className="input" dir="ltr" value={addon.code} onChange={(e) => setAddon({ ...addon, code: e.target.value })} /></Field>
            <Field label={t("Name")}><input className="input" value={addon.name} onChange={(e) => setAddon({ ...addon, name: e.target.value })} /></Field>
            <Field label={t("Monthly price ($)")}><input className="input" type="number" value={addon.price_monthly} onChange={(e) => setAddon({ ...addon, price_monthly: +e.target.value })} /></Field>
            <Field label={t("Yearly price ($)")}><input className="input" type="number" value={addon.price_yearly} onChange={(e) => setAddon({ ...addon, price_yearly: +e.target.value })} /></Field>
            {limits.map((k) => <Field key={k} label={`+ ${t(`limit.${k}`)}`}><input className="input" type="number" value={addon.grants[k] ?? 0}
              onChange={(e) => setAddon({ ...addon, grants: Object.fromEntries(Object.entries({ ...addon.grants, [k]: +e.target.value } as Record<string, number>).filter(([, v]) => v > 0)) })} /></Field>)}
          </div>
          <p className="mb-1 mt-4 text-sm font-medium">{t("Unlocks features")}</p>
          <div className="flex flex-wrap gap-2">{features.map((f) => <label key={f} className="flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-sm">
            <input type="checkbox" className="accent-signal" checked={addon.features.includes(f)} onChange={() => setAddon({ ...addon, features: toggleIn(addon.features, f) })} />{t(`feature.${f}`)}</label>)}</div>
        </>}
      </Modal>

      <Modal title={coupon?.id ? coupon.code : t("New coupon")} open={!!coupon} onClose={() => setCoupon(null)}
        onSave={() => save("/api/platform/billing/coupons", coupon.id, { ...coupon, id: undefined, redeemed: undefined, valid_until: coupon.valid_until || null }, () => setCoupon(null))}>
        {coupon && <>
          <ErrorNote error={error} />
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("Code")}><input className="input uppercase" dir="ltr" value={coupon.code} onChange={(e) => setCoupon({ ...coupon, code: e.target.value.toUpperCase() })} /></Field>
            <Field label={t("Discount %")}><input className="input" type="number" value={coupon.percent_off} onChange={(e) => setCoupon({ ...coupon, percent_off: +e.target.value })} /></Field>
            <Field label={t("Or fixed amount ($)")}><input className="input" type="number" value={coupon.amount_off} onChange={(e) => setCoupon({ ...coupon, amount_off: +e.target.value })} /></Field>
            <Field label={t("For")}><select className="input" value={coupon.duration} onChange={(e) => setCoupon({ ...coupon, duration: e.target.value })}>
              {["once", "repeating", "forever"].map((d) => <option key={d} value={d}>{t(`coupon.${d}`)}</option>)}</select></Field>
            {coupon.duration === "repeating" && <Field label={t("Number of bills")}><input className="input" type="number" value={coupon.cycles ?? 3} onChange={(e) => setCoupon({ ...coupon, cycles: +e.target.value })} /></Field>}
            <Field label={t("Max uses (empty = no limit)")}><input className="input" type="number" value={coupon.max_redemptions ?? ""} onChange={(e) => setCoupon({ ...coupon, max_redemptions: e.target.value ? +e.target.value : null })} /></Field>
            <Field label={t("Valid until")}><input className="input" type="date" value={coupon.valid_until} onChange={(e) => setCoupon({ ...coupon, valid_until: e.target.value })} /></Field>
          </div>
        </>}
      </Modal>
    </>
  );
}
