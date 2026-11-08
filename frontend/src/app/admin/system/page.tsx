"use client";
import { useState } from "react";
import { usePaged, useApi } from "@/lib/hooks";
import { useT } from "@/lib/i18n";
import { Badge, Drawer, PageTitle, PagedTable, StatCard, Table, Tabs } from "@/components/ui";

const TABS = ["overview", "errors", "jobs"] as const;

/** Platform observability: requests, server resources, background jobs, errors. */
export default function SystemPage() {
  const { t } = useT();
  const [tab, setTab] = useState<(typeof TABS)[number]>("overview");
  const sys = useApi<any>(tab === "overview" ? "/api/platform/system" : null, [tab], { platform: true });
  const [source, setSource] = useState("");
  const errs = usePaged<any>(tab === "errors" ? `/api/platform/errors?source=${source}` : null, [tab, source], 50, { platform: true });
  const jobs = usePaged<any>(tab === "jobs" ? "/api/platform/jobs" : null, [tab], 50, { platform: true });
  const [detail, setDetail] = useState<any>(null);
  const d = sys.data;
  const m = d?.metrics;
  const r = d?.resources;

  return (
    <>
      <PageTitle title={t("System")} help={t("System help")} actions={tab === "overview" && <button className="btn-ghost" onClick={sys.reload}>↻ {t("Refresh")}</button>} />
      <Tabs tabs={TABS} value={tab} onChange={setTab} />
      {tab === "overview" && d && <>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatCard label={t("Requests since restart")} value={m.requests.toLocaleString()} note={Object.entries(m.by_status).map(([k, v]) => `${k}: ${v}`).join(" · ")} />
          <StatCard label={t("Response time p95")} value={`${m.latency_ms.p95} ms`} note={`p50 ${m.latency_ms.p50} · p99 ${m.latency_ms.p99}`} tone={m.latency_ms.p95 > 1000 ? "bad" : "neutral"} />
          <StatCard label={t("Memory")} value={r.memory ? `${r.memory.used_pct}%` : "—"} note={r.memory ? `${r.memory.used_mb} / ${r.memory.total_mb} MB` : t("Only measured on Linux servers")} />
          <StatCard label={t("Disk (data)")} value={r.disk?.data ? `${r.disk.data.used_pct}%` : "—"} note={r.disk?.data ? `${r.disk.data.free_gb} GB ${t("free")}` : ""} tone={r.disk?.data?.free_gb < 2 ? "bad" : "neutral"} />
        </div>
        <div className="mt-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatCard label={t("CPU load")} value={r.load_avg ? r.load_avg.join(" / ") : "—"} note={`${r.cpu_count} CPU`} />
          <StatCard label={t("Emails waiting / failed 24h")} value={`${d.email_waiting} / ${d.email_failed_24h}`} tone={d.email_failed_24h ? "bad" : "neutral"} />
          <StatCard label={t("Webhooks pending / failed 24h")} value={`${d.webhooks_pending} / ${d.webhooks_failed_24h}`} tone={d.webhooks_failed_24h ? "bad" : "neutral"} />
          <StatCard label={t("Errors 24h")} value={String(Object.values(d.errors_24h as Record<string, number>).reduce((a, b) => a + b, 0))}
            note={Object.entries(d.errors_24h).map(([k, v]) => `${k}: ${v}`).join(" · ")} />
        </div>
        <h2 className="mb-2 mt-8 text-lg font-semibold">{t("Background jobs")}</h2>
        <div className="panel"><Table rows={Object.entries(d.jobs).map(([name, j]: any) => ({ name, ...j }))} cols={[
          { h: t("Job"), c: (j: any) => <span className="font-mono text-sm">{j.name}</span> },
          { h: t("Last run"), c: (j: any) => { const x = j.last_in_memory ?? j.last_recorded; return x ? <span><Badge tone={x.status === "ok" ? "good" : "bad"}>{x.status}</Badge> <span className="text-xs text-slate">{String(x.at).replace("T", " ").slice(0, 19)} · {x.ms} ms</span></span> : "—"; } },
          { h: t("Failures 24h"), c: (j: any) => j.failures_24h ? <span className="font-semibold text-rust">{j.failures_24h}</span> : "0", end: true },
        ]} /></div>
        <h2 className="mb-2 mt-8 text-lg font-semibold">{t("Slowest routes")}</h2>
        <div className="panel"><Table rows={m.slowest_routes} cols={[
          { h: t("Route"), c: (x: any) => <span dir="ltr" className="font-mono text-xs">{x.route}</span> }, { h: t("Calls"), c: (x: any) => x.count, end: true },
          { h: t("Average"), c: (x: any) => `${x.avg_ms} ms`, end: true }, { h: t("Errors"), c: (x: any) => x.errors, end: true },
        ]} /></div>
        {m.slow_queries.length > 0 && <>
          <h2 className="mb-2 mt-8 text-lg font-semibold">{t("Slow database queries")}</h2>
          <div className="panel"><Table rows={m.slow_queries} cols={[{ h: t("When"), c: (q: any) => q.at }, { h: "ms", c: (q: any) => q.ms, end: true },
            { h: "SQL", c: (q: any) => <span dir="ltr" className="font-mono text-xs">{q.sql}</span> }]} /></div>
        </>}
      </>}
      {tab === "errors" && <>
        <div className="mb-3 flex gap-1 text-sm">{["", "http", "job", "email", "webhook", "ai", "backup"].map((s) => (
          <button key={s || "all"} onClick={() => setSource(s)} className={`rounded-md px-3 py-1 ${source === s ? "bg-signal text-white" : "text-slate hover:bg-paper"}`}>{s || t("All")}</button>))}</div>
        <div className="panel"><PagedTable paged={errs} onRow={setDetail} empty={t("No errors recorded.")} cols={[
          { h: t("When"), c: (e: any) => new Date(e.at + "Z").toLocaleString() }, { h: t("Source"), c: (e: any) => <Badge tone={e.level === "error" ? "bad" : "warn"}>{e.source}</Badge> },
          { h: t("Company"), c: (e: any) => e.company ?? "—" }, { h: t("Message"), c: (e: any) => <span className="text-sm">{e.message}</span> },
          { h: t("Where"), c: (e: any) => e.path ? <span dir="ltr" className="font-mono text-xs">{e.method} {e.path} {e.status ?? ""}</span> : "—" },
        ]} /></div>
      </>}
      {tab === "jobs" && <div className="panel"><PagedTable paged={jobs} empty={t("No job runs recorded yet.")} cols={[
        { h: t("Job"), c: (j: any) => <span className="font-mono text-sm">{j.job}</span> }, { h: t("Started"), c: (j: any) => new Date(j.started_at + "Z").toLocaleString() },
        { h: t("Status"), c: (j: any) => <Badge tone={j.status === "ok" ? "good" : j.status === "failed" ? "bad" : "info"}>{j.status}</Badge> },
        { h: "ms", c: (j: any) => j.ms ?? "—", end: true }, { h: t("Details"), c: (j: any) => <span className="text-xs text-slate">{j.detail ?? ""}</span> },
      ]} /></div>}
      <Drawer title={detail?.message ?? ""} open={!!detail} onClose={() => setDetail(null)}>
        {detail && <pre className="whitespace-pre-wrap break-all rounded-lg bg-paper p-3 text-xs" dir="ltr">{detail.detail ?? t("No details.")}</pre>}
      </Drawer>
    </>
  );
}
