"use client";
import { useRef, useState } from "react";
import { api, download, upload } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { date } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { toast } from "./ui";

/** Files attached to any record (expense receipt, contract, invoice scan…). */
export function Attachments({ entity, id, compact = false }: { entity: string; id: number; compact?: boolean }) {
  const { t } = useT();
  const list = useApi<any[]>(`/api/attachments?entity=${entity}&entity_id=${id}`, [entity, id]);
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const add = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true);
    try {
      for (const f of Array.from(files)) await upload(`/api/attachments?entity=${entity}&entity_id=${id}`, f);
      toast("Uploaded"); list.reload();
    } catch (e: any) { toast(e.message, "bad"); } finally { setBusy(false); if (input.current) input.current.value = ""; }
  };
  const kb = (n: number) => (n > 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);
  return (
    <div className={compact ? "" : "mt-6"}>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold">📎 {t("Attachments")}</h3>
        <button className="link" disabled={busy} onClick={() => input.current?.click()}>{busy ? "…" : `+ ${t("Attach file")}`}</button>
        <input ref={input} type="file" multiple hidden onChange={(e) => add(e.target.files)} />
      </div>
      {list.data && !list.data.length && <p className="text-xs text-slate">{t("No files yet. Attach a receipt, contract or photo.")}</p>}
      <ul className="space-y-1">
        {list.data?.map((a) => (
          <li key={a.id} className="flex items-center justify-between gap-2 rounded-lg border border-line px-3 py-2 text-sm">
            <button className="min-w-0 truncate text-start text-signal hover:underline" onClick={() => download(`/api/attachments/${a.id}`, a.filename).catch((e) => toast(e.message, "bad"))}>{a.filename}</button>
            <span className="shrink-0 text-xs text-slate">{kb(a.size)} · {date(a.created_at)}</span>
            <button className="link-danger shrink-0" onClick={async () => { if (confirm(t("Delete?"))) { await api(`/api/attachments/${a.id}`, { method: "DELETE" }); list.reload(); } }}>✕</button>
          </li>
        ))}
      </ul>
    </div>
  );
}
