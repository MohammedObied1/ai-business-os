"use client";
import { useEffect, useState } from "react";
import { usePaged } from "@/lib/hooks";
import { useT } from "@/lib/i18n";
import { Badge, Field, PagedTable } from "./ui";

export const AUDIT_ENTITIES = ["products", "customers", "suppliers", "sales_orders", "invoices", "payments", "purchase_orders", "expenses", "accounts",
  "transactions", "cheques", "credit_notes", "employees", "payroll_runs", "users", "roles", "companies", "branches", "journal_entries", "accounting_periods",
  "approval_requests", "approval_rules", "price_lists", "promotions", "stock_counts", "stock_transfers", "api_keys", "webhooks", "currencies"];
const ACTIONS = ["create", "update", "delete", "impersonation_start", "period_close", "period_reopen", "export"];

/** Filterable activity log. `base` = the list endpoint (company or platform view); `users` fills the "who" filter. */
export function AuditTable({ base, users, platform = false }: { base: string; users?: { id: number; full_name: string }[]; platform?: boolean }) {
  const { t, tx } = useT();
  const [f, setF] = useState({ entity: "", user_id: "", action: "", date_from: "", date_to: "", ip: "", q: "" });
  const [debounced, setDebounced] = useState(f);
  useEffect(() => { const h = setTimeout(() => setDebounced(f), 300); return () => clearTimeout(h); }, [f]);
  const qs = new URLSearchParams(Object.entries(debounced).filter(([, v]) => v) as [string, string][]).toString();
  const list = usePaged<any>(`${base}${base.includes("?") ? "&" : "?"}${qs}`, [qs], 50, { platform });
  const set = (k: keyof typeof f) => (e: any) => setF({ ...f, [k]: e.target.value });
  const tone = (a: string) => (a === "create" ? "good" : a === "delete" ? "bad" : a === "update" ? "info" : "warn") as any;
  const fmt = (v: unknown) => (v === null || v === undefined || v === "" ? "—" : typeof v === "boolean" ? (v ? "✓" : "✗") : String(v));

  return (
    <>
      <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
        <Field label={t("What")}><select className="input" value={f.entity} onChange={set("entity")}><option value="">{t("Everything")}</option>
          {AUDIT_ENTITIES.map((e) => <option key={e} value={e}>{t(`entity.${e}`)}</option>)}</select></Field>
        {users && <Field label={t("Who")}><select className="input" value={f.user_id} onChange={set("user_id")}><option value="">{t("Everyone")}</option>
          {users.map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}</select></Field>}
        <Field label={t("Action")}><select className="input" value={f.action} onChange={set("action")}><option value="">{t("All")}</option>
          {ACTIONS.map((a) => <option key={a} value={a}>{t(`action.${a}`)}</option>)}</select></Field>
        <Field label={t("From")}><input className="input" type="date" value={f.date_from} onChange={set("date_from")} /></Field>
        <Field label={t("To")}><input className="input" type="date" value={f.date_to} onChange={set("date_to")} /></Field>
        <Field label="IP"><input className="input" dir="ltr" value={f.ip} onChange={set("ip")} /></Field>
        <Field label={t("Search")}><input className="input" placeholder={t("Name or number")} value={f.q} onChange={set("q")} /></Field>
      </div>
      <div className="panel"><PagedTable paged={list} empty={t("Nothing recorded yet.")} cols={[
        { h: t("When"), c: (a: any) => <span className="whitespace-nowrap text-slate">{new Date(a.created_at + (String(a.created_at).endsWith("Z") ? "" : "Z")).toLocaleString()}</span> },
        { h: t("Who"), c: (a: any) => <div>{a.user_name ?? "—"}{a.impersonated_by && <Badge tone="warn">{t("platform admin")}</Badge>}</div> },
        { h: t("Action"), c: (a: any) => <Badge tone={tone(a.action)}>{t(`action.${a.action}`)}</Badge> },
        { h: t("What"), c: (a: any) => <span><span className="text-slate">{t(`entity.${a.entity}`)}:</span> <span className="font-medium">{tx(a.label) || (a.entity_id ? `#${a.entity_id}` : "")}</span></span> },
        { h: t("Changes"), c: (a: any) => <div>
          {Object.keys(a.changes ?? {}).length ? <ul className="space-y-0.5 text-xs">{Object.entries(a.changes).map(([k, v]: any) => Array.isArray(v)
            ? <li key={k}><span className="text-slate">{k}:</span> <span className="text-rust line-through">{fmt(v[0])}</span> → <span className="text-moss">{fmt(v[1])}</span></li>
            : <li key={k}><span className="text-slate">{k}:</span> {fmt(v)}</li>)}</ul> : "—"}
          {a.reason && <div className="mt-1 text-xs"><span className="text-slate">{t("Reason")}:</span> {a.reason}</div>}</div> },
        { h: t("Device"), c: (a: any) => <div className="text-xs text-slate" dir="ltr">{a.ip ?? ""}<div className="max-w-[12rem] truncate" title={a.user_agent ?? ""}>{a.user_agent ?? ""}</div></div> },
      ]} /></div>
    </>
  );
}
