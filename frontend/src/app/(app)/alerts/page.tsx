"use client";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { date } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { PageTitle } from "@/components/ui";

export default function Alerts() {
  const { t, tx } = useT();
  const alerts = useApi<any[]>("/api/alerts");
  const tasks = useApi<any[]>("/api/tasks");
  const resolve = async (id: number) => { await api(`/api/alerts/${id}/resolve`, { method: "POST" }); alerts.reload(); };
  const done = async (id: number) => { await api(`/api/tasks/${id}/status?status=done`, { method: "POST" }); tasks.reload(); };
  const border = (sev: string) => (sev === "critical" ? "border-s-rust" : sev === "warning" ? "border-s-amber" : "border-s-line");
  return (
    <>
      <PageTitle title={t("Alerts & tasks")} help={t("Alerts help")} actions={<button className="btn-ghost" onClick={async () => { await api("/api/automation/run", { method: "POST" }); alerts.reload(); tasks.reload(); }}>{t("Check now")}</button>} />
      <div className="grid gap-8 lg:grid-cols-2">
        <section>
          <h2 className="mb-3 text-lg font-semibold">{t("Alerts")} <span className="text-base font-normal text-slate">({alerts.data?.length ?? "…"})</span></h2>
          <ul className="space-y-2">
            {alerts.data?.map((a) => <li key={a.id} className={`panel flex gap-3 border-s-4 p-4 ${border(a.severity)}`}>
              <div className="min-w-0 flex-1">
                <div className="font-medium">{tx(a.title)}</div>
                {a.message && <div className="mt-0.5 text-sm text-slate">{tx(a.message)}</div>}
                {a.recommended_action && <div className="mt-1 text-sm text-signal">💡 {tx(a.recommended_action)}</div>}
                <div className="mt-1 text-xs text-slate">{date(a.created_at)}</div>
              </div>
              <button className="btn-ghost self-start !px-3 !py-1" onClick={() => resolve(a.id)}>✓ {t("Done")}</button></li>)}
            {alerts.data && !alerts.data.length && <li className="panel p-4 text-sm text-slate">{t("No alerts. All good!")}</li>}
          </ul>
        </section>
        <section>
          <h2 className="mb-3 text-lg font-semibold">{t("Tasks")} <span className="text-base font-normal text-slate">({tasks.data?.length ?? "…"})</span></h2>
          <ul className="space-y-2">
            {tasks.data?.map((tk) => <li key={tk.id} className="panel flex gap-3 p-4">
              <input type="checkbox" className="mt-1 h-4 w-4 accent-signal" onChange={() => done(tk.id)} aria-label={t("Mark done")} />
              <div className="min-w-0 flex-1"><div className="font-medium">{tx(tk.title)}</div>{tk.description && <div className="text-sm text-slate">{tx(tk.description)}</div>}<div className="mt-1 text-xs text-slate">{t("Created by")} {tx(tk.created_by)} · {date(tk.created_at)}</div></div></li>)}
            {tasks.data && !tasks.data.length && <li className="panel p-4 text-sm text-slate">{t("No tasks.")}</li>}
          </ul>
        </section>
      </div>
    </>
  );
}
