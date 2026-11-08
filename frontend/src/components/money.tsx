"use client";
import { useEffect, useState } from "react";
import { useApi } from "@/lib/hooks";
import { money } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { Field } from "./ui";

export type PaymentValue = { method: string; account_id: number | null; reference: string; cheque: { number: string; bank: string; due_date: string } };
export const emptyPayment = (): PaymentValue => ({ method: "cash", account_id: null, reference: "", cheque: { number: "", bank: "", due_date: new Date().toISOString().slice(0, 10) } });

/** Converts the form value into the API shape ({method, account_id, reference, cheque?}). */
export function paymentPayload(v: PaymentValue) {
  return { method: v.method, account_id: v.method === "cheque" ? null : v.account_id, reference: v.reference || null, cheque: v.method === "cheque" ? v.cheque : null };
}

/** Method + account (cash box / bank) + cheque details. Used for customer receipts, supplier payments and the POS. */
export function PaymentFields({ value, onChange, direction = "in" }: { value: PaymentValue; onChange: (v: PaymentValue) => void; direction?: "in" | "out" }) {
  const { t } = useT();
  const { data: accounts } = useApi<any[]>("/api/accounts");
  const active = accounts?.filter((a) => a.is_active) ?? [];
  // pick a sensible default account for the chosen method
  useEffect(() => {
    if (!active.length || value.method === "cheque") return;
    const wanted = value.method === "cash" ? "cash" : "bank";
    const current = active.find((a) => a.id === value.account_id);
    if (!current || (current.kind !== wanted && active.some((a) => a.kind === wanted))) {
      const pick = active.find((a) => a.kind === wanted) ?? active[0];
      onChange({ ...value, account_id: pick.id });
    }
  }, [accounts, value.method]); // eslint-disable-line react-hooks/exhaustive-deps
  const set = (patch: Partial<PaymentValue>) => onChange({ ...value, ...patch });
  const setCheque = (patch: Partial<PaymentValue["cheque"]>) => onChange({ ...value, cheque: { ...value.cheque, ...patch } });
  return (
    <div className="grid grid-cols-2 gap-3">
      <Field label={t("Method")}>
        <select className="input" value={value.method} onChange={(e) => set({ method: e.target.value })}>
          {["cash", "bank", "card", "cheque"].map((m) => <option key={m} value={m}>{t(m)}</option>)}
        </select>
      </Field>
      {value.method !== "cheque" ? (
        <Field label={direction === "in" ? t("Into") : t("From account")}>
          <select className="input" value={value.account_id ?? ""} onChange={(e) => set({ account_id: +e.target.value })}>
            {active.map((a) => <option key={a.id} value={a.id}>{a.name} ({money(a.balance)})</option>)}
          </select>
        </Field>
      ) : (
        <Field label={t("Cheque number")}><input className="input" dir="ltr" value={value.cheque.number} onChange={(e) => setCheque({ number: e.target.value })} /></Field>
      )}
      {value.method === "cheque" && <>
        <Field label={t("Bank")}><input className="input" value={value.cheque.bank} onChange={(e) => setCheque({ bank: e.target.value })} /></Field>
        <Field label={t("Cheque date (due)")}><input className="input" type="date" value={value.cheque.due_date} onChange={(e) => setCheque({ due_date: e.target.value })} /></Field>
      </>}
      <div className={value.method === "cheque" ? "col-span-2" : "col-span-2"}>
        <Field label={t("Reference (cheque no., transfer no.)")}><input className="input" value={value.reference} onChange={(e) => set({ reference: e.target.value })} /></Field>
      </div>
    </div>
  );
}

/** Start/end date inputs with quick presets. */
export function DateRange({ start, end, onChange }: { start: string; end: string; onChange: (s: string, e: string) => void }) {
  const { t } = useT();
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  const now = new Date();
  const presets: [string, () => [string, string]][] = [
    ["This month", () => [iso(new Date(now.getFullYear(), now.getMonth(), 1)), iso(now)]],
    ["Last month", () => [iso(new Date(now.getFullYear(), now.getMonth() - 1, 1)), iso(new Date(now.getFullYear(), now.getMonth(), 0))]],
    ["This year", () => [iso(new Date(now.getFullYear(), 0, 1)), iso(now)]],
  ];
  return (
    <div className="flex flex-wrap items-end gap-2">
      <Field label={t("From")}><input className="input" type="date" value={start} onChange={(e) => onChange(e.target.value, end)} /></Field>
      <Field label={t("To")}><input className="input" type="date" value={end} onChange={(e) => onChange(start, e.target.value)} /></Field>
      {presets.map(([label, fn]) => <button key={label} className="btn-ghost !py-2" onClick={() => { const [s, e] = fn(); onChange(s, e); }}>{t(label)}</button>)}
    </div>
  );
}

export function useMonthRange() {
  const now = new Date();
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  const [range, setRange] = useState({ start: iso(new Date(now.getFullYear(), now.getMonth(), 1)), end: iso(now) });
  return { ...range, set: (start: string, end: string) => setRange({ start, end }) };
}

/** wa.me link. Local numbers (05…) get the default country code. */
export function whatsappLink(phone: string | null | undefined, text: string, countryCode = "970") {
  let p = (phone ?? "").replace(/[^\d+]/g, "");
  if (p.startsWith("+")) p = p.slice(1);
  else if (p.startsWith("00")) p = p.slice(2);
  else if (p.startsWith("0")) p = countryCode + p.slice(1);
  return `https://wa.me/${p}?text=${encodeURIComponent(text)}`;
}

export function WhatsAppButton({ phone, text, label, className = "", anyone = false }: { phone?: string | null; text: string; label?: string; className?: string; anyone?: boolean }) {
  const { t } = useT();
  if (!phone && !anyone) return null; // anyone: WhatsApp asks who to send it to
  return (
    <a href={whatsappLink(phone, text)} target="_blank" rel="noreferrer" className={`btn inline-flex bg-[#25D366] text-white hover:bg-[#1ebe5b] ${className}`}>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden><path d="M12 2a10 10 0 00-8.6 15.1L2 22l5-1.3A10 10 0 1012 2zm0 18.2a8.2 8.2 0 01-4.2-1.2l-.3-.2-3 .8.8-2.9-.2-.3A8.2 8.2 0 1112 20.2zm4.5-6.1c-.2-.1-1.5-.7-1.7-.8s-.4-.1-.6.1-.7.8-.8 1-.3.2-.5.1a6.7 6.7 0 01-3.3-2.9c-.3-.4.3-.4.7-1.3.1-.2 0-.3 0-.4l-.8-1.8c-.2-.5-.4-.4-.6-.4h-.5a1 1 0 00-.7.3 3 3 0 00-.9 2.2 5.2 5.2 0 001.1 2.7 11.8 11.8 0 004.5 4c1.7.7 2.3.8 3.2.6a2.7 2.7 0 001.8-1.2 2.2 2.2 0 00.1-1.2c0-.1-.2-.2-.4-.3z" /></svg>
      {label ?? t("WhatsApp")}
    </a>
  );
}
