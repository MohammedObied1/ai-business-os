"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { API_URL } from "@/lib/api";
import { LangSwitch, useT } from "@/lib/i18n";
import { ErrorNote, Field, toast } from "@/components/ui";

/** Opened from the reset email: /reset-password?token=… */
export default function ResetPassword() {
  const { t } = useT();
  const router = useRouter();
  const [token, setToken] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { setToken(new URLSearchParams(window.location.search).get("token") ?? ""); }, []);

  const save = async () => {
    setError(null);
    if (pw !== pw2) { setError(t("The two passwords don't match")); return; }
    const r = await fetch(`${API_URL}/api/auth/reset-password`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token, new_password: pw }) });
    if (!r.ok) { setError((await r.json()).detail); return; }
    toast("Password changed");
    router.push("/login");
  };

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex justify-end"><LangSwitch /></div>
        <form className="panel space-y-3 p-5" onSubmit={(e) => { e.preventDefault(); save(); }}>
          <h1 className="text-lg font-semibold">{t("Choose a new password")}</h1>
          <ErrorNote error={error} />
          <Field label={t("New password")}><input className="input" type="password" dir="ltr" value={pw} onChange={(e) => setPw(e.target.value)} /></Field>
          <Field label={t("Repeat new password")}><input className="input" type="password" dir="ltr" value={pw2} onChange={(e) => setPw2(e.target.value)} /></Field>
          <button className="btn-primary w-full" disabled={!token}>{t("Save")}</button>
        </form>
      </div>
    </main>
  );
}
