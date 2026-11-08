"use client";
import Link from "next/link";
import { useApi } from "@/lib/hooks";
import { date } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { Badge, PageTitle, StatCard, Table } from "@/components/ui";

const TONE: Record<string, any> = { HEALTHY: "good", WARNING: "warn", CRITICAL: "bad" };

/** Health of every company (platform admin only). */
export default function TenantHealth() {
  const { t } = useT();
  const { data } = useApi<any>("/api/platform/health", [], { platform: true });
  const s = data?.summary ?? {};
  return (
    <>
      <PageTitle title={t("Company health")} help={t("Company health help")} />
      <div className="mb-6 grid grid-cols-3 gap-4">
        <StatCard label={t("Healthy")} value={String(s.HEALTHY ?? 0)} tone="good" />
        <StatCard label={t("Warning")} value={String(s.WARNING ?? 0)} tone={s.WARNING ? "bad" : "neutral"} />
        <StatCard label={t("Critical")} value={String(s.CRITICAL ?? 0)} tone={s.CRITICAL ? "bad" : "neutral"} />
      </div>
      <div className="panel"><Table rows={data?.companies ?? null} pageSize={100} cols={[
        { h: t("Company"), c: (r: any) => <Link className="font-medium text-signal" href={`/admin/companies/${r.company_id}`}>{r.company}</Link> },
        { h: t("Health"), c: (r: any) => <div><Badge tone={TONE[r.level]}>{t(`health.${r.level}`)}</Badge>
          {r.reasons.length > 0 && <div className="mt-1 text-xs text-slate">{r.reasons.join(" · ")}</div>}</div> },
        { h: t("Subscription"), c: (r: any) => <span className="text-sm">{r.plan ?? "—"} · {t(`sub.${r.subscription}`)}</span> },
        { h: t("Users"), c: (r: any) => r.users, end: true },
        { h: t("Storage"), c: (r: any) => `${r.storage_mb} MB`, end: true },
        { h: "AI / API", c: (r: any) => `${r.ai_requests} / ${r.api_requests}`, end: true },
        { h: t("Errors 24h"), c: (r: any) => r.errors_24h ? <span className="font-semibold text-rust">{r.errors_24h}</span> : "0", end: true },
        { h: t("Last activity"), c: (r: any) => date(r.last_activity) },
        { h: t("Last sign-in"), c: (r: any) => date(r.last_login) },
      ]} /></div>
      {data?.backups && <p className="mt-3 text-sm text-slate">{t("Latest backup")}: {data.backups.latest?.name ?? "—"} ·
        {" "}{t("Restore test")}: {data.backups.restore_test ? `${t(data.backups.restore_test.status)} (${date(data.backups.restore_test.at)})` : t("never run")}</p>}
    </>
  );
}
