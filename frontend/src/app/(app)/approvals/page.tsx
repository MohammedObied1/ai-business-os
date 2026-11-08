"use client";
import Link from "next/link";
import { useState } from "react";
import { api, download } from "@/lib/api";
import { useApi, usePaged } from "@/lib/hooks";
import { date, money } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { Badge, ErrorNote, Field, Modal, PageTitle, PagedTable, Table, Tabs, toast } from "@/components/ui";

const TABS = ["waiting", "my requests", "history"] as const;
const PERCENT_KINDS = ["sales_discount", "price_change"];

/** Where the record behind a request lives in the app. */
function entityLink(r: any): string | null {
  if (!r.entity_id) return null;
  return ({ sales_orders: `/sales?order=${r.entity_id}`, invoices: `/sales/invoices/${r.entity_id}`, expenses: "/finance", purchase_orders: "/purchasing",
    products: "/inventory" } as Record<string, string>)[r.entity] ?? null;
}

export default function ApprovalCenter() {
  const { t, tx } = useT();
  const { can } = useSession();
  const approver = can("approvals.approve");
  const [tab, setTab] = useState<(typeof TABS)[number]>(approver ? "waiting" : "my requests");
  const path = tab === "waiting" ? "/api/approval-requests?status=PENDING" : tab === "my requests" ? "/api/approval-requests?status=&mine=true"
    : "/api/approval-requests?status=APPROVED,REJECTED,CANCELLED";
  const list = usePaged<any>(path, [tab]);
  const proofs = useApi<any[]>(can("payments:write") ? "/api/customers/payment-proofs/pending" : null);
  const accounts = useApi<any[]>(can("payments:write") ? "/api/accounts" : null);
  const [proof, setProof] = useState<any>(null);
  const [accountId, setAccountId] = useState<number | "">("");
  const [rejecting, setRejecting] = useState<any>(null);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const act = async (fn: () => Promise<any>, msg: string) => {
    try { await fn(); toast(msg); list.reload(); proofs.reload(); } catch (e: any) { toast(e.message, "bad"); }
  };
  const reject = async () => {
    setError(null);
    try { await api(`/api/approval-requests/${rejecting.id}/reject`, { method: "POST", json: { reason } }); setRejecting(null); toast("Rejected"); list.reload(); }
    catch (e: any) { setError(e.message); }
  };
  const confirmProof = () => act(async () => {
    await api(`/api/customers/payment-proofs/${proof.id}`, { method: "POST", json: { approve: true, method: "bank", account_id: accountId || null } });
    setProof(null);
  }, "Payment recorded");
  const value = (r: any) => r.requested_value == null ? "—" : PERCENT_KINDS.includes(r.kind) ? `${r.requested_value}%` : money(r.requested_value, undefined, 2);
  const tone = (s: string) => (s === "APPROVED" ? "good" : s === "REJECTED" ? "bad" : s === "PENDING" ? "warn" : "neutral") as any;

  return (
    <>
      <PageTitle title={t("Approval center")} help={t("Approvals help")}
        actions={can("approvals.rules") && <Link className="btn-ghost" href="/approval-rules">⚙ {t("Approval rules")}</Link>} />
      <Tabs tabs={approver ? TABS : (["my requests"] as const)} value={tab} onChange={setTab} />
      <div className="panel"><PagedTable paged={list} empty={tab === "waiting" ? t("Nothing is waiting for your approval.") : t("Nothing here yet.")} cols={[
        { h: t("Date"), c: (r: any) => date(r.created_at) },
        { h: t("Type"), c: (r: any) => <Badge tone="info">{t(`approval.kind.${r.kind}`)}</Badge> },
        { h: t("What"), c: (r: any) => { const href = entityLink(r); return href ? <Link className="text-signal" href={href}>{r.label ?? "—"}</Link> : r.label ?? "—"; } },
        { h: t("Value"), c: (r: any) => value(r), end: true },
        { h: t("Why"), c: (r: any) => <span className="text-xs text-slate">{(r.reason ?? "").split(/[;\n]/).map((x: string) => tx(x.trim())).filter(Boolean).join(" · ") || "—"}</span> },
        { h: t("By"), c: (r: any) => r.requested_by ?? "—" },
        { h: t("Status"), c: (r: any) => <div><Badge tone={tone(r.status)}>{t(`approval.${r.status}`)}</Badge>
          {r.approver && <div className="mt-0.5 text-xs text-slate">{r.approver}</div>}{r.rejection_reason && <div className="text-xs text-rust">{r.rejection_reason}</div>}</div> },
        { h: "", c: (r: any) => r.status === "PENDING" && <div className="flex justify-end gap-1">
          {tab === "waiting" && <>
            <button className="btn-primary !px-3 !py-1" onClick={() => act(() => api(`/api/approval-requests/${r.id}/approve`, { method: "POST", json: {} }), "Approved")}>{t("Approve")}</button>
            <button className="link-danger" onClick={() => { setError(null); setReason(""); setRejecting(r); }}>{t("Reject")}</button></>}
          {tab === "my requests" && <button className="link-danger" onClick={() => confirm(t("Cancel this request?")) && act(() => api(`/api/approval-requests/${r.id}/cancel`, { method: "POST" }), "Cancelled")}>{t("Cancel")}</button>}
        </div> },
      ]} /></div>

      {!!proofs.data?.length && <>
        <h2 className="mb-1 mt-8 text-lg font-semibold">{t("Payment notices from customers")}</h2>
        <p className="mb-3 text-sm text-slate">{t("Customers sent these from their portal link. Check your bank, then confirm.")}</p>
        <div className="panel"><Table rows={proofs.data} cols={[
          { h: t("Date"), c: (p: any) => date(p.created_at) },
          { h: t("Customer"), c: (p: any) => <Link className="text-signal" href={`/customers/${p.customer_id}`}>{p.customer}</Link> },
          { h: t("Reference"), c: (p: any) => <span dir="ltr">{p.reference ?? "—"}</span> }, { h: t("Note"), c: (p: any) => p.note ?? "—" },
          { h: t("File"), c: (p: any) => p.attachment_id ? <button className="link" onClick={() => download(`/api/attachments/${p.attachment_id}`, "proof")}>📎 {t("Open")}</button> : "—" },
          { h: t("Amount"), c: (p: any) => money(p.amount), end: true },
          { h: "", c: (p: any) => <div className="flex justify-end gap-1">
            <button className="btn-primary !px-3 !py-1" onClick={() => { setAccountId(""); setProof(p); }}>{t("Confirm")}</button>
            <button className="link-danger" onClick={() => confirm(t("Reject?")) && act(() => api(`/api/customers/payment-proofs/${p.id}`, { method: "POST", json: { approve: false } }), "Rejected")}>{t("Reject")}</button>
          </div> },
        ]} /></div>
      </>}

      <Modal title={t("Reject request")} open={!!rejecting} onClose={() => setRejecting(null)} onSave={reject} saveLabel={t("Reject")}>
        <ErrorNote error={error} />
        {rejecting && <p className="mb-3 text-sm">{t(`approval.kind.${rejecting.kind}`)} · {rejecting.label}</p>}
        <Field label={t("Reason (the requester sees it)")}><textarea className="input h-24" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      </Modal>
      <Modal title={t("Confirm payment")} open={!!proof} onClose={() => setProof(null)} onSave={confirmProof} saveLabel={t("Confirm")}>
        {proof && <div className="space-y-3">
          <p className="text-sm">{proof.customer} · <Badge tone="good">{money(proof.amount)}</Badge></p>
          <Field label={t("Received into")}>
            <select className="input" value={accountId} onChange={(e) => setAccountId(e.target.value ? +e.target.value : "")}>
              <option value="">{t("Default bank account")}</option>
              {accounts.data?.filter((a) => a.is_active !== false).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </Field>
        </div>}
      </Modal>
    </>
  );
}
