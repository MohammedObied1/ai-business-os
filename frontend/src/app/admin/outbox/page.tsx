"use client";
import { useState } from "react";
import { useApi } from "@/lib/hooks";
import { useT } from "@/lib/i18n";
import { Badge, Drawer, PageTitle, Table } from "@/components/ui";

export default function Outbox() {
  const { t } = useT();
  const data = useApi<any>("/api/platform/outbox", [], { platform: true });
  const [open, setOpen] = useState<any>(null);
  return (
    <>
      <PageTitle title={t("Emails")} help={t("Outbox help")} />
      {data.data && !data.data.smtp && <div className="mb-4 rounded-xl bg-amber-soft p-4 text-sm text-amber">{t("Email sending is not set up (SMTP). Emails are saved here and not sent. Add SMTP_HOST, SMTP_USER and SMTP_PASSWORD to backend/.env.")}</div>}
      <div className="panel"><Table rows={data.data?.items ?? null} onRow={setOpen} empty={t("No emails yet.")} cols={[
        { h: t("When"), c: (m: any) => new Date(m.created_at + (String(m.created_at).endsWith("Z") ? "" : "Z")).toLocaleString() },
        { h: t("To"), c: (m: any) => <span dir="ltr">{m.to}</span> }, { h: t("Subject"), c: (m: any) => m.subject },
        { h: t("Type"), c: (m: any) => <Badge tone="info">{m.kind ?? "—"}</Badge> },
        { h: t("Status"), c: (m: any) => <Badge tone={m.status === "sent" ? "good" : m.status === "failed" ? "bad" : "warn"}>{t(`mail.${m.status}`)}</Badge> },
      ]} /></div>
      <Drawer title={open?.subject ?? ""} open={!!open} onClose={() => setOpen(null)}>
        {open && <>
          <p className="mb-2 text-sm text-slate" dir="ltr">{open.to}</p>
          {open.error && <p className="mb-2 rounded bg-rust-soft p-2 text-xs text-rust" dir="ltr">{open.error}</p>}
          <iframe title="email" sandbox="" className="h-[70vh] w-full rounded-lg border border-line bg-white" srcDoc={open.body_html} />
        </>}
      </Drawer>
    </>
  );
}
