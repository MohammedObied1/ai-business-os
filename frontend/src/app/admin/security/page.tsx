"use client";
import QRCode from "qrcode";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, setPlatformToken } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useT } from "@/lib/i18n";
import { Badge, ErrorNote, Field, Modal, PageTitle, Table, toast } from "@/components/ui";

export default function AdminSecurity() {
  const { t } = useT();
  const router = useRouter();
  const data = useApi<any>("/api/platform/security", [], { platform: true });
  const [setup, setSetup] = useState<{ secret: string; uri: string } | null>(null);
  const [qr, setQr] = useState("");
  const [code, setCode] = useState("");
  const [off, setOff] = useState(false);
  const [pw, setPw] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [onlyFailed, setOnlyFailed] = useState(false);
  useEffect(() => { if (setup) QRCode.toDataURL(setup.uri, { width: 220, margin: 1 }).then(setQr); }, [setup]);

  const start = async () => { setError(null); setCode(""); try { setSetup(await api("/api/platform/2fa/setup", { method: "POST", platform: true })); } catch (e: any) { toast(e.message, "bad"); } };
  const enable = async () => {
    setError(null);
    try { await api("/api/platform/2fa/enable", { method: "POST", platform: true, json: { code } }); setSetup(null); toast("Two-step verification is on"); data.reload(); } catch (e: any) { setError(e.message); }
  };
  const disable = async () => {
    setError(null);
    try { await api("/api/platform/2fa/disable", { method: "POST", platform: true, json: { password: pw, code } }); setOff(false); toast("Two-step verification is off"); data.reload(); } catch (e: any) { setError(e.message); }
  };
  const logoutAll = async () => {
    if (!confirm(t("Sign out on every device, including this one?"))) return;
    await api("/api/platform/logout-all", { method: "POST", platform: true }); setPlatformToken(null); router.push("/login");
  };
  const reason = (r: string) => (t(`login.${r}`) === `login.${r}` ? r : t(`login.${r}`));
  const events = data.data?.events.filter((e: any) => !onlyFailed || !e.success) ?? null;

  return (
    <>
      <PageTitle title={t("Security")} help={t("Admin security help")} />
      <div className="grid gap-6 lg:grid-cols-2">
        <section className="panel p-5">
          <h2 className="text-base font-semibold">{t("Two-step verification")}</h2>
          <p className="mt-1 text-sm text-slate">{t("Strongly recommended for the platform admin: this account can open every company.")}</p>
          <div className="mt-4 flex items-center gap-3">
            <Badge tone={data.data?.totp_enabled ? "good" : "bad"}>{data.data?.totp_enabled ? t("On") : t("Off")}</Badge>
            {data.data && !data.data.totp_enabled && !setup && <button className="btn-primary" onClick={start}>{t("Turn on")}</button>}
            {data.data?.totp_enabled && <button className="btn-ghost !text-rust" onClick={() => { setError(null); setPw(""); setCode(""); setOff(true); }}>{t("Turn off")}</button>}
          </div>
          {setup && <div className="mt-5 space-y-3 rounded-xl bg-paper p-4">
            <p className="text-sm">{t("1. Scan this code with Google Authenticator or Microsoft Authenticator.")}</p>
            {qr && <img src={qr} alt="QR" className="mx-auto rounded-lg bg-white p-2" />}
            <p className="text-center text-xs text-slate">{t("Or type this key:")} <span dir="ltr" className="font-mono">{setup.secret}</span></p>
            <p className="text-sm">{t("2. Write the 6-digit code the app shows:")}</p>
            <ErrorNote error={error} />
            <div className="flex gap-2">
              <input className="input text-center text-lg tracking-[0.4em]" dir="ltr" inputMode="numeric" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
              <button className="btn-primary" disabled={code.length !== 6} onClick={enable}>{t("Confirm")}</button>
            </div>
          </div>}
        </section>
        <section className="panel p-5">
          <h2 className="text-base font-semibold">{t("Sessions")}</h2>
          <p className="mt-1 text-sm text-slate">{t("Lost a phone or used a shared computer? Sign out everywhere.")}</p>
          <button className="btn-ghost mt-4" onClick={logoutAll}>{t("Sign out on all devices")}</button>
        </section>
      </div>
      <div className="mb-3 mt-8 flex items-center justify-between">
        <h2 className="text-lg font-semibold">{t("Sign-ins on the platform")}</h2>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="accent-signal" checked={onlyFailed} onChange={(e) => setOnlyFailed(e.target.checked)} />{t("Failed only")}</label>
      </div>
      <div className="panel"><Table rows={events} cols={[
        { h: t("When"), c: (r: any) => new Date(r.at + (String(r.at).endsWith("Z") ? "" : "Z")).toLocaleString() },
        { h: t("Email"), c: (r: any) => <span dir="ltr">{r.email}</span> }, { h: t("Company"), c: (r: any) => r.company ?? "—" },
        { h: t("Result"), c: (r: any) => <Badge tone={r.success ? "good" : "bad"}>{reason(r.reason ?? (r.success ? "ok" : "failed"))}</Badge> },
        { h: "IP", c: (r: any) => <span dir="ltr" className="text-slate">{r.ip ?? "—"}</span> },
      ]} /></div>
      <Modal title={t("Turn off two-step verification")} open={off} onClose={() => setOff(false)} onSave={disable}>
        <ErrorNote error={error} />
        <div className="grid gap-3">
          <Field label={t("Password")}><input className="input" type="password" dir="ltr" value={pw} onChange={(e) => setPw(e.target.value)} /></Field>
          <Field label={t("6-digit code from your authenticator app")}><input className="input" dir="ltr" inputMode="numeric" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} /></Field>
        </div>
      </Modal>
    </>
  );
}
