"use client";
import { useApi } from "@/lib/hooks";
import { useT } from "@/lib/i18n";
import { AuditTable } from "@/components/AuditTable";
import { PageTitle } from "@/components/ui";

export default function Audit() {
  const { t } = useT();
  const users = useApi<any[]>("/api/users");
  return (
    <>
      <PageTitle title={t("Activity log")} help={t("Audit help")} />
      <AuditTable base="/api/audit" users={users.data ?? undefined} />
    </>
  );
}
