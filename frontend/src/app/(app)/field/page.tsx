"use client";
import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { money } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { WhatsAppButton } from "@/components/money";
import { Badge, Field, Modal, PageTitle, Table, Tabs, toast } from "@/components/ui";

const TABS = ["today", "visit log"] as const;
const OUTCOMES = ["visited", "ordered", "collected", "no_answer", "closed", "not_interested"];

function where(): Promise<{ lat: number; lng: number } | null> {
  return new Promise((res) => {
    if (!navigator.geolocation) return res(null);
    navigator.geolocation.getCurrentPosition((p) => res({ lat: p.coords.latitude, lng: p.coords.longitude }), () => res(null), { timeout: 8000, enableHighAccuracy: true });
  });
}

export default function FieldSales() {
  const { t } = useT();
  const { can } = useSession();
  const [tab, setTab] = useState<(typeof TABS)[number]>("today");
  const today = useApi<any[]>("/api/field/today");
  const log = useApi<any[]>(tab === "visit log" ? "/api/field/visits?days=14" : null, [tab]);
  const [visit, setVisit] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    try {
      const pos = can("field.track_location") ? await where() : null;
      const r = await api("/api/field/visits", { method: "POST", json: { customer_id: visit.c.id, outcome: visit.outcome, note: visit.note || null,
        lat: pos?.lat ?? null, lng: pos?.lng ?? null, amount_collected: visit.outcome === "collected" ? +visit.amount || 0 : 0 } });
      setVisit(null); toast(r.payment ? `Payment ${r.payment} recorded` : pos ? "Visit saved with location" : "Visit saved"); today.reload();
    } catch (e: any) { toast(e.message, "bad"); } finally { setBusy(false); }
  };
  const scheduled = today.data?.filter((c) => c.scheduled) ?? [];
  const visitedCount = scheduled.filter((c) => c.visited).length;
  const mapUrl = (c: any) => c.lat && c.lng ? `https://www.google.com/maps/dir/?api=1&destination=${c.lat},${c.lng}` : c.address ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(c.address)}` : null;

  return (
    <>
      <PageTitle title={t("Field sales")} help={t("Field sales help")} />
      <Tabs tabs={TABS} value={tab} onChange={setTab} />
      {tab === "today" && <>
        {today.data && <div className="mb-4 flex items-center gap-3 text-sm">
          <Badge tone="info">{t("Today's route")}: {visitedCount} / {scheduled.length}</Badge>
          {!today.data.length && <span className="text-slate">{t("No customers are assigned to you. The manager assigns them from the customer card.")}</span>}
        </div>}
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {today.data?.map((c) => (
            <div key={c.id} className={`panel p-4 ${c.visited ? "opacity-70" : ""} ${!c.scheduled ? "border-dashed" : ""}`}>
              <div className="flex items-start justify-between gap-2">
                <div>
                  <Link href={`/customers/${c.id}`} className="font-semibold hover:text-signal">{c.name}</Link>
                  <div className="text-xs text-slate">{c.scheduled ? t("On today's route") : t("Not scheduled today")}</div>
                </div>
                {c.visited ? <Badge tone="good">✓ {t(`visit.${c.visited}`)}</Badge> : c.balance > 0 && <Badge tone="warn">{t("Owes")} {money(c.balance)}</Badge>}
              </div>
              {c.address && <p className="mt-2 text-sm text-slate">{c.address}</p>}
              <div className="mt-3 flex flex-wrap gap-2">
                {mapUrl(c) && <a className="btn-ghost !py-1.5" href={mapUrl(c)!} target="_blank" rel="noreferrer">🧭 {t("Directions")}</a>}
                {c.phone && <a className="btn-ghost !py-1.5" href={`tel:${c.phone}`}>📞</a>}
                {c.phone && <WhatsAppButton phone={c.phone} text={t("Hello, I'll pass by today.")} className="!py-1.5" label="" />}
                {can("sales:write") && <Link className="btn-ghost !py-1.5" href={`/sales?new=1&customer=${c.id}`}>🧾 {t("New order")}</Link>}
                <button className="btn-primary !py-1.5" onClick={() => setVisit({ c, outcome: "visited", note: "", amount: c.balance > 0 ? String(c.balance) : "" })}>📍 {t("Log visit")}</button>
              </div>
            </div>
          ))}
        </div>
      </>}
      {tab === "visit log" && <div className="panel"><Table rows={log.data} cols={[
        { h: t("When"), c: (v: any) => new Date(v.at + (String(v.at).endsWith("Z") ? "" : "Z")).toLocaleString() },
        { h: t("Customer"), c: (v: any) => <Link className="text-signal" href={`/customers/${v.customer_id}`}>{v.customer}</Link> },
        { h: t("Rep"), c: (v: any) => v.user }, { h: t("Result"), c: (v: any) => <Badge tone="info">{t(`visit.${v.outcome}`)}</Badge> },
        { h: t("Note"), c: (v: any) => v.note ?? "—" },
        { h: t("Location"), c: (v: any) => v.lat ? <a className="link" target="_blank" rel="noreferrer" href={`https://www.google.com/maps?q=${v.lat},${v.lng}`}>📍 {t("Map")}</a> : "—" },
      ]} /></div>}

      <Modal title={visit ? `${t("Log visit")} · ${visit.c.name}` : ""} open={!!visit} onClose={() => setVisit(null)} onSave={busy ? undefined : save}>
        {visit && <div className="grid gap-3">
          <Field label={t("Result")}><div className="flex flex-wrap gap-2">{OUTCOMES.map((o) => (
            <button key={o} type="button" onClick={() => setVisit({ ...visit, outcome: o })} className={`rounded-lg border px-3 py-1.5 text-sm ${visit.outcome === o ? "border-signal bg-signal-soft text-signal" : "border-line"}`}>{t(`visit.${o}`)}</button>))}</div></Field>
          {visit.outcome === "collected" && can("field.collect_payment") && <Field label={t("Amount collected")}>
            <input className="input" type="number" inputMode="decimal" value={visit.amount} onChange={(e) => setVisit({ ...visit, amount: e.target.value })} /></Field>}
          {visit.outcome === "collected" && !can("field.collect_payment") && <p className="text-xs text-amber">{t("You can't record payments. Ask your manager for that permission, or note the amount below.")}</p>}
          <Field label={t("Note")}><textarea className="input min-h-20" value={visit.note} onChange={(e) => setVisit({ ...visit, note: e.target.value })} /></Field>
          {can("field.track_location")
            ? <p className="text-xs text-slate">{t("Your location is saved with the visit (the phone will ask for permission).")}</p>
            : <p className="text-xs text-slate">{t("Location isn't recorded for your role.")}</p>}
        </div>}
      </Modal>
    </>
  );
}
