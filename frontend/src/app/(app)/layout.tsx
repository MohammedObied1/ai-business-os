"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import Sidebar from "@/components/Sidebar";
import { ApiError, api, getToken, setToken } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { SessionContext } from "@/lib/session";
import { setFormatCurrency } from "@/lib/format";
import { applyBrand } from "@/lib/brand";
import { usePathname } from "next/navigation";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { t } = useT();
  const [user, setUser] = useState<any>(null);
  const [company, setCompany] = useState<any>(null);
  const [menu, setMenu] = useState(false);
  const path = usePathname();
  const loadCompany = () => api("/api/auth/company").then(setCompany).catch(() => {});
  useEffect(() => {
    if (!getToken()) { router.replace("/login"); return; }
    Promise.all([api("/api/auth/me"), api("/api/auth/company")]).then(([u, c]) => {
      setUser(u); setCompany(c);
      try { localStorage.setItem("session:cache", JSON.stringify({ u, c })); } catch {}
    }).catch((e) => {
      // no internet: reuse the last session so the cashier screen still works offline
      const cached = (() => { try { return JSON.parse(localStorage.getItem("session:cache") ?? "null"); } catch { return null; } })();
      if (!(e instanceof ApiError) && cached) { setUser(cached.u); setCompany(cached.c); } else router.replace("/login");
    });
  }, [router]);
  if (!user) return <div className="p-8 text-sm text-slate">{t("Loading…")}</div>;
  setFormatCurrency(company?.currency);
  applyBrand(company?.brand_color);
  // the company requires two-step verification and this user hasn't set it up yet
  if (user.must_setup_2fa && path !== "/security") { router.replace("/security"); return <div className="p-8 text-sm text-slate">{t("Loading…")}</div>; }

  // effective_permissions holds both the coarse ("sales:read") and granular ("sales.discount") names the role grants
  const perms: string[] = user.effective_permissions?.length ? user.effective_permissions : user.role?.permissions ?? [];
  const can = (p: string) => perms.includes("*") || perms.includes(p);
  const backToAdmin = () => { setToken(null); router.push("/admin"); };

  return (
    <SessionContext.Provider value={{ user, company, reloadCompany: loadCompany, can }}>
      <div className="flex min-h-screen">
        <Sidebar user={user} company={company} open={menu} onClose={() => setMenu(false)} />
        <div className="min-w-0 flex-1">
          {user.impersonated && (
            <div className="print:hidden flex flex-wrap items-center justify-center gap-3 bg-amber px-4 py-2 text-sm text-white">
              <span>{t("You are inside {c} as platform admin.", { c: company?.name ?? "" })}</span>
              <button className="rounded-md bg-white/20 px-3 py-1 font-medium hover:bg-white/30" onClick={backToAdmin}>{t("Back to admin panel")}</button>
            </div>
          )}
          <header className="print:hidden sticky top-0 z-20 flex items-center gap-3 border-b border-line bg-white px-4 py-3 lg:hidden">
            <button className="btn-ghost !px-3" onClick={() => setMenu(true)} aria-label={t("Menu")}>☰</button>
            <span className="font-semibold">{company?.name}</span>
          </header>
          <main className="px-4 py-6 sm:px-8 print:p-0"><div className="mx-auto max-w-6xl">{children}</div></main>
        </div>
      </div>
    </SessionContext.Provider>
  );
}
