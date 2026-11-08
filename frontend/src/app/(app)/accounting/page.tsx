"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { useApi, usePaged } from "@/lib/hooks";
import { date, money } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { DateRange, useMonthRange } from "@/components/money";
import { Badge, Drawer, ErrorNote, Field, Modal, PageTitle, PagedTable, Table, Tabs, toast } from "@/components/ui";

const TABS = ["chart of accounts", "journal", "trial balance", "balance sheet", "income statement", "integrity", "periods"] as const;
type Tab = (typeof TABS)[number];
const TYPES = ["asset", "liability", "equity", "revenue", "expense"];

export default function Accounting() {
  const { t, lang } = useT();
  const { can } = useSession();
  const canWrite = can("accounting:write");
  const [tab, setTab] = useState<Tab>("balance sheet");
  const r = useMonthRange();
  const [asOf, setAsOf] = useState(new Date().toISOString().slice(0, 10));
  const chart = useApi<any[]>("/api/accounting/accounts");
  const journal = usePaged<any>(tab === "journal" ? "/api/accounting/journal" : null, [tab], 30);
  const tb = useApi<any>(tab === "trial balance" ? `/api/accounting/trial-balance?start=${r.start}&end=${r.end}` : null, [tab, r.start, r.end]);
  const bs = useApi<any>(tab === "balance sheet" ? `/api/accounting/balance-sheet?as_of=${asOf}` : null, [tab, asOf]);
  const is = useApi<any>(tab === "income statement" ? `/api/accounting/income-statement?start=${r.start}&end=${r.end}` : null, [tab, r.start, r.end]);
  const periods = useApi<any[]>(tab === "periods" ? "/api/accounting/periods" : null, [tab]);
  const integrity = useApi<any>(tab === "integrity" ? "/api/accounting/integrity" : null, [tab]);
  const canClose = can("accounting.close_period");
  const periodAction = async (p: string, action: "close" | "reopen") => {
    const note = action === "reopen" ? prompt(t("Why reopen this month? (saved in the activity log)")) : prompt(t("Note (optional)"), "");
    if (note === null || (action === "reopen" && !note.trim())) return;
    try { await api(`/api/accounting/periods/${p}/${action}`, { method: "POST", json: { note } }); toast("Saved"); periods.reload(); }
    catch (e: any) { toast(e.message, "bad"); }
  };
  const [ledgerId, setLedgerId] = useState<number | null>(null);
  const ledger = useApi<any>(ledgerId ? `/api/accounting/accounts/${ledgerId}/ledger?start=${r.start}&end=${r.end}` : null, [ledgerId, r.start, r.end]);
  const [open, setOpen] = useState<"account" | "entry" | null>(null);
  const [acc, setAcc] = useState({ code: "", name: "", type: "asset" });
  const [entry, setEntry] = useState<{ entry_date: string; memo: string; lines: { account_id: number; debit: number; credit: number }[] }>({
    entry_date: new Date().toISOString().slice(0, 10), memo: "", lines: [{ account_id: 0, debit: 0, credit: 0 }, { account_id: 0, debit: 0, credit: 0 }] });
  const [error, setError] = useState<string | null>(null);
  const name = (a: any) => (lang === "ar" ? a.name : a.name_en || a.name);
  const debits = entry.lines.reduce((s, l) => s + (+l.debit || 0), 0);
  const credits = entry.lines.reduce((s, l) => s + (+l.credit || 0), 0);

  const saveAccount = async () => {
    setError(null);
    try { await api("/api/accounting/accounts", { method: "POST", json: acc }); setOpen(null); toast("Saved"); chart.reload(); } catch (e: any) { setError(e.message); }
  };
  const saveEntry = async () => {
    setError(null);
    try { await api("/api/accounting/journal", { method: "POST", json: entry }); setOpen(null); toast("Saved"); journal.reload(); chart.reload(); } catch (e: any) { setError(e.message); }
  };
  const Section = ({ title, rows, total }: { title: string; rows: any[]; total: number }) => (
    <div className="mb-4">
      <div className="mb-1 text-sm font-semibold">{title}</div>
      {rows.map((x, i) => <button key={x.code || i} onClick={() => x.account_id && setLedgerId(x.account_id)} className="flex w-full justify-between border-b border-line/60 py-1.5 text-sm hover:bg-paper">
        <span className="flex items-baseline gap-2"><span className="text-xs text-slate" dir="ltr">{x.code}</span><span>{name(x)}</span></span><span className="num">{money(x.amount, undefined, 2)}</span></button>)}
      <div className="flex justify-between py-2 font-semibold"><span>{t("Total")}</span><span className="num">{money(total, undefined, 2)}</span></div>
    </div>
  );

  return (
    <>
      <PageTitle title={t("Accounting")} help={t("Accounting help")} actions={canWrite && <>
        <button className="btn-ghost" onClick={() => { setError(null); setAcc({ code: "", name: "", type: "asset" }); setOpen("account"); }}>+ {t("New account")}</button>
        <button className="btn-primary" onClick={() => { setError(null); setOpen("entry"); }}>+ {t("Journal entry")}</button>
        <button className="btn-ghost print:hidden" onClick={() => window.print()}>🖨</button></>} />
      <div className="print:hidden"><Tabs tabs={TABS} value={tab} onChange={setTab} /></div>
      {["trial balance", "income statement"].includes(tab) && <div className="mb-4 print:hidden"><DateRange start={r.start} end={r.end} onChange={r.set} /></div>}
      {tab === "balance sheet" && <div className="mb-4 max-w-xs print:hidden"><Field label={t("As of")}><input className="input" type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} /></Field></div>}

      {tab === "chart of accounts" && <div className="panel"><Table rows={chart.data} pageSize={500} onRow={(a: any) => setLedgerId(a.id)} cols={[
        { h: t("Code"), c: (a: any) => <span dir="ltr" className="font-mono text-sm">{a.code}</span> }, { h: t("Account"), c: (a: any) => <span className="font-medium">{name(a)}</span> },
        { h: t("Type"), c: (a: any) => <Badge tone={a.type === "asset" ? "info" : a.type === "liability" ? "warn" : a.type === "revenue" ? "good" : a.type === "expense" ? "bad" : "neutral"}>{t(`gl.${a.type}`)}</Badge> },
        { h: t("Balance"), c: (a: any) => <span className="num">{money(a.balance, undefined, 2)}</span>, end: true },
      ]} /></div>}

      {tab === "journal" && <div className="panel"><PagedTable paged={journal} cols={[
        { h: t("Date"), c: (e: any) => date(e.date) },
        { h: t("Details"), c: (e: any) => <div><div className="font-medium">{e.memo}</div>{e.source === "manual" && <Badge tone="info">{e.number}</Badge>}</div> },
        { h: t("Lines"), c: (e: any) => <table className="w-full text-xs"><tbody>{e.lines.map((l: any, i: number) => (
          <tr key={i}><td className="py-0.5 pe-3"><span dir="ltr" className="text-slate">{l.code}</span> {l.account}</td>
            <td className="num w-24 py-0.5 text-end">{l.debit ? money(l.debit, undefined, 2) : ""}</td><td className="num w-24 py-0.5 text-end">{l.credit ? money(l.credit, undefined, 2) : ""}</td></tr>))}</tbody></table> },
        { h: "", c: (e: any) => e.source === "manual" && canWrite && <button className="link-danger" onClick={async () => { if (confirm(t("Delete?"))) { await api(`/api/accounting/journal/${e.id}`, { method: "DELETE" }); journal.reload(); } }}>{t("Delete")}</button> },
      ]} /></div>}

      {tab === "trial balance" && tb.data && <div className="panel"><Table rows={tb.data.rows} pageSize={500} onRow={(x: any) => setLedgerId(x.account_id)} cols={[
        { h: t("Code"), c: (x: any) => <span dir="ltr" className="font-mono text-sm">{x.code}</span> }, { h: t("Account"), c: (x: any) => name(x) },
        { h: t("Opening balance"), c: (x: any) => money(x.opening, undefined, 2), end: true }, { h: t("Debit"), c: (x: any) => money(x.debit, undefined, 2), end: true },
        { h: t("Credit"), c: (x: any) => money(x.credit, undefined, 2), end: true }, { h: t("Closing debit"), c: (x: any) => x.closing_debit ? money(x.closing_debit, undefined, 2) : "", end: true },
        { h: t("Closing credit"), c: (x: any) => x.closing_credit ? money(x.closing_credit, undefined, 2) : "", end: true },
      ]} />
        <div className={`flex justify-end gap-8 border-t border-line p-4 font-semibold ${tb.data.total_closing_debit === tb.data.total_closing_credit ? "" : "text-rust"}`}>
          <span>{t("Debit")}: {money(tb.data.total_closing_debit, undefined, 2)}</span><span>{t("Credit")}: {money(tb.data.total_closing_credit, undefined, 2)}</span>
          {tb.data.total_closing_debit === tb.data.total_closing_credit && <Badge tone="good">✓ {t("Balanced")}</Badge>}
        </div></div>}

      {tab === "balance sheet" && bs.data && (
        <div className="grid gap-6 lg:grid-cols-2">
          <div className="panel p-5"><Section title={t("Assets")} rows={bs.data.assets} total={bs.data.total_assets} /></div>
          <div className="panel p-5">
            <Section title={t("Liabilities")} rows={bs.data.liabilities} total={bs.data.total_liabilities} />
            <Section title={t("Equity")} rows={[...bs.data.equity, { code: "", name: "الأرباح المحتجزة (أرباح الفترات)", name_en: "Retained earnings (profit to date)", amount: bs.data.retained_earnings, account_id: null }]}
              total={bs.data.total_equity} />
            <div className={`mt-2 rounded-lg p-3 text-sm font-semibold ${bs.data.balanced ? "bg-moss-soft text-moss" : "bg-rust-soft text-rust"}`}>
              {bs.data.balanced ? `✓ ${t("Assets = liabilities + equity")}` : t("The balance sheet does not balance")}
            </div>
          </div>
        </div>
      )}

      {tab === "income statement" && is.data && (
        <div className="panel max-w-2xl p-5">
          <Section title={t("Revenue")} rows={is.data.revenue.map((x: any) => ({ ...x, account_id: chart.data?.find((a) => a.code === x.code)?.id }))} total={is.data.total_revenue} />
          <Section title={t("Expenses")} rows={is.data.expenses.map((x: any) => ({ ...x, account_id: chart.data?.find((a) => a.code === x.code)?.id }))} total={is.data.total_expenses} />
          <div className={`flex justify-between rounded-lg p-3 text-lg font-bold ${is.data.net_profit >= 0 ? "bg-moss-soft text-moss" : "bg-rust-soft text-rust"}`}>
            <span>{t("Net profit")}</span><span className="num">{money(is.data.net_profit, undefined, 2)}</span></div>
        </div>
      )}

      {tab === "integrity" && integrity.data && <>
        <div className={`mb-4 rounded-xl p-4 text-sm font-semibold ${integrity.data.healthy ? "bg-moss-soft text-moss" : "bg-rust-soft text-rust"}`}>
          {integrity.data.healthy ? `✓ ${t("Everything ties out.")}` : t("Something needs a look — see below.")}
          <div className="mt-1 text-xs font-normal text-slate">{t("Checked")}: {new Date(integrity.data.checked_at + "Z").toLocaleString()}</div>
        </div>
        <div className="space-y-3">{integrity.data.checks.map((c: any, i: number) => (
          <div key={i} className={`panel p-4 ${c.ok ? "" : "border-s-4 border-s-rust"}`}>
            <div className="flex items-center justify-between gap-2"><span className="font-medium">{c.check}</span>
              {c.ok ? <Badge tone="good">✓ {t("OK")}</Badge> : <Badge tone="bad">{t("Mismatch")}</Badge>}</div>
            {!c.ok && Array.isArray(c.detail) && c.detail.length > 0 && <ul className="mt-2 space-y-1 text-xs text-slate">
              {c.detail.map((d: any, j: number) => <li key={j}>{t("Entry")} #{d.entry_id} — {d.memo}: {t("Debit")} {money(d.debit, undefined, 2)} / {t("Credit")} {money(d.credit, undefined, 2)}</li>)}
            </ul>}
            {!c.ok && !Array.isArray(c.detail) && <div className="mt-2 grid grid-cols-3 gap-3 text-sm">
              <div><div className="text-xs text-slate">{t("Ledger balance")}</div><div className="font-semibold">{money(c.detail.ledger_balance, undefined, 2)}</div></div>
              <div><div className="text-xs text-slate">{t("Sub-ledger total")}</div><div className="font-semibold">{money(c.detail.sub_ledger_total, undefined, 2)}</div></div>
              <div><div className="text-xs text-slate">{t("Difference")}</div><div className="font-semibold text-rust">{money(c.detail.difference, undefined, 2)}</div></div>
            </div>}
          </div>
        ))}</div>
      </>}

      {tab === "periods" && <>
        <p className="mb-3 text-sm text-slate">{t("Closing a month locks its invoices, payments, expenses and entries. Corrections are then posted as adjustments in an open month.")}</p>
        <div className="panel"><Table rows={periods.data} pageSize={36} cols={[
          { h: t("Month"), c: (p: any) => <span className="font-medium" dir="ltr">{p.period}</span> },
          { h: t("Status"), c: (p: any) => <Badge tone={p.status === "CLOSED" ? "neutral" : "good"}>{p.status === "CLOSED" ? `🔒 ${t("Closed")}` : t("Open")}</Badge> },
          { h: t("Closed by"), c: (p: any) => p.closed_by ? `${p.closed_by} · ${date(p.closed_at)}` : "—" },
          { h: t("Note"), c: (p: any) => <span className="text-sm text-slate">{p.note ?? "—"}</span> },
          { h: "", c: (p: any) => canClose && <div className="flex justify-end">{p.status === "CLOSED"
            ? <button className="link-danger" onClick={() => periodAction(p.period, "reopen")}>{t("Reopen")}</button>
            : <button className="link" onClick={() => periodAction(p.period, "close")}>🔒 {t("Close month")}</button>}</div> },
        ]} /></div>
      </>}

      <Drawer title={ledger.data ? `${ledger.data.account.code} · ${name(ledger.data.account)}` : "…"} open={!!ledgerId} onClose={() => setLedgerId(null)}>
        <DateRange start={r.start} end={r.end} onChange={r.set} />
        {ledger.data && <>
          <div className="my-4 grid grid-cols-2 gap-3 text-sm">
            <div className="rounded-lg bg-paper p-3"><div className="text-slate">{t("Opening balance")}</div><div className="font-semibold">{money(ledger.data.opening, undefined, 2)}</div></div>
            <div className="rounded-lg bg-paper p-3"><div className="text-slate">{t("Closing balance")}</div><div className="font-semibold">{money(ledger.data.closing, undefined, 2)}</div></div>
          </div>
          <div className="rounded-lg border border-line"><Table rows={ledger.data.rows} pageSize={200} cols={[
            { h: t("Date"), c: (x: any) => date(x.date) }, { h: t("Details"), c: (x: any) => <span className="text-sm">{x.memo}</span> },
            { h: t("Debit"), c: (x: any) => x.debit ? money(x.debit, undefined, 2) : "", end: true }, { h: t("Credit"), c: (x: any) => x.credit ? money(x.credit, undefined, 2) : "", end: true },
            { h: t("Balance"), c: (x: any) => money(x.balance, undefined, 2), end: true },
          ]} /></div>
        </>}
      </Drawer>

      <Modal title={t("New account")} open={open === "account"} onClose={() => setOpen(null)} onSave={saveAccount}>
        <ErrorNote error={error} />
        <div className="grid grid-cols-2 gap-3">
          <Field label={t("Code")}><input className="input" dir="ltr" placeholder="1710" value={acc.code} onChange={(e) => setAcc({ ...acc, code: e.target.value })} /></Field>
          <Field label={t("Type")}><select className="input" value={acc.type} onChange={(e) => setAcc({ ...acc, type: e.target.value })}>{TYPES.map((x) => <option key={x} value={x}>{t(`gl.${x}`)}</option>)}</select></Field>
          <div className="col-span-2"><Field label={t("Name")}><input className="input" placeholder={t("e.g. Delivery van")} value={acc.name} onChange={(e) => setAcc({ ...acc, name: e.target.value })} /></Field></div>
        </div>
      </Modal>

      <Modal title={t("Journal entry")} open={open === "entry"} onClose={() => setOpen(null)} onSave={saveEntry}>
        <ErrorNote error={error} />
        <div className="grid grid-cols-2 gap-3">
          <Field label={t("Date")}><input className="input" type="date" value={entry.entry_date} onChange={(e) => setEntry({ ...entry, entry_date: e.target.value })} /></Field>
          <Field label={t("Description")}><input className="input" value={entry.memo} onChange={(e) => setEntry({ ...entry, memo: e.target.value })} /></Field>
        </div>
        <div className="mt-4 space-y-2">
          <div className="flex gap-2 text-xs text-slate"><span className="flex-1">{t("Account")}</span><span className="w-24">{t("Debit")}</span><span className="w-24">{t("Credit")}</span></div>
          {entry.lines.map((l, i) => (
            <div key={i} className="flex gap-2">
              <select className="input" value={l.account_id} onChange={(e) => setEntry({ ...entry, lines: entry.lines.map((x, j) => (j === i ? { ...x, account_id: +e.target.value } : x)) })}>
                <option value={0}>{t("Select…")}</option>{chart.data?.map((a) => <option key={a.id} value={a.id}>{a.code} · {name(a)}</option>)}
              </select>
              <input className="input !w-24 shrink-0 !px-2" type="number" value={l.debit} onChange={(e) => setEntry({ ...entry, lines: entry.lines.map((x, j) => (j === i ? { ...x, debit: +e.target.value, credit: 0 } : x)) })} />
              <input className="input !w-24 shrink-0 !px-2" type="number" value={l.credit} onChange={(e) => setEntry({ ...entry, lines: entry.lines.map((x, j) => (j === i ? { ...x, credit: +e.target.value, debit: 0 } : x)) })} />
            </div>
          ))}
          <button className="link -ms-2" onClick={() => setEntry({ ...entry, lines: [...entry.lines, { account_id: 0, debit: 0, credit: 0 }] })}>+ {t("Add line")}</button>
          <div className={`flex justify-end gap-6 text-sm font-semibold ${Math.abs(debits - credits) < 0.005 ? "text-moss" : "text-rust"}`}>
            <span>{t("Debit")}: {money(debits, undefined, 2)}</span><span>{t("Credit")}: {money(credits, undefined, 2)}</span>
          </div>
        </div>
      </Modal>
    </>
  );
}
