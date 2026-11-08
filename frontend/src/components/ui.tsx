"use client";
import { ReactNode, useEffect, useState } from "react";
import { useT } from "@/lib/i18n";

export function PageTitle({ title, help, actions }: { title: string; help?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div className="max-w-2xl">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {help && <p className="mt-1.5 text-sm leading-relaxed text-slate">{help}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

type Tone = "good" | "bad" | "neutral";
export function StatCard({ label, value, note, tone = "neutral" }: { label: string; value: string; note?: string; tone?: Tone }) {
  const c = tone === "good" ? "text-moss" : tone === "bad" ? "text-rust" : "text-slate";
  return (
    <div className="panel p-4">
      <div className="text-sm text-slate">{label}</div>
      <div className="num mt-1 text-2xl font-semibold">{value}</div>
      {note && <div className={`num mt-1 text-sm ${c}`}>{note}</div>}
    </div>
  );
}

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "good" | "warn" | "bad" | "neutral" | "info" }) {
  const map = { good: "bg-moss-soft text-moss", warn: "bg-amber-soft text-amber", bad: "bg-rust-soft text-rust", info: "bg-signal-soft text-signal", neutral: "bg-paper text-slate" };
  return <span className={`inline-block whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ${map[tone]}`}>{children}</span>;
}

export function statusTone(s: string): "good" | "warn" | "bad" | "neutral" | "info" {
  if (["paid", "delivered", "received", "approved", "LOW", "healthy", "done", "active", "indexed"].includes(s)) return "good";
  if (["partial", "ordered", "confirmed", "MEDIUM", "attention", "warning"].includes(s)) return "warn";
  if (["overdue", "cancelled", "HIGH", "critical", "inactive"].includes(s)) return "bad";
  if (["request", "quotation", "open", "info"].includes(s)) return "info";
  return "neutral";
}

/** Status pill with the value translated. */
export function Status({ value }: { value: string }) {
  const { t } = useT();
  return <Badge tone={statusTone(value)}>{t(value)}</Badge>;
}

export function Tabs<K extends string>({ tabs, value, onChange }: { tabs: readonly K[]; value: K; onChange: (k: K) => void }) {
  const { t } = useT();
  return (
    <div className="mb-4 inline-flex flex-wrap gap-1 rounded-lg border border-line bg-white p-1 text-sm">
      {tabs.map((k) => (
        <button key={k} onClick={() => onChange(k)} className={`rounded-md px-4 py-1.5 ${value === k ? "bg-signal text-white" : "text-slate hover:bg-paper hover:text-ink"}`}>{t(k)}</button>
      ))}
    </div>
  );
}

type Col<T> = { h: string; c: (r: T) => ReactNode; end?: boolean };

export function Table<T>({ rows, cols, empty, onRow, pageSize = 25 }: { rows: T[] | null; cols: Col<T>[]; empty?: string; onRow?: (r: T) => void; pageSize?: number }) {
  const { t } = useT();
  const [shown, setShown] = useState(pageSize);
  if (!rows) return <div className="p-6 text-sm text-slate">{t("Loading…")}</div>;
  if (!rows.length) return <div className="p-6 text-sm text-slate">{empty ?? t("Nothing here yet.")}</div>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead><tr>{cols.map((c, i) => <th key={i} className={`th ${c.end ? "text-end" : ""}`}>{c.h}</th>)}</tr></thead>
        <tbody>
          {rows.slice(0, shown).map((r, i) => (
            <tr key={i} onClick={onRow ? () => onRow(r) : undefined} className={onRow ? "cursor-pointer hover:bg-signal-soft/40" : ""}>
              {cols.map((c, j) => <td key={j} className={`td ${c.end ? "num text-end" : ""}`}>{c.c(r)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > shown && (
        <div className="flex items-center justify-center gap-3 p-3 text-sm text-slate">
          {t("Showing {a} of {b}", { a: shown, b: rows.length })}
          <button className="link" onClick={() => setShown(shown + pageSize)}>{t("Show more")}</button>
        </div>
      )}
    </div>
  );
}

/** A table fed page by page from the server (see usePaged). */
export function PagedTable<T>({ paged, cols, empty, onRow }: { paged: { rows: T[] | null; total: number; loading: boolean; hasMore: boolean; loadMore: () => void };
  cols: Col<T>[]; empty?: string; onRow?: (r: T) => void }) {
  const { t } = useT();
  return (
    <>
      <Table rows={paged.rows} cols={cols} empty={empty} onRow={onRow} pageSize={100000} />
      {paged.rows && paged.rows.length > 0 && (
        <div className="flex items-center justify-center gap-3 border-t border-line/60 p-3 text-sm text-slate">
          {t("Showing {a} of {b}", { a: paged.rows.length, b: paged.total })}
          {paged.hasMore && <button className="link" disabled={paged.loading} onClick={paged.loadMore}>{paged.loading ? "…" : t("Show more")}</button>}
        </div>
      )}
    </>
  );
}

export function Modal({ title, open, onClose, children, onSave, saveLabel }: { title: string; open: boolean; onClose: () => void; children: ReactNode; onSave?: () => void; saveLabel?: string }) {
  const { t } = useT();
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/40 p-4 pt-16" onClick={onClose}>
      <div className="panel w-full max-w-lg p-5 shadow-lg" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <div className="mb-4 flex items-center justify-between"><h2 className="text-lg font-semibold">{title}</h2><button onClick={onClose} className="rounded-md px-2 text-slate hover:bg-paper hover:text-ink" aria-label={t("Close")}>✕</button></div>
        {children}
        {onSave && <div className="mt-5 flex justify-end gap-2"><button className="btn-ghost" onClick={onClose}>{t("Cancel")}</button><button className="btn-primary" onClick={onSave}>{saveLabel ?? t("Save")}</button></div>}
      </div>
    </div>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="block"><span className="label">{label}</span>{children}</label>;
}

export function useForm<T extends Record<string, any>>(initial: T) {
  const [v, setV] = useState<T>(initial);
  const set = (k: keyof T) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
    const t = e.target as HTMLInputElement;
    setV({ ...v, [k]: t.type === "number" ? (t.value === "" ? "" : Number(t.value)) : t.type === "checkbox" ? t.checked : t.value });
  };
  return { v, set, reset: () => setV(initial), setV };
}

/** Side panel for viewing a record's details. */
export function Drawer({ title, open, onClose, children, actions }: { title: ReactNode; open: boolean; onClose: () => void; children: ReactNode; actions?: ReactNode }) {
  const { t } = useT();
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-ink/40" onClick={onClose}>
      <aside className="flex h-full w-full max-w-xl flex-col bg-white shadow-xl" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-4">
          <h2 className="min-w-0 truncate text-lg font-semibold">{title}</h2>
          <div className="flex shrink-0 items-center gap-2">{actions}<button onClick={onClose} className="rounded-md px-2 text-slate hover:bg-paper hover:text-ink" aria-label={t("Close")}>✕</button></div>
        </div>
        <div className="flex-1 overflow-y-auto p-5">{children}</div>
      </aside>
    </div>
  );
}

/** Label/value rows inside a drawer. */
export function InfoList({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
      {items.map(([k, v]) => <div key={k}><dt className="text-xs text-slate">{k}</dt><dd className="mt-0.5 font-medium">{v ?? "—"}</dd></div>)}
    </dl>
  );
}

/** Fire-and-forget notification: toast("Saved"). Rendered by <ToastHost/> in the root layout. */
export function toast(message: string, tone: "good" | "bad" = "good") {
  if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent("app-toast", { detail: { message, tone } }));
}

export function ToastHost() {
  const { tx } = useT();
  const [items, setItems] = useState<{ id: number; message: string; tone: string }[]>([]);
  useEffect(() => {
    const on = (e: Event) => {
      const d = (e as CustomEvent).detail;
      const id = Date.now() + Math.random();
      setItems((x) => [...x, { id, ...d }]);
      setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), 3500);
    };
    window.addEventListener("app-toast", on);
    return () => window.removeEventListener("app-toast", on);
  }, []);
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-4 z-[60] flex flex-col items-center gap-2">
      {items.map((i) => <div key={i.id} className={`rounded-lg px-4 py-2 text-sm font-medium text-white shadow-lg ${i.tone === "bad" ? "bg-rust" : "bg-ink"}`}>{tx(i.message)}</div>)}
    </div>
  );
}

/** Runs an async action and reports success / failure as a toast. */
export async function run(fn: () => Promise<unknown>, okMessage?: string): Promise<boolean> {
  try { await fn(); if (okMessage) toast(okMessage); return true; } catch (e: any) { toast(e.message ?? String(e), "bad"); return false; }
}

export function ErrorNote({ error }: { error: string | null }) {
  const { tx } = useT();
  return error ? <div className="mb-3 rounded-lg bg-rust-soft px-3 py-2 text-sm text-rust">{tx(error)}</div> : null;
}
