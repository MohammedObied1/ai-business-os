"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { date } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { Badge, ErrorNote, Field, Modal, PageTitle, Status, Table, Tabs, toast } from "@/components/ui";

const TABS = ["rules", "what they did"] as const;
const LEGACY_ACTION: Record<string, string> = { create_alert: "alert", notify: "notify", create_task: "create_task", create_purchase_request: "purchase_suggestion" };
// actions that make sense for each kind of match
const ACTIONS_FOR: Record<string, string[]> = {
  invoice: ["alert", "notify", "email_customer", "whatsapp_customer", "create_task"], product: ["alert", "notify", "purchase_suggestion"],
  cheque: ["alert", "notify", "create_task"], customer: ["alert", "notify", "create_task", "email_customer", "whatsapp_customer"],
  company: ["alert", "notify"], user: ["alert", "notify"], event: ["require_approval"],
};

type Action = { type: string; params: Record<string, any> };
const actionsOf = (r: any): Action[] => (r.actions?.length ? r.actions : [{ type: LEGACY_ACTION[r.action_type] ?? "alert", params: {} }]);

export default function Automation() {
  const { t, tx } = useT();
  const { can } = useSession();
  const editable = can("automation:write");
  const [tab, setTab] = useState<(typeof TABS)[number]>("rules");
  const rules = useApi<any[]>("/api/automation/rules");
  const catalog = useApi<any>("/api/automation/catalog");
  const logs = useApi<any[]>(tab === "what they did" && editable ? "/api/automation/logs" : null, [tab]);
  const users = useApi<any[]>("/api/users");
  const [form, setForm] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const conds: any[] = catalog.data?.conditions ?? [];
  const cond = (type: string) => conds.find((c) => c.type === type);
  const ruleName = (id: number) => tx(rules.data?.find((r) => r.id === id)?.name) ?? `#${id}`;

  const openRule = (r: any = null) => {
    setError(null);
    if (r) setForm({ id: r.id, name: r.name, condition_type: r.condition_type, params: { ...(r.params ?? {}) }, severity: r.severity, is_active: r.is_active, actions: actionsOf(r) });
    else setForm({ name: "", condition_type: "invoice_overdue", params: { days: 30 }, severity: "warning", is_active: true, actions: [{ type: "alert", params: {} }] });
  };
  const setCondition = (type: string) => {
    const c = cond(type);
    const allowed = ACTIONS_FOR[c?.subject ?? "company"];
    setForm({ ...form, condition_type: type, params: { ...(c?.params ?? {}) }, actions: [{ type: allowed[0], params: {} }] });
  };
  const toggleAction = (type: string) => {
    const has = form.actions.some((a: Action) => a.type === type);
    setForm({ ...form, actions: has ? form.actions.filter((a: Action) => a.type !== type) : [...form.actions, { type, params: {} }] });
  };
  const setActionParam = (type: string, k: string, v: any) =>
    setForm({ ...form, actions: form.actions.map((a: Action) => (a.type === type ? { ...a, params: { ...a.params, [k]: v } } : a)) });
  const save = async () => {
    setError(null);
    const body = { name: form.name, condition_type: form.condition_type, params: form.params, severity: form.severity, is_active: form.is_active,
      action_type: "create_alert", actions: form.actions };
    try { await api(form.id ? `/api/automation/rules/${form.id}` : "/api/automation/rules", { method: form.id ? "PATCH" : "POST", json: body }); setForm(null); toast("Saved"); rules.reload(); }
    catch (e: any) { setError(e.message); }
  };
  const toggle = async (r: any) => { await api(`/api/automation/rules/${r.id}`, { method: "PATCH", json: { ...r, is_active: !r.is_active } }); rules.reload(); };
  const runNow = async () => { try { const r = await api("/api/automation/run", { method: "POST" }); toast(t("{n} actions done", { n: Object.values(r.created as Record<string, number>).reduce((a, b) => a + b, 0) })); rules.reload(); } catch (e: any) { toast(e.message, "bad"); } };
  const condLabel = (r: any) => {
    const n = r.params?.days ?? r.params?.pct ?? r.params?.amount;
    const label = t(`cond.${r.condition_type}`);
    return n != null ? label.replace("N", String(n)) : label;
  };
  const allowed = form ? ACTIONS_FOR[cond(form.condition_type)?.subject ?? "company"] : [];

  return (
    <>
      <PageTitle title={t("Automatic rules")} help={t("Automation help")} actions={editable && <>
        <button className="btn-ghost" onClick={runNow}>▶ {t("Run now")}</button>
        <button className="btn-primary" onClick={() => openRule()}>+ {t("New rule")}</button></>} />
      <Tabs tabs={editable ? TABS : (["rules"] as const)} value={tab} onChange={setTab} />
      {tab === "rules" && <div className="panel"><Table rows={rules.data} onRow={editable ? openRule : undefined} cols={[
        { h: t("Rule"), c: (r: any) => <span className="font-medium">{tx(r.name)}</span> },
        { h: t("If"), c: (r: any) => condLabel(r) },
        { h: t("Then"), c: (r: any) => <div className="flex flex-wrap gap-1">{actionsOf(r).map((a) => <Badge key={a.type} tone="info">{t(`act.${a.type}`)}</Badge>)}</div> },
        { h: t("Importance"), c: (r: any) => <Status value={r.severity} /> },
        { h: t("Last run"), c: (r: any) => date(r.last_run_at) },
        { h: t("On"), c: (r: any) => <input type="checkbox" className="h-4 w-4 accent-signal" disabled={!editable} checked={r.is_active} onClick={(e) => e.stopPropagation()} onChange={() => toggle(r)} aria-label={t("On")} /> },
      ]} /></div>}
      {tab === "what they did" && <div className="panel"><Table rows={logs.data} empty={t("Nothing yet.")} cols={[
        { h: t("When"), c: (x: any) => new Date(x.created_at + "Z").toLocaleString() }, { h: t("Rule"), c: (x: any) => ruleName(x.rule_id) },
        { h: t("Action"), c: (x: any) => <Badge tone="info">{t(`act.${x.action}`)}</Badge> }, { h: t("On"), c: (x: any) => <span className="text-xs" dir="ltr">{x.match_key}</span> },
        { h: t("Details"), c: (x: any) => <span className="text-xs text-slate">{x.detail ?? ""}</span> },
      ]} /></div>}
      <p className="mt-3 text-xs text-slate">{t("Rules never move money on their own. Purchase suggestions are requests that still need approval.")}</p>

      <Modal title={form?.id ? t("Edit rule") : t("New rule")} open={!!form} onClose={() => setForm(null)} onSave={save} saveLabel={t("Save rule")}>
        {form && <>
          <ErrorNote error={error} />
          <div className="grid gap-3">
            <Field label={t("Name")}><input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
            <Field label={t("If")}><select className="input" value={form.condition_type} onChange={(e) => setCondition(e.target.value)}>
              {conds.map((c) => <option key={c.type} value={c.type}>{t(`cond.${c.type}`).replace("N", "…")}</option>)}</select></Field>
            {Object.keys(form.params).map((k) => <Field key={k} label={t(`param.${k}`)}>
              <input className="input" type="number" value={form.params[k]} onChange={(e) => setForm({ ...form, params: { ...form.params, [k]: +e.target.value } })} /></Field>)}
            <div>
              <div className="mb-1 text-sm font-medium">{t("Then")}</div>
              <div className="space-y-2">{allowed.map((type) => {
                const a = form.actions.find((x: Action) => x.type === type);
                return <div key={type} className="rounded-lg border border-line p-2">
                  <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="accent-signal" checked={!!a} onChange={() => toggleAction(type)} />{t(`act.${type}`)}</label>
                  {a && type === "notify" && <div className="mt-2 ps-6"><Field label={t("Who (permission, e.g. accounting.view)")}><input className="input !py-1" dir="ltr" value={a.params.permission ?? ""} onChange={(e) => setActionParam(type, "permission", e.target.value)} /></Field></div>}
                  {a && ["email_customer", "whatsapp_customer", "notify"].includes(type) && <div className="mt-2 ps-6"><Field label={t("Repeat every (days, empty = once)")}><input className="input !py-1" type="number" value={a.params.repeat_days ?? ""} onChange={(e) => setActionParam(type, "repeat_days", e.target.value ? +e.target.value : null)} /></Field></div>}
                  {a && type === "create_task" && <div className="mt-2 ps-6"><Field label={t("Assign to")}><select className="input !py-1" value={a.params.assign_to ?? ""} onChange={(e) => setActionParam(type, "assign_to", e.target.value ? +e.target.value : null)}>
                    <option value="">—</option>{users.data?.map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}</select></Field></div>}
                </div>;
              })}</div>
            </div>
            <Field label={t("Importance")}><select className="input" value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value })}>{["info", "warning", "critical"].map((s) => <option key={s} value={s}>{t(s)}</option>)}</select></Field>
          </div>
        </>}
      </Modal>
    </>
  );
}
