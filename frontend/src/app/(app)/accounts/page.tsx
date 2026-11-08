"use client";
import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { useApi, usePaged } from "@/lib/hooks";
import { date, money } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { DateRange, useMonthRange } from "@/components/money";
import { Drawer, ErrorNote, Field, Modal, PageTitle, PagedTable, Table, toast, useForm } from "@/components/ui";

const KIND_ICON: Record<string, string> = { cash: "💵", bank: "🏦" };

export default function Accounts() {
  const { t } = useT();
  const { can } = useSession();
  const canWrite = can("accounts:write");
  const accounts = useApi<any[]>("/api/accounts");
  const recent = usePaged<any>("/api/transactions", [], 30);
  const [open, setOpen] = useState<"account" | "in" | "out" | "transfer" | null>(null);
  const [editing, setEditing] = useState<any>(null);
  const [viewId, setViewId] = useState<number | null>(null);
  const range = useMonthRange();
  const ledger = useApi<any>(viewId ? `/api/accounts/${viewId}/ledger?start=${range.start}&end=${range.end}` : null, [viewId, range.start, range.end]);
  const [error, setError] = useState<string | null>(null);
  const acc = useForm({ name: "", kind: "cash", bank_name: "", account_number: "", opening_balance: 0, is_active: true });
  const v = useForm({ account_id: 0, amount: 0, party_name: "", description: "", reference: "", tx_date: new Date().toISOString().slice(0, 10) });
  const tr = useForm({ from_account_id: 0, to_account_id: 0, amount: 0, description: "" });
  const list = accounts.data ?? [];
  const accName = (id: number) => list.find((a) => a.id === id)?.name ?? "";
  const totalCash = list.filter((a) => a.kind === "cash").reduce((s, a) => s + a.balance, 0);
  const totalBank = list.filter((a) => a.kind === "bank").reduce((s, a) => s + a.balance, 0);

  const show = (m: typeof open, item: any = null) => {
    setError(null); setEditing(item);
    if (m === "account") acc.setV(item ? { name: item.name, kind: item.kind, bank_name: item.bank_name ?? "", account_number: item.account_number ?? "", opening_balance: item.opening_balance, is_active: item.is_active }
      : { name: "", kind: "cash", bank_name: "", account_number: "", opening_balance: 0, is_active: true });
    if (m === "in" || m === "out") v.setV({ account_id: list[0]?.id ?? 0, amount: 0, party_name: "", description: "", reference: "", tx_date: new Date().toISOString().slice(0, 10) });
    if (m === "transfer") tr.setV({ from_account_id: list.find((a) => a.kind === "cash")?.id ?? 0, to_account_id: list.find((a) => a.kind === "bank")?.id ?? 0, amount: 0, description: "" });
    setOpen(m);
  };
  const submit = async (fn: () => Promise<any>, ok: string) => {
    setError(null);
    try { const r = await fn(); setOpen(null); toast(r?.pending_approval ? "Sent to a manager for approval" : ok); accounts.reload(); recent.reload(); ledger.reload(); } catch (e: any) { setError(e.message); }
  };
  const kindLabel = (k: string) => t(`tx.${k}`) === `tx.${k}` ? k : t(`tx.${k}`);
  const txCols = (withAccount: boolean) => [
    { h: t("Date"), c: (r: any) => date(r.date) },
    { h: t("Voucher"), c: (r: any) => r.number ? <Link className="link -ms-2" href={`/vouchers/${r.number}`} dir="ltr">{r.number}</Link> : "—" },
    ...(withAccount ? [{ h: t("Account"), c: (r: any) => accName(r.account_id) }] : []),
    { h: t("Type"), c: (r: any) => kindLabel(r.kind) },
    { h: t("Details"), c: (r: any) => <span className="text-slate">{[r.party_name, r.description, r.reference].filter(Boolean).join(" · ")}</span> },
    { h: t("In"), c: (r: any) => r.amount > 0 ? <span className="text-moss">{money(r.amount, undefined, 2)}</span> : "", end: true },
    { h: t("Out"), c: (r: any) => r.amount < 0 ? <span className="text-rust">{money(-r.amount, undefined, 2)}</span> : "", end: true },
  ];

  return (
    <>
      <PageTitle title={t("Cash & banks")} help={t("Accounts help")} actions={canWrite && <>
        <button className="btn-ghost" onClick={() => show("in")}>＋ {t("Receipt voucher")}</button>
        <button className="btn-ghost" onClick={() => show("out")}>－ {t("Payment voucher")}</button>
        <button className="btn-ghost" onClick={() => show("transfer")}>⇄ {t("Transfer")}</button>
        <button className="btn-primary" onClick={() => show("account")}>+ {t("New account")}</button></>} />

      <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {list.map((a) => (
          <button key={a.id} onClick={() => setViewId(a.id)} className={`panel p-4 text-start transition hover:border-signal ${a.is_active ? "" : "opacity-50"}`}>
            <div className="flex items-center gap-2 text-sm text-slate"><span>{KIND_ICON[a.kind]}</span>{a.name}</div>
            <div className={`mt-1 text-2xl font-semibold ${a.balance < 0 ? "text-rust" : ""}`}>{money(a.balance, undefined, 2)}</div>
            {a.bank_name && <div className="text-xs text-slate">{a.bank_name} {a.account_number && <span dir="ltr">· {a.account_number}</span>}</div>}
          </button>
        ))}
      </div>
      <div className="mb-6 flex flex-wrap gap-6 text-sm">
        <span>💵 {t("Total cash")}: <b>{money(totalCash, undefined, 2)}</b></span>
        <span>🏦 {t("Total in banks")}: <b>{money(totalBank, undefined, 2)}</b></span>
      </div>

      <h2 className="mb-3 text-lg font-semibold">{t("Latest money movements")}</h2>
      <div className="panel"><PagedTable paged={recent} empty={t("No movements yet.")} cols={txCols(true)} /></div>

      <Drawer title={ledger.data?.account.name ?? "…"} open={!!viewId} onClose={() => setViewId(null)} actions={canWrite && viewId && (
        <button className="btn-ghost !px-3 !py-1" onClick={() => show("account", list.find((a) => a.id === viewId))}>{t("Edit")}</button>)}>
        <DateRange start={range.start} end={range.end} onChange={range.set} />
        {ledger.data && <>
          <div className="my-4 grid grid-cols-2 gap-3 text-sm">
            <div className="rounded-lg bg-paper p-3"><div className="text-slate">{t("Opening balance")}</div><div className="text-lg font-semibold">{money(ledger.data.opening, undefined, 2)}</div></div>
            <div className="rounded-lg bg-paper p-3"><div className="text-slate">{t("Closing balance")}</div><div className="text-lg font-semibold">{money(ledger.data.closing, undefined, 2)}</div></div>
          </div>
          <div className="rounded-lg border border-line"><Table rows={ledger.data.rows} empty={t("No movements yet.")} cols={[...txCols(false), { h: t("Balance"), c: (r: any) => money(r.balance, undefined, 2), end: true }]} /></div>
        </>}
      </Drawer>

      <Modal title={editing ? t("Edit account") : t("New account")} open={open === "account"} onClose={() => setOpen(null)}
        onSave={() => submit(() => editing ? api(`/api/accounts/${editing.id}`, { method: "PATCH", json: acc.v }) : api("/api/accounts", { method: "POST", json: acc.v }), "Saved")}>
        <ErrorNote error={error} />
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2"><Field label={t("Name")}><input className="input" placeholder={t("e.g. Main cash box, Bank of Palestine")} value={acc.v.name} onChange={acc.set("name")} /></Field></div>
          <Field label={t("Type")}><select className="input" value={acc.v.kind} onChange={acc.set("kind")}><option value="cash">{t("Cash box")}</option><option value="bank">{t("Bank account")}</option></select></Field>
          <Field label={t("Opening balance")}><input className="input" type="number" step="0.01" value={acc.v.opening_balance} onChange={acc.set("opening_balance")} /></Field>
          {acc.v.kind === "bank" && <>
            <Field label={t("Bank")}><input className="input" value={acc.v.bank_name} onChange={acc.set("bank_name")} /></Field>
            <Field label={t("Account number")}><input className="input" dir="ltr" value={acc.v.account_number} onChange={acc.set("account_number")} /></Field>
          </>}
          {editing && <label className="col-span-2 flex items-center gap-2 text-sm"><input type="checkbox" className="h-4 w-4 accent-signal" checked={acc.v.is_active} onChange={acc.set("is_active")} />{t("Active")}</label>}
        </div>
      </Modal>

      <Modal title={open === "in" ? t("Receipt voucher") : t("Payment voucher")} open={open === "in" || open === "out"} onClose={() => setOpen(null)}
        onSave={() => submit(() => api("/api/vouchers", { method: "POST", json: { ...v.v, direction: open, account_id: +v.v.account_id || null } }), "Saved")}>
        <ErrorNote error={error} />
        <p className="mb-3 text-sm text-slate">{open === "in" ? t("Receipt voucher help") : t("Payment voucher help")}</p>
        <div className="grid grid-cols-2 gap-3">
          <Field label={open === "in" ? t("Into") : t("From account")}><select className="input" value={v.v.account_id} onChange={v.set("account_id")}>{list.filter((a) => a.is_active).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</select></Field>
          <Field label={t("Amount")}><input className="input" type="number" step="0.01" value={v.v.amount} onChange={v.set("amount")} /></Field>
          <Field label={open === "in" ? t("Received from") : t("Paid to")}><input className="input" value={v.v.party_name} onChange={v.set("party_name")} /></Field>
          <Field label={t("Date")}><input className="input" type="date" value={v.v.tx_date} onChange={v.set("tx_date")} /></Field>
          <div className="col-span-2"><Field label={t("Description")}><input className="input" value={v.v.description} onChange={v.set("description")} /></Field></div>
        </div>
      </Modal>

      <Modal title={t("Transfer")} open={open === "transfer"} onClose={() => setOpen(null)}
        onSave={() => submit(() => api("/api/transfers", { method: "POST", json: { ...tr.v, from_account_id: +tr.v.from_account_id, to_account_id: +tr.v.to_account_id } }), "Saved")}>
        <ErrorNote error={error} />
        <div className="grid grid-cols-2 gap-3">
          <Field label={t("From")}><select className="input" value={tr.v.from_account_id} onChange={tr.set("from_account_id")}>{list.map((a) => <option key={a.id} value={a.id}>{a.name} ({money(a.balance)})</option>)}</select></Field>
          <Field label={t("To")}><select className="input" value={tr.v.to_account_id} onChange={tr.set("to_account_id")}>{list.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</select></Field>
          <Field label={t("Amount")}><input className="input" type="number" step="0.01" value={tr.v.amount} onChange={tr.set("amount")} /></Field>
          <Field label={t("Description")}><input className="input" placeholder={t("e.g. cash deposit to bank")} value={tr.v.description} onChange={tr.set("description")} /></Field>
        </div>
      </Modal>
    </>
  );
}
