"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useT } from "@/lib/i18n";
import { Badge, ErrorNote, Field, Modal, PageTitle, Table, toast } from "@/components/ui";

/** Platform admins and what each may do (owners manage admins; only admins with the right can enter companies). */
export default function PlatformAdmins() {
  const { t } = useT();
  const list = useApi<any[]>("/api/platform/admins", [], { platform: true });
  const [form, setForm] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    setError(null);
    try {
      await api(form.id ? `/api/platform/admins/${form.id}` : "/api/platform/admins", { method: form.id ? "PATCH" : "POST", json: { ...form, password: form.password || null }, platform: true });
      setForm(null); toast("Saved"); list.reload();
    } catch (e: any) { setError(e.message); }
  };
  return (
    <>
      <PageTitle title={t("Platform admins")} help={t("Platform admins help")} actions={<button className="btn-primary" onClick={() => { setError(null); setForm({ email: "", full_name: "", password: "", is_owner: false, can_impersonate: false, is_active: true }); }}>+ {t("New admin")}</button>} />
      <div className="panel"><Table rows={list.data} onRow={(a: any) => { setError(null); setForm({ ...a, password: "" }); }} cols={[
        { h: t("Name"), c: (a: any) => <span className="font-medium">{a.full_name}</span> }, { h: t("Email"), c: (a: any) => <span dir="ltr">{a.email}</span> },
        { h: t("Rights"), c: (a: any) => <div className="flex flex-wrap gap-1">{a.is_owner && <Badge tone="info">{t("Owner")}</Badge>}{a.can_impersonate && <Badge tone="warn">{t("Can enter companies")}</Badge>}</div> },
        { h: "2FA", c: (a: any) => <Badge tone={a.totp_enabled ? "good" : "bad"}>{a.totp_enabled ? t("On") : t("Off")}</Badge> },
        { h: t("Status"), c: (a: any) => <Badge tone={a.is_active ? "good" : "neutral"}>{a.is_active ? t("Active") : t("Stopped")}</Badge> },
      ]} /></div>
      <Modal title={form?.id ? form.full_name : t("New admin")} open={!!form} onClose={() => setForm(null)} onSave={save}>
        {form && <>
          <ErrorNote error={error} />
          <div className="grid gap-3">
            <Field label={t("Name")}><input className="input" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></Field>
            <Field label={t("Email")}><input className="input" dir="ltr" disabled={!!form.id} value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
            <Field label={form.id ? t("New password (leave empty to keep)") : t("Password (8+ characters)")}><input className="input" type="password" dir="ltr" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></Field>
            {(["is_owner", "can_impersonate", "is_active"] as const).map((k) => <label key={k} className="flex items-center gap-2 text-sm">
              <input type="checkbox" className="accent-signal" checked={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.checked })} />
              {t(k === "is_owner" ? "Owner (manages platform admins)" : k === "can_impersonate" ? "Can enter companies for support (always recorded)" : "Active")}</label>)}
          </div>
        </>}
      </Modal>
    </>
  );
}
