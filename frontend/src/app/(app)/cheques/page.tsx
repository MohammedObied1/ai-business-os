"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { date, money } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { ErrorNote, Field, Modal, PageTitle, StatCard, Status, Table, Tabs, toast } from "@/components/ui";

export default function Cheques() {
  const { t } = useT();
  const { can } = useSession();
  const [tab, setTab] = useState<"incoming" | "outgoing">("incoming");
  const [status, setStatus] = useState("open");
  const list = useApi<any[]>(`/api/cheques?direction=${tab === "incoming" ? "in" : "out"}`, [tab]);
  const summary = useApi<any>("/api/cheques/summary");
  const { data: accounts } = useApi<any[]>("/api/accounts");
  const [action, setAction] = useState<{ kind: "deposit" | "clear" | "bounce"; cheque: any } | null>(null);
  const [accountId, setAccountId] = useState(0);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  const rows = list.data?.filter((c) => status === "all" || (status === "open" ? ["pending", "deposited"].includes(c.status) : c.status === status)) ?? null;
  const open = (kind: "deposit" | "clear" | "bounce", cheque: any) => {
    setError(null); setNote("");
    setAccountId(cheque.account_id ?? accounts?.find((a) => a.kind === "bank")?.id ?? accounts?.[0]?.id ?? 0);
    setAction({ kind, cheque });
  };
  const submit = async () => {
    if (!action) return;
    setError(null);
    try {
      await api(`/api/cheques/${action.cheque.id}/${action.kind}`, { method: "POST", json: { account_id: accountId || null, note: note || null } });
      toast("Saved"); setAction(null); list.reload(); summary.reload();
    } catch (e: any) { setError(e.message); }
  };
  const cancel = async (c: any) => {
    if (!confirm(t("Cancel this cheque? The supplier will be owed the amount again."))) return;
    try { await api(`/api/cheques/${c.id}/cancel`, { method: "POST" }); toast("Saved"); list.reload(); summary.reload(); } catch (e: any) { toast(e.message, "bad"); }
  };
  const dueTone = (c: any) => (!["pending", "deposited"].includes(c.status) ? "" : c.days_to_due < 0 ? "text-rust font-semibold" : c.days_to_due <= 3 ? "text-amber font-semibold" : "");
  const s = summary.data;
  const canWrite = can("accounts:write");

  return (
    <>
      <PageTitle title={t("Cheques")} help={t("Cheques help")} />
      {s && <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label={t("Cheques in hand")} value={money(s.in_hand)} note={`${t("Due this week")}: ${money(s.in_due_week)}`} />
        <StatCard label={t("Cheques we issued")} value={money(s.issued)} note={`${t("Due this week")}: ${money(s.out_due_week)}`} tone={s.out_due_week ? "bad" : "neutral"} />
        <StatCard label={t("Bounced cheques")} value={String(s.bounced_count)} tone={s.bounced_count ? "bad" : "neutral"} />
      </div>}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs tabs={["incoming", "outgoing"] as const} value={tab} onChange={setTab} />
        <select className="input mb-4 !w-auto" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="open">{t("Not settled yet")}</option><option value="cleared">{t("cleared")}</option><option value="bounced">{t("bounced")}</option><option value="all">{t("All")}</option>
        </select>
      </div>
      <div className="panel"><Table rows={rows} empty={t("No cheques.")} cols={[
        { h: t("Cheque number"), c: (c: any) => <span className="font-medium" dir="ltr">{c.number}</span> },
        { h: tab === "incoming" ? t("From") : t("To"), c: (c: any) => c.party ?? "—" },
        { h: t("Bank"), c: (c: any) => c.bank ?? "—" },
        { h: t("Due"), c: (c: any) => <span className={dueTone(c)}>{date(c.due_date)}{["pending", "deposited"].includes(c.status) && c.days_to_due < 0 ? ` (${t("late")})` : ""}</span> },
        { h: t("Amount"), c: (c: any) => money(c.amount, undefined, 2), end: true },
        { h: t("Status"), c: (c: any) => <Status value={c.status} /> },
        { h: "", c: (c: any) => canWrite && <div className="flex justify-end gap-1 whitespace-nowrap">
            {c.direction === "in" && c.status === "pending" && <button className="link" onClick={() => open("deposit", c)}>{t("Deposit")}</button>}
            {["pending", "deposited"].includes(c.status) && <button className="link" onClick={() => open("clear", c)}>{t("Cashed")}</button>}
            {["pending", "deposited"].includes(c.status) && c.direction === "in" && <button className="link-danger" onClick={() => open("bounce", c)}>{t("Bounced")}</button>}
            {c.direction === "out" && c.status === "pending" && <button className="link-danger" onClick={() => cancel(c)}>{t("Cancel")}</button>}
          </div> },
      ]} /></div>

      <Modal title={action ? `${t(action.kind === "deposit" ? "Deposit" : action.kind === "clear" ? "Cashed" : "Bounced")} · ${action.cheque.number}` : ""} open={!!action} onClose={() => setAction(null)} onSave={submit}>
        <ErrorNote error={error} />
        {action && <p className="mb-3 text-sm">{action.cheque.party} · <b>{money(action.cheque.amount, undefined, 2)}</b></p>}
        {action?.kind === "bounce"
          ? <><p className="mb-3 text-sm text-rust">{t("The customer will owe this amount again and an alert will be created.")}</p>
              <Field label={t("Note")}><input className="input" value={note} onChange={(e) => setNote(e.target.value)} /></Field></>
          : <Field label={action?.kind === "deposit" ? t("Deposited into") : action?.cheque.direction === "in" ? t("Money went into") : t("Paid from")}>
              <select className="input" value={accountId} onChange={(e) => setAccountId(+e.target.value)}>{accounts?.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</select>
            </Field>}
      </Modal>
    </>
  );
}
