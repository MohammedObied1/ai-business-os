"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { date, money, num } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { ErrorNote, Field, Modal, PageTitle, StatCard, Status, Table, toast, useForm } from "@/components/ui";
import { CURRENCIES } from "@/lib/constants";



const EMPTY = { name: "", industry: "", currency: "ILS", phone: "", email: "", address: "", tax_number: "", notes: "", owner_name: "", owner_email: "", owner_password: "",
  tax_rate: 16, plan_id: 0, subscription_ends_at: "" };

export default function AdminHome() {
  const { t } = useT();
  const router = useRouter();
  const { data, reload } = useApi<any[]>("/api/platform/companies", [], { platform: true });
  const { data: ov } = useApi<any>("/api/platform/overview", [data], { platform: true });
  const { data: plans } = useApi<any[]>("/api/platform/plans", [], { platform: true });
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const f = useForm(EMPTY);

  const rows = data?.filter((c) => !q || `${c.name} ${c.owner_email ?? ""} ${c.owner_name ?? ""}`.toLowerCase().includes(q.toLowerCase())) ?? null;
  const active = data?.filter((c) => c.is_active).length ?? 0;
  const users = data?.reduce((s, c) => s + c.stats.users, 0) ?? 0;

  const genPassword = () => f.setV({ ...f.v, owner_password: Math.random().toString(36).slice(2, 6) + Math.random().toString(36).slice(2, 8).toUpperCase() });
  const save = async () => {
    setError(null);
    try {
      const c = await api("/api/platform/companies", { method: "POST", json: { ...f.v, plan_id: +f.v.plan_id || null, subscription_ends_at: f.v.subscription_ends_at || null }, platform: true });
      toast("Company created");
      setOpen(false); f.reset(); reload();
      router.push(`/admin/companies/${c.id}`);
    } catch (e: any) { setError(e.message); }
  };

  return (
    <>
      <PageTitle title={t("Companies")} help={t("Admin help")} actions={<button className="btn-primary" onClick={() => { setError(null); setOpen(true); }}>+ {t("New company")}</button>} />
      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label={t("Companies")} value={num(data?.length ?? 0)} />
        <StatCard label={t("Active")} value={num(active)} note={data && data.length - active ? `${data.length - active} ${t("suspended")}` : undefined} tone={data && data.length - active ? "bad" : "neutral"} />
        <StatCard label={t("Users")} value={num(users)} />
        <StatCard label={t("Monthly income")} value={money(ov?.mrr ?? 0, "ILS")} tone="good" />
      </div>
      {ov && (ov.expired.length > 0 || ov.expiring_soon.length > 0) && (
        <div className="mb-6 grid gap-3 sm:grid-cols-2">
          {ov.expired.length > 0 && <div className="rounded-xl bg-rust-soft p-4 text-sm text-rust"><b>{t("Subscription expired")}:</b> {ov.expired.map((c: any) => <button key={c.id} className="ms-2 underline" onClick={() => router.push(`/admin/companies/${c.id}`)}>{c.name}</button>)}</div>}
          {ov.expiring_soon.length > 0 && <div className="rounded-xl bg-amber-soft p-4 text-sm text-amber"><b>{t("Ending within 14 days")}:</b> {ov.expiring_soon.map((c: any) => <button key={c.id} className="ms-2 underline" onClick={() => router.push(`/admin/companies/${c.id}`)}>{c.name} ({date(c.ends)})</button>)}</div>}
        </div>
      )}
      <input className="input mb-4 max-w-sm" placeholder={`🔍 ${t("Search companies")}`} value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="panel">
        <Table rows={rows} empty={t("No companies yet.")} onRow={(c: any) => router.push(`/admin/companies/${c.id}`)} cols={[
          { h: t("Company"), c: (c: any) => <div><div className="font-medium">{c.name}</div><div className="text-xs text-slate">{c.industry ?? ""}</div></div> },
          { h: t("Owner"), c: (c: any) => <div><div>{c.owner_name ?? "—"}</div><div className="text-xs text-slate" dir="ltr">{c.owner_email}</div></div> },
          { h: t("Users"), c: (c: any) => c.stats.users, end: true },
          { h: t("Products"), c: (c: any) => num(c.stats.products), end: true },
          { h: t("Customers"), c: (c: any) => num(c.stats.customers), end: true },
          { h: t("Total sales"), c: (c: any) => money(c.stats.revenue, c.currency), end: true },
          { h: t("Subscription"), c: (c: any) => c.subscription_ends_at ? <span className={c.subscription_ends_at < new Date().toISOString().slice(0, 10) ? "text-rust" : ""}>{date(c.subscription_ends_at)}</span> : "—" },
          { h: t("Status"), c: (c: any) => <Status value={c.is_active ? "active" : "suspended"} /> },
        ]} />
      </div>

      <Modal title={t("New company")} open={open} onClose={() => setOpen(false)} onSave={save} saveLabel={t("Create company")}>
        <ErrorNote error={error} />
        <h3 className="mb-2 text-sm font-semibold">{t("Company info")}</h3>
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2"><Field label={`${t("Company name")} *`}><input className="input" value={f.v.name} onChange={f.set("name")} /></Field></div>
          <Field label={t("Business type")}><input className="input" placeholder={t("e.g. supermarket, pharmacy")} value={f.v.industry} onChange={f.set("industry")} /></Field>
          <Field label={t("Currency")}><select className="input" value={f.v.currency} onChange={f.set("currency")}>{CURRENCIES.map((c) => <option key={c}>{c}</option>)}</select></Field>
          <Field label={t("Phone")}><input className="input" dir="ltr" value={f.v.phone} onChange={f.set("phone")} /></Field>
          <Field label={t("City / address")}><input className="input" value={f.v.address} onChange={f.set("address")} /></Field>
          <Field label={t("VAT rate %")}><input className="input" type="number" value={f.v.tax_rate} onChange={f.set("tax_rate")} /></Field>
          <Field label={t("Plan")}><select className="input" value={f.v.plan_id} onChange={f.set("plan_id")}><option value={0}>{t("No plan (unlimited)")}</option>{plans?.filter((p) => p.is_active).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
          <div className="col-span-2"><Field label={t("Subscription until (empty = no end)")}><input className="input" type="date" value={f.v.subscription_ends_at} onChange={f.set("subscription_ends_at")} /></Field></div>
        </div>
        <h3 className="mb-2 mt-5 text-sm font-semibold">{t("Owner account (they log in with this)")}</h3>
        <div className="grid grid-cols-2 gap-3">
          <Field label={`${t("Full name")} *`}><input className="input" value={f.v.owner_name} onChange={f.set("owner_name")} /></Field>
          <Field label={`${t("Email")} *`}><input className="input" type="email" dir="ltr" value={f.v.owner_email} onChange={f.set("owner_email")} /></Field>
          <div className="col-span-2"><Field label={`${t("Password")} *`}>
            <div className="flex gap-2"><input className="input" dir="ltr" value={f.v.owner_password} onChange={f.set("owner_password")} /><button type="button" className="btn-ghost whitespace-nowrap" onClick={genPassword}>{t("Generate")}</button></div>
          </Field></div>
        </div>
        <p className="mt-3 text-xs text-slate">{t("Send the owner their email and password. They can change the password after logging in.")}</p>
      </Modal>
    </>
  );
}
