"use client";
import { useEffect, useRef, useState } from "react";
import { api, logoUrl, upload } from "@/lib/api";
import { CURRENCIES } from "@/lib/constants";
import { useApi } from "@/lib/hooks";
import { date } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { CompanyExtras } from "@/components/CompanyExtras";
import { ErrorNote, Field, Modal, PageTitle, Status, Table, toast, useForm } from "@/components/ui";

export default function CompanySettings() {
  const { t } = useT();
  const { company, reloadCompany, can } = useSession();
  const [form, setForm] = useState<any>(null);
  const [pw, setPw] = useState({ current_password: "", new_password: "", confirm: "" });
  const [error, setError] = useState<string | null>(null);
  const [pwError, setPwError] = useState<string | null>(null);
  const branches = useApi<any[]>("/api/branches");
  const [branchOpen, setBranchOpen] = useState(false);
  const [editingBranch, setEditingBranch] = useState<any>(null);
  const b = useForm({ name: "", address: "", phone: "", is_active: true });
  const logoInput = useRef<HTMLInputElement>(null);
  const editable = can("settings:write");

  useEffect(() => {
    if (company) setForm({ name: company.name, industry: company.industry ?? "", currency: company.currency, phone: company.phone ?? "", email: company.email ?? "",
      address: company.address ?? "", tax_number: company.tax_number ?? "", tax_rate: company.tax_rate ?? 0, prices_include_tax: !!company.prices_include_tax,
      invoice_footer: company.invoice_footer ?? "" });
  }, [company]);
  if (!form) return <div className="text-sm text-slate">{t("Loading…")}</div>;
  const set = (k: string) => (e: any) => setForm({ ...form, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.type === "number" ? +e.target.value : e.target.value });
  const daysLeft = company?.subscription_ends_at ? Math.ceil((new Date(company.subscription_ends_at).getTime() - Date.now()) / 86400000) : null;

  const save = async () => {
    setError(null);
    try { await api("/api/auth/company", { method: "PATCH", json: form }); reloadCompany(); toast("Saved"); } catch (e: any) { setError(e.message); }
  };
  const changePw = async () => {
    setPwError(null);
    if (pw.new_password !== pw.confirm) { setPwError(t("The two passwords don't match")); return; }
    try { await api("/api/auth/change-password", { method: "POST", json: { current_password: pw.current_password, new_password: pw.new_password } }); setPw({ current_password: "", new_password: "", confirm: "" }); toast("Password changed"); }
    catch (e: any) { setPwError(e.message); }
  };
  const onLogo = async (f: File | undefined) => {
    if (!f) return;
    try { await upload("/api/company/logo", f); reloadCompany(); toast("Saved"); } catch (e: any) { toast(e.message, "bad"); }
  };
  const removeLogo = async () => { try { await api("/api/company/logo", { method: "DELETE" }); reloadCompany(); } catch (e: any) { toast(e.message, "bad"); } };
  const saveBranch = async () => {
    setError(null);
    try { await api(editingBranch ? `/api/branches/${editingBranch.id}` : "/api/branches", { method: editingBranch ? "PATCH" : "POST", json: b.v }); setBranchOpen(false); toast("Saved"); branches.reload(); }
    catch (e: any) { setError(e.message); }
  };

  return (
    <>
      <PageTitle title={t("Company settings")} help={t("Company settings help")} />
      {daysLeft !== null && (
        <div className={`mb-6 rounded-xl p-4 text-sm ${daysLeft < 0 ? "bg-rust-soft text-rust" : daysLeft <= 14 ? "bg-amber-soft text-amber" : "bg-moss-soft text-moss"}`}>
          {t("Subscription until")} <b>{date(company.subscription_ends_at)}</b> {daysLeft >= 0 ? `(${t("{n} days left", { n: daysLeft })})` : ""}
        </div>
      )}
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <section className="panel p-5">
            <h2 className="mb-4 text-base font-semibold">{t("Company info")}</h2>
            <ErrorNote error={error && !branchOpen ? error : null} />
            <div className="mb-5 flex items-center gap-4">
              {company.logo_path ? <img src={logoUrl(company.id, company.logo_path)} alt="" className="h-20 w-20 rounded-xl border border-line object-contain" />
                : <div className="flex h-20 w-20 items-center justify-center rounded-xl border-2 border-dashed border-line text-xs text-slate">{t("No logo")}</div>}
              {editable && <div className="flex flex-col gap-2">
                <input ref={logoInput} type="file" accept="image/png,image/jpeg,image/webp,image/svg+xml" className="hidden" onChange={(e) => onLogo(e.target.files?.[0])} />
                <button className="btn-ghost" onClick={() => logoInput.current?.click()}>{t("Upload logo")}</button>
                {company.logo_path && <button className="link-danger" onClick={removeLogo}>{t("Remove logo")}</button>}
              </div>}
            </div>
            <fieldset disabled={!editable} className="grid gap-3 sm:grid-cols-2">
              <Field label={t("Company name")}><input className="input" value={form.name} onChange={set("name")} /></Field>
              <Field label={t("Business type")}><input className="input" value={form.industry} onChange={set("industry")} /></Field>
              <Field label={t("Phone")}><input className="input" dir="ltr" value={form.phone} onChange={set("phone")} /></Field>
              <Field label={t("Email")}><input className="input" dir="ltr" value={form.email} onChange={set("email")} /></Field>
              <div className="sm:col-span-2"><Field label={t("City / address")}><input className="input" value={form.address} onChange={set("address")} /></Field></div>
              <div className="sm:col-span-2"><Field label={t("Text at the bottom of invoices")}><input className="input" placeholder={t("Thank you for your business.")} value={form.invoice_footer} onChange={set("invoice_footer")} /></Field></div>
            </fieldset>
          </section>
          <section className="panel p-5">
            <h2 className="mb-4 text-base font-semibold">{t("Tax & currency")}</h2>
            <fieldset disabled={!editable} className="grid gap-3 sm:grid-cols-2">
              <Field label={t("Currency")}><select className="input" value={form.currency} onChange={set("currency")}>{CURRENCIES.map((x) => <option key={x}>{x}</option>)}</select></Field>
              <Field label={t("Tax number")}><input className="input" dir="ltr" value={form.tax_number} onChange={set("tax_number")} /></Field>
              <Field label={t("VAT rate %")}><input className="input" type="number" step="0.5" value={form.tax_rate} onChange={set("tax_rate")} /></Field>
              <label className="flex items-end gap-2 pb-2 text-sm"><input type="checkbox" className="h-4 w-4 accent-signal" checked={form.prices_include_tax} onChange={set("prices_include_tax")} />{t("My sale prices already include VAT")}</label>
            </fieldset>
            <p className="mt-3 text-xs text-slate">{t("VAT help")}</p>
            {editable && <div className="mt-4 flex justify-end"><button className="btn-primary" onClick={save}>{t("Save changes")}</button></div>}
          </section>
          <CompanyExtras />
          <section className="panel">
            <div className="flex items-center justify-between p-4">
              <h2 className="text-base font-semibold">{t("Branches")}</h2>
              {editable && <button className="btn-ghost" onClick={() => { setError(null); setEditingBranch(null); b.setV({ name: "", address: "", phone: "", is_active: true }); setBranchOpen(true); }}>+ {t("New branch")}</button>}
            </div>
            <Table rows={branches.data} empty={t("One location only. Add branches if you have more than one shop.")} onRow={editable ? (x: any) => { setError(null); setEditingBranch(x); b.setV({ name: x.name, address: x.address ?? "", phone: x.phone ?? "", is_active: x.is_active }); setBranchOpen(true); } : undefined} cols={[
              { h: t("Name"), c: (x: any) => <span className="font-medium">{x.name}</span> }, { h: t("City / address"), c: (x: any) => x.address ?? "—" },
              { h: t("Phone"), c: (x: any) => <span dir="ltr">{x.phone ?? "—"}</span> }, { h: t("Status"), c: (x: any) => <Status value={x.is_active ? "active" : "inactive"} /> },
            ]} />
          </section>
        </div>
        <section className="panel h-fit p-5">
          <h2 className="mb-4 text-base font-semibold">{t("Change my password")}</h2>
          <ErrorNote error={pwError} />
          <div className="grid gap-3">
            <Field label={t("Current password")}><input className="input" type="password" dir="ltr" value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} /></Field>
            <Field label={t("New password")}><input className="input" type="password" dir="ltr" value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} /></Field>
            <Field label={t("Repeat new password")}><input className="input" type="password" dir="ltr" value={pw.confirm} onChange={(e) => setPw({ ...pw, confirm: e.target.value })} /></Field>
          </div>
          <div className="mt-4 flex justify-end"><button className="btn-primary" onClick={changePw}>{t("Change password")}</button></div>
        </section>
      </div>
      <Modal title={editingBranch ? t("Edit branch") : t("New branch")} open={branchOpen} onClose={() => setBranchOpen(false)} onSave={saveBranch}>
        <ErrorNote error={error} />
        <div className="grid gap-3">
          <Field label={t("Name")}><input className="input" value={b.v.name} onChange={b.set("name")} /></Field>
          <Field label={t("City / address")}><input className="input" value={b.v.address} onChange={b.set("address")} /></Field>
          <Field label={t("Phone")}><input className="input" dir="ltr" value={b.v.phone} onChange={b.set("phone")} /></Field>
          {editingBranch && <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="h-4 w-4 accent-signal" checked={b.v.is_active} onChange={b.set("is_active")} />{t("Active")}</label>}
        </div>
      </Modal>
    </>
  );
}
