"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { API_URL, login, logoUrl } from "@/lib/api";
import { applyBrand } from "@/lib/brand";
import { LangSwitch, useT } from "@/lib/i18n";
import { ErrorNote, Field, toast } from "@/components/ui";

export default function LoginPage() {
  const router = useRouter();
  const { t, lang } = useT();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [needOtp, setNeedOtp] = useState(false);
  const [mode, setMode] = useState<"login" | "forgot">("login");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [brand, setBrand] = useState<any>(null);

  // white-label: on a company's own domain, show its name, logo and colour
  useEffect(() => {
    fetch(`${API_URL}/api/public/brand?host=${encodeURIComponent(window.location.hostname)}`).then((r) => r.json()).then((b) => {
      if (b) { setBrand(b); applyBrand(b.brand_color); }
    }).catch(() => {});
  }, []);

  const submit = async () => {
    if (!email || !password) return;
    setBusy(true); setError(null);
    try {
      const kind = await login(email, password, needOtp ? otp : undefined);
      router.push(kind === "platform" ? "/admin" : "/command-center");
    } catch (e: any) {
      if (e.message === "2FA code required") { setNeedOtp(true); setError(null); } else setError(e.message);
    } finally { setBusy(false); }
  };
  const forgot = async () => {
    if (!email) { setError(t("Write your email first")); return; }
    setBusy(true); setError(null);
    try {
      await fetch(`${API_URL}/api/auth/forgot-password`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, lang }) });
      toast(t("If this email has an account, a reset link was sent to it."));
      setMode("login");
    } finally { setBusy(false); }
  };

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex justify-end"><LangSwitch /></div>
        {brand?.logo ? <img src={logoUrl(brand.id, brand.logo_version)} alt="" className="mb-3 h-14 w-14 rounded-xl object-contain" />
          : <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-signal text-xl font-bold text-white">{(brand?.name ?? "B").slice(0, 1)}</div>}
        <h1 className="text-3xl font-semibold tracking-tight">{brand?.name ?? t("AI Business OS")}</h1>
        {!brand && <p className="mt-2 text-sm leading-relaxed text-slate">{t("Your business has a database. Our AI turns that data into decisions and actions.")}</p>}
        <form className="panel mt-8 space-y-3 p-5" onSubmit={(e) => { e.preventDefault(); if (mode === "login") submit(); else forgot(); }}>
          <h2 className="mb-1 text-lg font-semibold">{mode === "login" ? t("Sign in") : t("Forgot your password?")}</h2>
          <ErrorNote error={error} />
          <Field label={t("Email")}><input className="input" type="email" dir="ltr" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
          {mode === "login" && <>
            <Field label={t("Password")}><input className="input" type="password" dir="ltr" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
            {needOtp && <Field label={t("6-digit code from your authenticator app")}>
              <input className="input text-center text-lg tracking-[0.4em]" dir="ltr" inputMode="numeric" autoComplete="one-time-code" maxLength={6} autoFocus value={otp}
                onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))} />
            </Field>}
          </>}
          <button type="submit" className="btn-primary w-full" disabled={busy}>{busy ? "…" : mode === "login" ? t("Sign in") : t("Send reset link")}</button>
          <button type="button" className="link w-full" onClick={() => { setError(null); setMode(mode === "login" ? "forgot" : "login"); }}>
            {mode === "login" ? t("Forgot your password?") : t("Back to sign in")}
          </button>
          {mode === "login" && !brand && (
            <div className="rounded-lg bg-paper p-3 text-xs leading-relaxed text-slate">
              {t("Try it with the demo account:")}{" "}
              <button type="button" className="font-medium text-signal hover:underline" dir="ltr" onClick={() => { setEmail("owner@demo.com"); setPassword("demo1234"); }}>owner@demo.com</button>
            </div>
          )}
        </form>
        <p className="mt-4 text-center text-xs text-slate">{t("No account? Ask the platform admin to open a company for you.")}</p>
      </div>
    </main>
  );
}
