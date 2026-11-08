"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, getPlatformToken, logout } from "@/lib/api";
import { LangSwitch, useT } from "@/lib/i18n";
import { ErrorNote, Field, Modal, toast } from "@/components/ui";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const path = usePathname();
  const { t } = useT();
  const [me, setMe] = useState<any>(null);
  const [pwOpen, setPwOpen] = useState(false);
  const [pw, setPw] = useState({ current_password: "", new_password: "" });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!getPlatformToken()) { router.replace("/login"); return; }
    api("/api/platform/me", { platform: true }).then(setMe).catch(() => router.replace("/login"));
  }, [router]);

  const changePassword = async () => {
    setError(null);
    try { await api("/api/platform/change-password", { method: "POST", json: pw, platform: true }); setPwOpen(false); setPw({ current_password: "", new_password: "" }); toast("Password changed"); }
    catch (e: any) { setError(e.message); }
  };

  if (!me) return <div className="p-8 text-sm text-slate">{t("Loading…")}</div>;
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-line bg-ink text-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-3 px-4 py-3 sm:px-8">
          <Link href="/admin" className="flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-signal font-bold">B</span>
            <span><span className="block text-sm font-semibold">{t("Platform admin")}</span><span className="block text-xs text-white/60">{t("AI Business OS")}</span></span>
          </Link>
          <nav className="flex flex-wrap gap-1 text-sm">
            {[["/admin", "Companies"], ["/admin/health", "Health"], ["/admin/billing", "Billing"], ["/admin/plans", "Plans"], ["/admin/system", "System"], ["/admin/outbox", "Emails"], ["/admin/security", "Security"], ["/admin/admins", "Admins"], ["/admin/backups", "Backups"]].map(([href, label]) => (
              <Link key={href} href={href} className={`rounded-lg px-3 py-1.5 ${path === href ? "bg-white/15 font-medium" : "text-white/70 hover:bg-white/10"}`}>{t(label)}</Link>
            ))}
          </nav>
          <div className="ms-auto flex flex-wrap items-center gap-2 text-sm">
            <span className="hidden text-white/70 sm:inline" dir="ltr">{me.email}</span>
            <button className="rounded-lg px-3 py-1.5 hover:bg-white/10" onClick={() => { setError(null); setPwOpen(true); }}>{t("Change password")}</button>
            <LangSwitch className="!border-white/20 !bg-transparent !text-white hover:!bg-white/10" />
            <button className="rounded-lg px-3 py-1.5 hover:bg-white/10" onClick={() => { logout(); router.push("/login"); }}>{t("Sign out")}</button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6 sm:px-8">{children}</main>
      <Modal title={t("Change password")} open={pwOpen} onClose={() => setPwOpen(false)} onSave={changePassword}>
        <ErrorNote error={error} />
        <div className="grid gap-3">
          <Field label={t("Current password")}><input className="input" type="password" dir="ltr" value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} /></Field>
          <Field label={t("New password")}><input className="input" type="password" dir="ltr" value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} /></Field>
        </div>
      </Modal>
    </div>
  );
}
