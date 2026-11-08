"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { getPlatformToken, logoUrl, setToken } from "@/lib/api";
import { LangSwitch, useT } from "@/lib/i18n";
import { NotificationBell } from "./NotificationBell";

// Outline icons, 24x24 viewBox
const ICONS: Record<string, string> = {
  home: "M3 11l9-7 9 7v9a1 1 0 01-1 1h-5v-6H9v6H4a1 1 0 01-1-1z",
  chart: "M4 20V10M10 20V4M16 20v-7M22 20H2",
  cart: "M3 4h2l2.4 11h11.2L21 7H6.2M9 20a1 1 0 100-2 1 1 0 000 2zm9 0a1 1 0 100-2 1 1 0 000 2z",
  users: "M16 19v-1a4 4 0 00-4-4H6a4 4 0 00-4 4v1M9 10a3 3 0 100-6 3 3 0 000 6zm13 9v-1a4 4 0 00-3-3.9M16 4.1a3 3 0 010 5.8",
  box: "M21 8l-9-5-9 5 9 5 9-5zM3 8v8l9 5 9-5V8M12 13v8",
  truck: "M1 5h13v11H1zM14 9h4l4 4v3h-8M5.5 19a1.5 1.5 0 100-3 1.5 1.5 0 000 3zm12 0a1.5 1.5 0 100-3 1.5 1.5 0 000 3z",
  wallet: "M3 7h18v12H3zM3 7l2-3h12l2 3M16 13h2",
  bell: "M18 16v-5a6 6 0 10-12 0v5l-2 2h16zM10 21h4",
  file: "M14 3H6a1 1 0 00-1 1v16a1 1 0 001 1h12a1 1 0 001-1V8zM14 3v5h5M8 13h8M8 17h5",
  bolt: "M13 2L4 14h7l-1 8 9-12h-7z",
  team: "M12 12a4 4 0 100-8 4 4 0 000 8zM4 21v-1a6 6 0 0116 0v1",
  sheet: "M4 3h16v18H4zM4 9h16M4 15h16M10 3v18",
  report: "M9 17v-5M13 17V8M17 17v-3M5 3h14a1 1 0 011 1v16a1 1 0 01-1 1H5a1 1 0 01-1-1V4a1 1 0 011-1z",
  register: "M4 10h16v10H4zM7 10V5h10v5M8 14h2M14 14h2M8 17h8",
  bank: "M3 10l9-6 9 6M5 10v8M9 10v8M15 10v8M19 10v8M3 21h18",
  cheque: "M3 7h18v10H3zM6 13h6M15 13h3M6 10h3",
  briefcase: "M4 8h16v11H4zM9 8V5h6v3M4 13h16",
  shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z",
  check: "M9 11l3 3 8-8M20 12v7a1 1 0 01-1 1H5a1 1 0 01-1-1V5a1 1 0 011-1h11",
  route: "M6 19a2 2 0 100-4 2 2 0 000 4zM18 9a2 2 0 100-4 2 2 0 000 4zM6 15V9a4 4 0 014-4h2M18 9v6a4 4 0 01-4 4h-2",
  pin: "M12 21s-7-6.2-7-11a7 7 0 1114 0c0 4.8-7 11-7 11zM12 12a2 2 0 100-4 2 2 0 000 4z",
  tag: "M3 12V4a1 1 0 011-1h8l9 9-9 9zM8 8h.01",
  clipboard: "M9 4h6v3H9zM9 5H6a1 1 0 00-1 1v14a1 1 0 001 1h12a1 1 0 001-1V6a1 1 0 00-1-1h-3M9 13l2 2 4-4",
  factory: "M3 21V9l6 4V9l6 4V5h4a1 1 0 011 1v15zM7 17h2M13 17h2",
  barcode: "M4 5v14M7 5v14M11 5v14M14 5v14M18 5v14M20 5v14",
  book: "M4 5a2 2 0 012-2h13v16H6a2 2 0 00-2 2zM4 19a2 2 0 002 2h13M8 7h7",
  lock: "M6 11h12v10H6zM8 11V7a4 4 0 118 0v4",
  plug: "M9 3v6M15 3v6M6 9h12v3a6 6 0 01-12 0zM12 18v3",
  gear: "M12 15a3 3 0 100-6 3 3 0 000 6zM19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-2.9 1.2V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-2.9-1.2l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00-1.2-2.9H3a2 2 0 110-4h.1a1.7 1.7 0 001.2-2.9l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 002.9-1.2V3a2 2 0 114 0v.1a1.7 1.7 0 002.9 1.2l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 001.2 2.9H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z",
};

// [href, label, icon, permission needed (empty = everyone)]
type NavItem = [string, string, string, string];
const NAV: { group: string; items: NavItem[] }[] = [
  { group: "Overview", items: [["/command-center", "Home", "home", ""], ["/dashboard", "Dashboard", "chart", ""], ["/reports", "Reports", "report", "reports:read"],
    ["/approvals", "Approval center", "check", ""]] },
  { group: "Sales", items: [["/pos", "Point of sale", "register", "pos:use"], ["/sales", "Sales & invoices", "cart", "sales:read"], ["/customers", "Customers", "users", "customers:read"],
    ["/deliveries", "Deliveries", "route", ""], ["/field", "Field sales", "pin", "customers:read"], ["/pricing", "Prices & offers", "tag", "sales:read"]] },
  { group: "Stock & purchasing", items: [["/inventory", "Inventory", "box", "inventory:read"], ["/stock-counts", "Stock counts", "clipboard", "inventory:write"],
    ["/transfers", "Warehouse transfers", "truck", "inventory.view"], ["/stock-states", "Damaged & expired", "box", "inventory.view"],
    ["/manufacturing", "Manufacturing", "factory", "inventory:read"], ["/labels", "Barcode labels", "barcode", "inventory:read"], ["/purchasing", "Purchasing", "truck", "purchasing:read"]] },
  { group: "Money", items: [["/accounts", "Cash & banks", "bank", "accounts:read"], ["/cheques", "Cheques", "cheque", "accounts:read"], ["/finance", "Expenses", "wallet", "finance:read"],
    ["/accounting", "Accounting", "book", "accounting:read"]] },
  { group: "People", items: [["/hr", "Employees & salaries", "briefcase", "hr:read"]] },
  { group: "More", items: [["/alerts", "Alerts & tasks", "bell", ""], ["/import", "Import & export", "sheet", ""], ["/documents", "Company files", "file", ""], ["/automation", "Automatic rules", "bolt", ""]] },
  { group: "Settings", items: [["/settings", "Team", "team", ""], ["/company", "Company settings", "gear", ""], ["/security", "Security", "lock", ""],
    ["/approval-rules", "Approval rules", "check", "approvals.rules"], ["/integrations", "Integrations", "plug", "settings:write"], ["/audit", "Activity log", "shield", "audit:read"]] },
];

export function Icon({ name, className = "" }: { name: string; className?: string }) {
  return <svg className={className} width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d={ICONS[name]} /></svg>;
}

export default function Sidebar({ user, company, open, onClose }: { user: any; company: any; open: boolean; onClose: () => void }) {
  const path = usePathname();
  const router = useRouter();
  const { t, tx } = useT();
  const perms: string[] = user?.effective_permissions?.length ? user.effective_permissions : user?.role?.permissions ?? [];
  const can = (p: string) => perms.includes("*") || perms.includes(p);
  return (
    <>
      {open && <div className="fixed inset-0 z-30 bg-ink/30 lg:hidden" onClick={onClose} />}
      <aside className={`print:hidden fixed inset-y-0 start-0 z-40 flex w-64 shrink-0 flex-col border-e border-line bg-white lg:sticky lg:top-0 lg:h-screen ${open ? "" : "max-lg:hidden"}`}>
        <div className="flex items-center gap-3 border-b border-line px-4 py-4">
          {company?.logo_path
            ? <img src={logoUrl(company.id, company.logo_path)} alt="" className="h-9 w-9 rounded-lg border border-line object-contain" />
            : <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-signal text-sm font-bold text-white">{(company?.name ?? "?").slice(0, 1)}</div>}
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-semibold">{company?.name ?? "…"}</div>
            <div className="text-xs text-slate">{t("AI Business OS")}</div>
          </div>
          <NotificationBell onNavigate={onClose} />
        </div>
        <nav className="flex-1 overflow-y-auto px-3 py-3">
          {NAV.map(({ group, items }) => ({ group, items: items.filter(([, , , perm]) => !perm || can(perm)) })).filter((g) => g.items.length).map(({ group, items }) => (
            <div key={group} className="mb-4">
              <div className="mb-1 px-3 text-xs font-medium text-slate/80">{t(group)}</div>
              {items.map(([href, label, icon]) => {
                const active = path.startsWith(href);
                return (
                  <Link key={href} href={href} onClick={onClose} className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm ${active ? "bg-signal-soft font-medium text-signal" : "text-ink/80 hover:bg-paper hover:text-ink"}`}>
                    <Icon name={icon} />{t(label)}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>
        <div className="space-y-3 border-t border-line px-4 py-3">
          <div className="text-sm">
            <div className="font-medium text-ink">{user?.full_name}</div>
            <div className="text-xs text-slate">{tx(user?.role?.name)}</div>
          </div>
          <div className="flex gap-2">
            <LangSwitch className="flex-1 !px-2" />
            <button className="btn-ghost flex-1 !px-2" onClick={() => { setToken(null); try { localStorage.removeItem("session:cache"); } catch {} router.push(getPlatformToken() ? "/admin" : "/login"); }}>{t("Sign out")}</button>
          </div>
        </div>
      </aside>
    </>
  );
}
