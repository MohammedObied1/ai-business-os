"use client";
import QRCode from "qrcode";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, setToken } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { Badge, ErrorNote, Field, Modal, PageTitle, Table, toast } from "@/components/ui";

export default function Security() {
  const { t } = useT();
  const router = useRouter();
  const { user, company, can, reloadCompany } = useSession();
  const me = useApi<any>("/api/auth/me");
  const history = useApi<any[]>("/api/auth/login-history");
  const companyLogins = useApi<any[]>(can("users:write") ? "/api/security/logins" : null);
  const [setup, setSetup] = useState<{ secret: string; uri: string } | null>(null);
  const [qr, setQr] = useState("");
  const [code, setCode] = useState("");
  const [disableOpen, setDisableOpen] = useState(false);
  const [pw, setPw] = useState("");
  const [error, setError] = useState<string | null>(null);
  const enabled = me.data?.totp_enabled;

  useEffect(() => { if (setup) QRCode.toDataURL(setup.uri, { width: 220, margin: 1 }).then(setQr); }, [setup]);

  const start = async () => { setError(null); setCode(""); try { setSetup(await api("/api/auth/2fa/setup", { method: "POST" })); } catch (e: any) { toast(e.message, "bad"); } };
  const enable = async () => {
    setError(null);
    try { await api("/api/auth/2fa/enable", { method: "POST", json: { code } }); setSetup(null); toast("Two-step verification is on"); me.reload(); if (user.must_setup_2fa) router.replace("/command-center"); }
    catch (e: any) { setError(e.message); }
  };
  const disable = async () => {
    setError(null);
    try { await api("/api/auth/2fa/disable", { method: "POST", json: { password: pw, code } }); setDisableOpen(false); toast("Two-step verification is off"); me.reload(); }
    catch (e: any) { setError(e.message); }
  };
  const logoutAll = async () => {
    if (!confirm(t("Sign out on every device, including this one?"))) return;
    await api("/api/auth/logout-all", { method: "POST" });
    setToken(null);
    router.push("/login");
  };
  const toggleRequire = async () => {
    try { await api("/api/auth/company", { method: "PATCH", json: { require_2fa: !company.require_2fa } }); reloadCompany(); toast("Saved"); } catch (e: any) { toast(e.message, "bad"); }
  };
  const reason = (r: string) => t(`login.${r}`) === `login.${r}` ? r : t(`login.${r}`);
  const loginCols = (withEmail: boolean) => [
    { h: t("When"), c: (r: any) => new Date(r.at + (String(r.at).endsWith("Z") ? "" : "Z")).toLocaleString() },
    ...(withEmail ? [{ h: t("Email"), c: (r: any) => <span dir="ltr">{r.email}</span> }] : []),
    { h: t("Result"), c: (r: any) => <Badge tone={r.success ? "good" : "bad"}>{reason(r.reason ?? (r.success ? "ok" : "failed"))}</Badge> },
    { h: "IP", c: (r: any) => <span dir="ltr" className="text-slate">{r.ip ?? "—"}</span> },
    { h: t("Device"), c: (r: any) => <span className="text-xs text-slate">{(r.user_agent ?? "").slice(0, 60)}</span> },
  ];

  return (
    <>
      <PageTitle title={t("Security")} help={t("Security help")} />
      {user.must_setup_2fa && <div className="mb-6 rounded-xl bg-amber-soft p-4 text-sm text-amber">{t("Your company requires two-step verification. Set it up to continue.")}</div>}
      <div className="grid gap-6 lg:grid-cols-2">
        <section className="panel p-5">
          <h2 className="text-base font-semibold">{t("Two-step verification")}</h2>
          <p className="mt-1 text-sm text-slate">{t("2FA help")}</p>
          <div className="mt-4 flex items-center gap-3">
            <Badge tone={enabled ? "good" : "neutral"}>{enabled ? t("On") : t("Off")}</Badge>
            {!enabled && !setup && <button className="btn-primary" onClick={start}>{t("Turn on")}</button>}
            {enabled && <button className="btn-ghost !text-rust" onClick={() => { setError(null); setPw(""); setCode(""); setDisableOpen(true); }}>{t("Turn off")}</button>}
          </div>
          {setup && (
            <div className="mt-5 space-y-3 rounded-xl bg-paper p-4">
              <p className="text-sm">{t("1. Scan this code with Google Authenticator or Microsoft Authenticator.")}</p>
              {qr && <img src={qr} alt="QR" className="mx-auto rounded-lg bg-white p-2" />}
              <p className="text-center text-xs text-slate">{t("Or type this key:")} <span dir="ltr" className="font-mono">{setup.secret}</span></p>
              <p className="text-sm">{t("2. Write the 6-digit code the app shows:")}</p>
              <ErrorNote error={error} />
              <div className="flex gap-2">
                <input className="input text-center text-lg tracking-[0.4em]" dir="ltr" inputMode="numeric" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
                <button className="btn-primary" disabled={code.length !== 6} onClick={enable}>{t("Confirm")}</button>
              </div>
            </div>
          )}
        </section>
        <section className="panel p-5">
          <h2 className="text-base font-semibold">{t("Sessions")}</h2>
          <p className="mt-1 text-sm text-slate">{t("Lost a phone or used a shared computer? Sign out everywhere.")}</p>
          <button className="btn-ghost mt-4" onClick={logoutAll}>{t("Sign out on all devices")}</button>
          {can("settings:write") && company && (
            <div className="mt-6 border-t border-line pt-4">
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" className="h-4 w-4 accent-signal" checked={!!company.require_2fa} onChange={toggleRequire} />
                {t("Require two-step verification for everyone in the company")}
              </label>
            </div>
          )}
        </section>
      </div>
      <h2 className="mb-3 mt-8 text-lg font-semibold">{t("My recent sign-ins")}</h2>
      <div className="panel"><Table rows={history.data} cols={loginCols(false)} /></div>
      {can("users:write") && <>
        <h2 className="mb-3 mt-8 text-lg font-semibold">{t("Sign-ins in the company")}</h2>
        <div className="panel"><Table rows={companyLogins.data} cols={loginCols(true)} /></div>
      </>}
      <Modal title={t("Turn off two-step verification")} open={disableOpen} onClose={() => setDisableOpen(false)} onSave={disable}>
        <ErrorNote error={error} />
        <div className="grid gap-3">
          <Field label={t("Password")}><input className="input" type="password" dir="ltr" value={pw} onChange={(e) => setPw(e.target.value)} /></Field>
          <Field label={t("6-digit code from your authenticator app")}><input className="input" dir="ltr" inputMode="numeric" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} /></Field>
        </div>
      </Modal>
    </>
  );
}
