"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { date, money } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { ErrorNote, Field, Modal, PageTitle, Status, Table, Tabs, toast, useForm } from "@/components/ui";

const ATT = ["present", "absent", "leave", "sick", "late"] as const;
const ATT_STYLE: Record<string, string> = { present: "bg-moss text-white", absent: "bg-rust text-white", leave: "bg-signal text-white", sick: "bg-amber text-white", late: "bg-ink text-white" };
const EMPTY = { full_name: "", job_title: "", phone: "", national_id: "", hire_date: "", base_salary: 0, allowances: 0, working_days: 26, is_active: true, notes: "" };

export default function HR() {
  const { t } = useT();
  const { can } = useSession();
  const canWrite = can("hr:write");
  const [tab, setTab] = useState<"employees" | "attendance" | "advances" | "payroll">("employees");
  const employees = useApi<any[]>("/api/hr/employees");
  const advances = useApi<any[]>("/api/hr/advances");
  const runs = useApi<any[]>("/api/hr/payroll");
  const { data: accounts } = useApi<any[]>("/api/accounts");
  const [open, setOpen] = useState<"employee" | "advance" | "pay" | null>(null);
  const [editing, setEditing] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const e = useForm(EMPTY);
  const adv = useForm({ employee_id: 0, amount: 0, monthly_deduction: 0, account_id: 0, note: "" });
  const [day, setDay] = useState(new Date().toISOString().slice(0, 10));
  const att = useApi<any[]>(`/api/hr/attendance?day=${day}`, [day]);
  const [sheet, setSheet] = useState<Record<number, { status: string; overtime_hours: number }>>({});
  const [month, setMonth] = useState(new Date().toISOString().slice(0, 7));
  const [run, setRun] = useState<any>(null);
  const [payAccount, setPayAccount] = useState(0);
  const active = employees.data?.filter((x) => x.is_active) ?? [];
  const name = (id: number) => employees.data?.find((x) => x.id === id)?.full_name ?? "";

  useEffect(() => {
    if (!att.data || !employees.data) return;
    const s: typeof sheet = {};
    for (const emp of employees.data) s[emp.id] = { status: "present", overtime_hours: 0 };
    for (const a of att.data) s[a.employee_id] = { status: a.status, overtime_hours: a.overtime_hours };
    setSheet(s);
  }, [att.data, employees.data]);
  useEffect(() => { const r = runs.data?.find((x) => x.month === month); if (r) api(`/api/hr/payroll/${r.id}`).then(setRun); else setRun(null); }, [runs.data, month]);

  const openEmployee = (x: any = null) => {
    setError(null); setEditing(x);
    e.setV(x ? { ...EMPTY, ...Object.fromEntries(Object.entries(x).map(([k, v]) => [k, v ?? ""])) } : EMPTY);
    setOpen("employee");
  };
  const saveEmployee = async () => {
    setError(null);
    const body = { ...e.v, hire_date: e.v.hire_date || null };
    try { await api(editing ? `/api/hr/employees/${editing.id}` : "/api/hr/employees", { method: editing ? "PATCH" : "POST", json: body }); toast("Saved"); setOpen(null); employees.reload(); }
    catch (err: any) { setError(err.message); }
  };
  const saveSheet = async () => {
    try {
      await api("/api/hr/attendance", { method: "POST", json: active.map((emp) => ({ employee_id: emp.id, day, ...sheet[emp.id] })) });
      toast("Saved"); att.reload();
    } catch (err: any) { toast(err.message, "bad"); }
  };
  const giveAdvance = async () => {
    setError(null);
    try { await api("/api/hr/advances", { method: "POST", json: { ...adv.v, employee_id: +adv.v.employee_id, account_id: +adv.v.account_id || null } }); toast("Saved"); setOpen(null); advances.reload(); employees.reload(); }
    catch (err: any) { setError(err.message); }
  };
  const prepare = async () => {
    try { const r = await api(`/api/hr/payroll?month=${month}`, { method: "POST" }); setRun(r); runs.reload(); toast("Payroll prepared"); } catch (err: any) { toast(err.message, "bad"); }
  };
  const editSlip = async (slip: any, patch: any) => {
    try { setRun(await api(`/api/hr/payroll/${run.id}/slips/${slip.id}`, { method: "PATCH", json: patch })); } catch (err: any) { toast(err.message, "bad"); }
  };
  const paySalaries = async () => {
    setError(null);
    try { setRun(await api(`/api/hr/payroll/${run.id}/pay`, { method: "POST", json: { account_id: payAccount || null } })); setOpen(null); runs.reload(); advances.reload(); toast("Salaries paid"); }
    catch (err: any) { setError(err.message); }
  };

  return (
    <>
      <PageTitle title={t("Employees & salaries")} help={t("HR help")} actions={canWrite && <>
        {tab === "advances" && <button className="btn-ghost" onClick={() => { setError(null); adv.setV({ employee_id: active[0]?.id ?? 0, amount: 0, monthly_deduction: 0, account_id: accounts?.[0]?.id ?? 0, note: "" }); setOpen("advance"); }}>+ {t("Give an advance")}</button>}
        <button className="btn-primary" onClick={() => openEmployee()}>+ {t("New employee")}</button></>} />
      <Tabs tabs={["employees", "attendance", "advances", "payroll"] as const} value={tab} onChange={setTab} />

      {tab === "employees" && <div className="panel"><Table rows={employees.data} empty={t("No employees yet.")} onRow={canWrite ? openEmployee : undefined} cols={[
        { h: t("Name"), c: (x: any) => <div><div className="font-medium">{x.full_name}</div><div className="text-xs text-slate">{x.job_title}</div></div> },
        { h: t("Phone"), c: (x: any) => <span dir="ltr">{x.phone || "—"}</span> }, { h: t("Hired"), c: (x: any) => date(x.hire_date) },
        { h: t("Salary"), c: (x: any) => money(x.base_salary), end: true }, { h: t("Allowances"), c: (x: any) => money(x.allowances), end: true },
        { h: t("Advance owed"), c: (x: any) => x.advance_balance ? <span className="text-amber">{money(x.advance_balance)}</span> : "—", end: true },
        { h: t("Status"), c: (x: any) => <Status value={x.is_active ? "active" : "inactive"} /> },
      ]} /></div>}

      {tab === "attendance" && <>
        <div className="mb-4 flex flex-wrap items-end gap-3">
          <Field label={t("Day")}><input className="input" type="date" value={day} onChange={(ev) => setDay(ev.target.value)} /></Field>
          {canWrite && <button className="btn-primary" onClick={saveSheet}>{t("Save attendance")}</button>}
        </div>
        <div className="panel divide-y divide-line">
          {active.map((emp) => (
            <div key={emp.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
              <div className="min-w-40 flex-1 font-medium">{emp.full_name}</div>
              <div className="flex flex-wrap gap-1">
                {ATT.map((s) => <button key={s} disabled={!canWrite} onClick={() => setSheet({ ...sheet, [emp.id]: { ...sheet[emp.id], status: s } })}
                  className={`rounded-md px-3 py-1 text-xs ${sheet[emp.id]?.status === s ? ATT_STYLE[s] : "bg-paper text-slate"}`}>{t(s)}</button>)}
              </div>
              <label className="flex items-center gap-2 text-xs text-slate">{t("Overtime hours")}
                <input className="input !w-16 !py-1" type="number" disabled={!canWrite} value={sheet[emp.id]?.overtime_hours ?? 0} onChange={(ev) => setSheet({ ...sheet, [emp.id]: { ...sheet[emp.id], overtime_hours: +ev.target.value } })} />
              </label>
            </div>
          ))}
          {!active.length && <div className="p-6 text-sm text-slate">{t("No employees yet.")}</div>}
        </div>
      </>}

      {tab === "advances" && <div className="panel"><Table rows={advances.data} empty={t("No advances.")} cols={[
        { h: t("Employee"), c: (x: any) => name(x.employee_id) }, { h: t("Date"), c: (x: any) => date(x.given_on) },
        { h: t("Amount"), c: (x: any) => money(x.amount), end: true }, { h: t("Monthly deduction"), c: (x: any) => money(x.monthly_deduction), end: true },
        { h: t("Repaid"), c: (x: any) => money(x.repaid), end: true }, { h: t("Remaining"), c: (x: any) => x.remaining > 0 ? <b className="text-amber">{money(x.remaining)}</b> : <span className="text-moss">✓</span>, end: true },
      ]} /></div>}

      {tab === "payroll" && <>
        <div className="mb-4 flex flex-wrap items-end gap-3 print:hidden">
          <Field label={t("Month")}><input className="input" type="month" value={month} onChange={(ev) => setMonth(ev.target.value)} /></Field>
          {canWrite && run?.status !== "paid" && <button className="btn-ghost" onClick={prepare}>{run ? t("Recalculate") : t("Prepare payroll")}</button>}
          {canWrite && run && run.status !== "paid" && <button className="btn-primary" onClick={() => { setError(null); setPayAccount(accounts?.[0]?.id ?? 0); setOpen("pay"); }}>{t("Pay salaries")} · {money(run.total_net)}</button>}
          {run && <button className="btn-ghost" onClick={() => window.print()}>🖨 {t("Print payslips")}</button>}
          {run?.status === "paid" && <Status value="paid" />}
        </div>
        {!run ? <div className="panel p-6 text-sm text-slate">{t("Payroll help")}</div> : (
          <div className="panel"><Table rows={run.slips} cols={[
            { h: t("Employee"), c: (x: any) => <span className="font-medium">{x.employee}</span> },
            { h: t("Salary"), c: (x: any) => money(x.base_salary), end: true }, { h: t("Allowances"), c: (x: any) => money(x.allowances), end: true },
            { h: t("Overtime"), c: (x: any) => money(x.overtime), end: true },
            { h: t("Bonus"), c: (x: any) => run.status === "paid" ? money(x.bonus) : <input className="input !w-20 !py-1" type="number" defaultValue={x.bonus} onBlur={(ev) => +ev.target.value !== x.bonus && editSlip(x, { bonus: +ev.target.value })} />, end: true },
            { h: t("Absence"), c: (x: any) => x.absence_days ? <span className="text-rust">−{money(x.absence_deduction)} ({x.absence_days})</span> : "—", end: true },
            { h: t("Advance"), c: (x: any) => x.advance_deduction ? `−${money(x.advance_deduction)}` : "—", end: true },
            { h: t("Other deductions"), c: (x: any) => run.status === "paid" ? money(x.other_deduction) : <input className="input !w-20 !py-1" type="number" defaultValue={x.other_deduction} onBlur={(ev) => +ev.target.value !== x.other_deduction && editSlip(x, { other_deduction: +ev.target.value })} />, end: true },
            { h: t("Net salary"), c: (x: any) => <b>{money(x.net, undefined, 2)}</b>, end: true },
          ]} />
            <div className="flex justify-end border-t border-line px-4 py-3 text-lg font-semibold">{t("Total")}: {money(run.total_net, undefined, 2)}</div>
          </div>
        )}
      </>}

      <Modal title={editing ? t("Edit employee") : t("New employee")} open={open === "employee"} onClose={() => setOpen(null)} onSave={saveEmployee}>
        <ErrorNote error={error} />
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2"><Field label={`${t("Full name")} *`}><input className="input" value={e.v.full_name} onChange={e.set("full_name")} /></Field></div>
          <Field label={t("Job title")}><input className="input" value={e.v.job_title} onChange={e.set("job_title")} /></Field>
          <Field label={t("Phone")}><input className="input" dir="ltr" value={e.v.phone} onChange={e.set("phone")} /></Field>
          <Field label={t("ID number")}><input className="input" dir="ltr" value={e.v.national_id} onChange={e.set("national_id")} /></Field>
          <Field label={t("Hire date")}><input className="input" type="date" value={e.v.hire_date} onChange={e.set("hire_date")} /></Field>
          <Field label={t("Monthly salary")}><input className="input" type="number" value={e.v.base_salary} onChange={e.set("base_salary")} /></Field>
          <Field label={t("Allowances")}><input className="input" type="number" value={e.v.allowances} onChange={e.set("allowances")} /></Field>
          <Field label={t("Working days per month")}><input className="input" type="number" value={e.v.working_days} onChange={e.set("working_days")} /></Field>
          {editing && <label className="flex items-end gap-2 pb-2 text-sm"><input type="checkbox" className="h-4 w-4 accent-signal" checked={e.v.is_active} onChange={e.set("is_active")} />{t("Still working here")}</label>}
          <div className="col-span-2"><Field label={t("Notes")}><input className="input" value={e.v.notes} onChange={e.set("notes")} /></Field></div>
        </div>
      </Modal>
      <Modal title={t("Give an advance")} open={open === "advance"} onClose={() => setOpen(null)} onSave={giveAdvance}>
        <ErrorNote error={error} />
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2"><Field label={t("Employee")}><select className="input" value={adv.v.employee_id} onChange={adv.set("employee_id")}>{active.map((x) => <option key={x.id} value={x.id}>{x.full_name}</option>)}</select></Field></div>
          <Field label={t("Amount")}><input className="input" type="number" value={adv.v.amount} onChange={adv.set("amount")} /></Field>
          <Field label={t("Deduct every month")}><input className="input" type="number" value={adv.v.monthly_deduction} onChange={adv.set("monthly_deduction")} /></Field>
          <Field label={t("Paid from")}><select className="input" value={adv.v.account_id} onChange={adv.set("account_id")}>{accounts?.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</select></Field>
          <Field label={t("Note")}><input className="input" value={adv.v.note} onChange={adv.set("note")} /></Field>
        </div>
      </Modal>
      <Modal title={t("Pay salaries")} open={open === "pay"} onClose={() => setOpen(null)} onSave={paySalaries} saveLabel={t("Pay salaries")}>
        <ErrorNote error={error} />
        <p className="mb-3 text-sm">{t("Pay salaries help", { total: money(run?.total_net ?? 0, undefined, 2) })}</p>
        <Field label={t("Paid from")}><select className="input" value={payAccount} onChange={(ev) => setPayAccount(+ev.target.value)}>{accounts?.map((a) => <option key={a.id} value={a.id}>{a.name} ({money(a.balance)})</option>)}</select></Field>
      </Modal>
    </>
  );
}
