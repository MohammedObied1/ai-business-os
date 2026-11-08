"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useApi, usePaged } from "@/lib/hooks";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { Badge, PageTitle, Tabs, toast } from "@/components/ui";

const TABS = ["inbox", "my preferences", "company rules"] as const;
const CHANNELS = ["in_app", "email", "whatsapp", "push"] as const;

export default function Notifications() {
  const { t } = useT();
  const { can } = useSession();
  const [tab, setTab] = useState<(typeof TABS)[number]>("inbox");
  const [unreadOnly, setUnreadOnly] = useState(false);
  const inbox = usePaged<any>(tab === "inbox" ? `/api/notifications?unread=${unreadOnly}` : null, [tab, unreadOnly], 30);
  const prefs = useApi<any[]>(tab === "my preferences" ? "/api/notifications/preferences" : null, [tab]);
  const rules = useApi<any[]>(tab === "company rules" ? "/api/notifications/rules" : null, [tab]);
  const [p, setP] = useState<any[] | null>(null);
  const [r, setR] = useState<any[] | null>(null);
  const [browserPerm, setBrowserPerm] = useState<string>("default");
  useEffect(() => { if (prefs.data) setP(prefs.data); }, [prefs.data]);
  useEffect(() => { if (rules.data) setR(rules.data); }, [rules.data]);
  useEffect(() => { if (typeof Notification !== "undefined") setBrowserPerm(Notification.permission); }, []);

  const open = async (n: any) => { if (!n.read) { await api(`/api/notifications/${n.id}/read`, { method: "POST" }).catch(() => {}); inbox.reload(); } };
  const readAll = async () => { await api("/api/notifications/read-all", { method: "POST" }); inbox.reload(); };
  const savePrefs = async () => { try { await api("/api/notifications/preferences", { method: "PUT", json: p }); toast("Saved"); } catch (e: any) { toast(e.message, "bad"); } };
  const saveRules = async () => { try { await api("/api/notifications/rules", { method: "PUT", json: r }); toast("Saved"); } catch (e: any) { toast(e.message, "bad"); } };
  const askBrowser = async () => { if (typeof Notification !== "undefined") setBrowserPerm(await Notification.requestPermission()); };
  const tone = (s: string) => (s === "critical" ? "bad" : s === "warning" ? "warn" : "info") as any;

  return (
    <>
      <PageTitle title={t("Notifications")} help={t("Notifications help")} />
      <Tabs tabs={can("settings.manage") ? TABS : (["inbox", "my preferences"] as const)} value={tab} onChange={setTab} />

      {tab === "inbox" && <>
        <div className="mb-3 flex flex-wrap items-center gap-3 text-sm">
          <label className="flex items-center gap-2"><input type="checkbox" className="accent-signal" checked={unreadOnly} onChange={(e) => setUnreadOnly(e.target.checked)} />{t("Unread only")}</label>
          <button className="link" onClick={readAll}>{t("Mark all as read")}</button>
          {browserPerm !== "granted" && typeof window !== "undefined" && "Notification" in window &&
            <button className="btn-ghost ms-auto !py-1.5" onClick={askBrowser}>🔔 {t("Allow desktop notifications")}</button>}
        </div>
        <div className="panel divide-y divide-line">
          {inbox.rows?.length === 0 && <div className="p-8 text-center text-sm text-slate">{t("No notifications.")}</div>}
          {inbox.rows?.map((n) => {
            const body = <div className="flex items-start gap-3">
              {!n.read && <span className="mt-2 h-2 w-2 shrink-0 rounded-full bg-signal" />}
              <div className="min-w-0 flex-1">
                <div className={`text-sm ${n.read ? "text-slate" : "font-semibold"}`}>{n.title}</div>
                {n.message && <div className="mt-0.5 text-sm text-slate">{n.message}</div>}
                <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate">
                  <Badge tone={tone(n.severity)}>{t(`notify.${n.kind}`)}</Badge>
                  <span>{new Date(n.created_at + (String(n.created_at).endsWith("Z") ? "" : "Z")).toLocaleString()}</span>
                  {(n.channels ?? []).filter((c: string) => c !== "in_app").map((c: string) => <span key={c}>· {t(`channel.${c}`)}</span>)}
                </div>
              </div>
            </div>;
            return n.link ? <Link key={n.id} href={n.link} onClick={() => open(n)} className="block p-4 hover:bg-paper">{body}</Link>
              : <button key={n.id} onClick={() => open(n)} className="block w-full p-4 text-start hover:bg-paper">{body}</button>;
          })}
          {inbox.hasMore && <div className="p-3 text-center"><button className="link" onClick={inbox.loadMore}>{t("Show more")}</button></div>}
        </div>
      </>}

      {tab === "my preferences" && p && <>
        <div className="panel overflow-x-auto"><table className="w-full">
          <thead><tr><th className="th">{t("Notification")}</th>{CHANNELS.map((c) => <th key={c} className="th text-center">{t(`channel.${c}`)}</th>)}</tr></thead>
          <tbody>{p.map((row, i) => <tr key={row.kind}>
            <td className="td">{t(`notify.${row.kind}`)}</td>
            {CHANNELS.map((c) => <td key={c} className="td text-center"><input type="checkbox" className="h-4 w-4 accent-signal" checked={!!row[c]}
              onChange={(e) => setP(p.map((x, j) => (j === i ? { ...x, [c]: e.target.checked } : x)))} /></td>)}
          </tr>)}</tbody></table></div>
        <p className="mt-2 text-xs text-slate">{t("Email needs the email server set up; WhatsApp needs a connected WhatsApp integration and your phone number in your profile.")}</p>
        <div className="mt-3 flex justify-end"><button className="btn-primary" onClick={savePrefs}>{t("Save changes")}</button></div>
      </>}

      {tab === "company rules" && r && <>
        <div className="panel overflow-x-auto"><table className="w-full">
          <thead><tr><th className="th">{t("Notification")}</th><th className="th">{t("On")}</th><th className="th">{t("Who receives it (permission)")}</th>
            <th className="th text-center">{t("channel.email")}</th><th className="th text-center">{t("channel.whatsapp")}</th></tr></thead>
          <tbody>{r.map((row, i) => {
            const set = (patch: any) => setR(r.map((x, j) => (j === i ? { ...x, ...patch } : x)));
            return <tr key={row.kind}>
              <td className="td">{t(`notify.${row.kind}`)}</td>
              <td className="td"><input type="checkbox" className="h-4 w-4 accent-signal" checked={row.enabled} onChange={(e) => set({ enabled: e.target.checked })} /></td>
              <td className="td"><input className="input !py-1 text-xs" dir="ltr" placeholder={row.default_permission || t("only the person concerned")} value={row.permission ?? ""}
                onChange={(e) => set({ permission: e.target.value || null })} /></td>
              <td className="td text-center"><input type="checkbox" className="h-4 w-4 accent-signal" checked={row.email} onChange={(e) => set({ email: e.target.checked })} /></td>
              <td className="td text-center"><input type="checkbox" className="h-4 w-4 accent-signal" checked={row.whatsapp} onChange={(e) => set({ whatsapp: e.target.checked })} /></td>
            </tr>;
          })}</tbody></table></div>
        <p className="mt-2 text-xs text-slate">{t("Company rules are the defaults; each person can change their own channels in My preferences.")}</p>
        <div className="mt-3 flex justify-end"><button className="btn-primary" onClick={saveRules}>{t("Save changes")}</button></div>
      </>}
    </>
  );
}
