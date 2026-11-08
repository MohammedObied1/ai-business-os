"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { ErrorNote, PageTitle, toast } from "@/components/ui";

type Rule = { kind: string; unit: "percent" | "amount" | "none"; enabled: boolean; threshold: number };

export default function ApprovalRules() {
  const { t } = useT();
  const { can, company } = useSession();
  const editable = can("approvals.rules");
  const { data, reload } = useApi<Rule[]>("/api/approval-rules");
  const [rules, setRules] = useState<Rule[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { if (data) setRules(data); }, [data]);

  const set = (i: number, patch: Partial<Rule>) => setRules(rules!.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const save = async () => {
    setError(null);
    try { await api("/api/approval-rules", { method: "PUT", json: rules!.map(({ kind, enabled, threshold }) => ({ kind, enabled, threshold: +threshold || 0 })) }); toast("Saved"); reload(); }
    catch (e: any) { setError(e.message); }
  };

  return (
    <>
      <PageTitle title={t("Approval rules")} help={t("Approval rules help")} actions={editable && <button className="btn-primary" onClick={save}>{t("Save changes")}</button>} />
      <ErrorNote error={error} />
      <div className="panel divide-y divide-line">
        {rules?.map((r, i) => (
          <div key={r.kind} className="flex flex-wrap items-center gap-4 p-4">
            <label className="flex min-w-0 flex-1 items-center gap-3">
              <input type="checkbox" className="h-5 w-5 accent-signal" disabled={!editable} checked={r.enabled} onChange={(e) => set(i, { enabled: e.target.checked })} />
              <span><span className="block font-medium">{t(`approval.kind.${r.kind}`)}</span><span className="block text-xs text-slate">{t(`approval.hint.${r.kind}`)}</span></span>
            </label>
            {r.unit !== "none" && <div className="flex items-center gap-2 text-sm">
              <span className="text-slate">{t(r.unit === "percent" ? "from %" : "from amount")}</span>
              <input className="input !w-28" type="number" min={0} disabled={!editable || !r.enabled} value={r.threshold} onChange={(e) => set(i, { threshold: +e.target.value })} />
              {r.unit === "amount" && <span className="text-slate">{company?.currency}</span>}
            </div>}
          </div>
        ))}
      </div>
      <p className="mt-3 text-xs text-slate">{t("People allowed to approve never wait for approval themselves. Nobody can approve their own request.")}</p>
    </>
  );
}
