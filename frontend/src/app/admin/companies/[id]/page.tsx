"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, setToken } from "@/lib/api";
import { CURRENCIES } from "@/lib/constants";
import { useApi } from "@/lib/hooks";
import { date, money, num } from "@/lib/format";
import { AuditTable } from "@/components/AuditTable";
import { SubscriptionPanel } from "@/components/SubscriptionPanel";
import { useT } from "@/lib/i18n";
import { ErrorNote, Field, Modal, StatCard, Status, toast } from "@/components/ui";

export default function AdminCompany() {
  const { t, lang } = useT();
  const router = useRouter();
  const { id } = useParams<{ id: string }>();
  const { data: c, reload } = useApi<any>(`/api/platform/companies/${id}`, [], { platform: true });
  const { data: plans } = useApi<any[]>("/api/platform/plans", [], { platform: true });
  const [form, setForm] = useState<any>(null);
  const [pwOpen, setPwOpen] = useState(false);
  const [newPw, setNewPw] = useState("");
  const [delOpen, setDelOpen] = useState(false);
  const [confirmName, setConfirmName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [asOpen, setAsOpen] = useState(false);
  const { data: users } = useApi<any[]>(asOpen ? `/api/platform/companies/${id}/users` : null, [asOpen], { platform: true });

  useEffect(() => { if (c) setForm({ name: c.name, industry: c.industry ?? "", currency: c.currency, phone: c.phone ?? "", email: c.email ?? "", address: c.address ?? "", tax_number: c.tax_number ?? "",
    notes: c.notes ?? "", custom_domain: c.custom_domain ?? "", tax_rate: c.tax_rate ?? 0, plan_id: c.plan_id ?? 0, subscription_ends_at: c.subscription_ends_at ?? "" }); }, [c]);
  if (!c || !form) return <div className="text-sm text-slate">{t("Loading…")}</div>;
  const set = (k: string) => (e: any) => setForm({ ...form, [k]: e.target.value });

  const call = async (fn: () => Promise<any>, ok: string) => { setError(null); try { await fn(); toast(ok); reload(); return true; } catch (e: any) { setError(e.message); toast(e.message, "bad"); return false; } };
  const save = () => call(() => api(`/api/platform/companies/${id}`, { method: "PATCH", json: { ...form, tax_rate: +form.tax_rate, plan_id: +form.plan_id || null, subscription_ends_at: form.subscription_ends_at || null, custom_domain: form.custom_domain || null }, platform: true }), "Saved");
  const extend = (months: number) => call(() => api(`/api/platform/companies/${id}/extend?months=${months}`, { method: "POST", platform: true }), "Subscription renewed");
  const toggle = () => call(() => api(`/api/platform/companies/${id}`, { method: "PATCH", json: { is_active: !c.is_active }, platform: true }), c.is_active ? "Company suspended" : "Company activated");
  const enter = async (userId?: number) => {
    try {
      const r = await api(`/api/platform/companies/${id}/enter${userId ? `?user_id=${userId}` : ""}`, { method: "POST", platform: true });
      setToken(r.access_token);
      router.push("/command-center");
    } catch (e: any) { toast(e.message, "bad"); }
  };
  const resetPw = async () => { if (await call(() => api(`/api/platform/companies/${id}/owner-password`, { method: "POST", json: { new_password: newPw }, platform: true }), "Password changed")) setPwOpen(false); };
  const remove = async () => {
    setError(null);
    try { await api(`/api/platform/companies/${id}?confirm_name=${encodeURIComponent(confirmName)}`, { method: "DELETE", platform: true }); toast("Company deleted"); router.push("/admin"); }
    catch (e: any) { setError(e.message); }
  };

  return (
    <>
      <Link href="/admin" className="link -ms-2 mb-2 inline-block">{lang === "ar" ? "→" : "←"} {t("All companies")}</Link>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-3"><h1 className="text-2xl font-semibold">{c.name}</h1><Status value={c.is_active ? "active" : "suspended"} /></div>
          <p className="mt-1 text-sm text-slate">{t("Created")} {date(c.created_at)} · {t("Owner")}: {c.owner_name} (<span dir="ltr">{c.owner_email}</span>)</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="btn-primary" onClick={() => enter()}>{t("Open company")} {lang === "ar" ? "←" : "→"}</button>
          <button className="btn-ghost" onClick={() => setAsOpen(true)}>{t("Enter as a user")}</button>
          <button className="btn-ghost" onClick={() => { setError(null); setNewPw(""); setPwOpen(true); }}>{t("Reset owner password")}</button>
          <button className={c.is_active ? "btn-ghost !text-rust" : "btn-ghost !text-moss"} onClick={toggle}>{c.is_active ? t("Suspend") : t("Activate")}</button>
        </div>
      </div>

      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-5">
        <StatCard label={t("Users")} value={num(c.stats.users)} />
        <StatCard label={t("Products")} value={num(c.stats.products)} />
        <StatCard label={t("Customers")} value={num(c.stats.customers)} />
        <StatCard label={t("Invoices")} value={num(c.stats.invoices)} />
        <StatCard label={t("Total sales")} value={money(c.stats.revenue, c.currency)} note={c.stats.last_order ? `${t("Last order")}: ${date(c.stats.last_order)}` : undefined} />
      </div>

      <div className="mb-6"><SubscriptionPanel cid={+id} /></div>

      <div className="panel mb-6 p-5">
        <h2 className="mb-1 text-base font-semibold">{t("Manual override")}</h2>
        <p className="mb-4 text-xs text-slate">{t("Set the plan or the end date by hand (for special deals). Normally the billing above handles this.")}</p>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label={t("Plan")}><select className="input" value={form.plan_id} onChange={set("plan_id")}><option value={0}>{t("No plan (unlimited)")}</option>{plans?.map((p) => <option key={p.id} value={p.id}>{p.name} · {money(p.price_monthly, "ILS")}</option>)}</select></Field>
          <Field label={t("Subscription until (empty = no end)")}><input className="input" type="date" value={form.subscription_ends_at} onChange={set("subscription_ends_at")} /></Field>
          <div className="flex items-end gap-2"><button className="btn-ghost" onClick={() => extend(1)}>+ {t("1 month")}</button><button className="btn-ghost" onClick={() => extend(12)}>+ {t("1 year")}</button></div>
        </div>
        <div className="mt-4 flex justify-end"><button className="btn-primary" onClick={save}>{t("Save changes")}</button></div>
      </div>

      <div className="panel p-5">
        <h2 className="mb-4 text-base font-semibold">{t("Company info")}</h2>
        <ErrorNote error={error && !pwOpen && !delOpen ? error : null} />
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("Company name")}><input className="input" value={form.name} onChange={set("name")} /></Field>
          <Field label={t("Business type")}><input className="input" value={form.industry} onChange={set("industry")} /></Field>
          <Field label={t("Currency")}><select className="input" value={form.currency} onChange={set("currency")}>{CURRENCIES.map((x) => <option key={x}>{x}</option>)}</select></Field>
          <Field label={t("Tax number")}><input className="input" dir="ltr" value={form.tax_number} onChange={set("tax_number")} /></Field>
          <Field label={t("VAT rate %")}><input className="input" type="number" value={form.tax_rate} onChange={set("tax_rate")} /></Field>
          <Field label={t("Phone")}><input className="input" dir="ltr" value={form.phone} onChange={set("phone")} /></Field>
          <Field label={t("Email")}><input className="input" dir="ltr" value={form.email} onChange={set("email")} /></Field>
          <div className="sm:col-span-2"><Field label={t("City / address")}><input className="input" value={form.address} onChange={set("address")} /></Field></div>
          <div className="sm:col-span-2"><Field label={t("Custom domain (white-label), e.g. erp.company.com")}>
            <div className="flex items-center gap-2"><input className="input" dir="ltr" placeholder="erp.company.com" value={form.custom_domain} onChange={set("custom_domain")} />
              {c.custom_domain && (c.domain_verified_at ? <span className="shrink-0 text-xs text-moss">✓ {t("Verified")}</span> : <span className="shrink-0 text-xs text-amber">{t("Not verified yet")}</span>)}</div>
            <p className="mt-1 text-xs text-slate">{t("Setting it here skips DNS verification (you already confirmed ownership yourself).")}</p>
          </Field></div>
          <div className="sm:col-span-2"><Field label={t("Private notes (only you see these)")}><textarea className="input h-24" value={form.notes} onChange={set("notes")} placeholder={t("Plan, price, contact person, renewal date…")} /></Field></div>
        </div>
        <div className="mt-4 flex justify-end"><button className="btn-primary" onClick={save}>{t("Save changes")}</button></div>
      </div>

      <div className="panel mt-6 border-rust/40 p-5">
        <h2 className="text-base font-semibold text-rust">{t("Danger zone")}</h2>
        <p className="mt-1 text-sm text-slate">{t("Deleting a company removes all its data permanently. Suspending is reversible.")}</p>
        <button className="btn-ghost mt-3 !border-rust/40 !text-rust" onClick={() => { setError(null); setConfirmName(""); setDelOpen(true); }}>{t("Delete company")}</button>
      </div>

      <section className="mt-8">
        <h2 className="mb-1 text-lg font-semibold">{t("Company activity")}</h2>
        <p className="mb-3 text-sm text-slate">{t("Everything done inside this company, including your own visits as platform admin.")}</p>
        <AuditTable base={`/api/platform/companies/${id}/audit`} platform />
      </section>

      <Modal title={t("Reset owner password")} open={pwOpen} onClose={() => setPwOpen(false)} onSave={resetPw}>
        <ErrorNote error={error} />
        <Field label={t("New password")}><input className="input" dir="ltr" value={newPw} onChange={(e) => setNewPw(e.target.value)} /></Field>
      </Modal>
      <Modal title={t("Delete company")} open={delOpen} onClose={() => setDelOpen(false)}>
        <ErrorNote error={error} />
        <p className="mb-3 text-sm">{t("Type the company name to confirm:")} <b>{c.name}</b></p>
        <input className="input" value={confirmName} onChange={(e) => setConfirmName(e.target.value)} />
        <div className="mt-5 flex justify-end gap-2">
          <button className="btn-ghost" onClick={() => setDelOpen(false)}>{t("Cancel")}</button>
          <button className="btn bg-rust text-white hover:bg-rust/90" disabled={confirmName !== c.name} onClick={remove}>{t("Delete forever")}</button>
        </div>
      </Modal>
      <Modal title={t("Enter as a user")} open={asOpen} onClose={() => setAsOpen(false)}>
        <p className="mb-3 text-sm text-slate">{t("You will see exactly what this user sees. The visit is recorded in the company's activity log.")}</p>
        <div className="divide-y divide-line">{(users ?? []).map((u: any) => (
          <button key={u.id} disabled={!u.is_active} onClick={() => enter(u.id)} className="flex w-full items-center justify-between gap-3 px-2 py-2 text-start hover:bg-paper disabled:opacity-40">
            <span><span className="font-medium">{u.full_name}</span> <span dir="ltr" className="text-xs text-slate">{u.email}</span></span>
            <span className="text-xs text-slate">{u.role ?? "—"}</span>
          </button>))}</div>
      </Modal>
    </>
  );
}
