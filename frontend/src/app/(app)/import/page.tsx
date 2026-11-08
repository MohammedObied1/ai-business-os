"use client";
import { useRef, useState } from "react";
import { api, download, upload } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { date } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { Badge, PageTitle, Table, toast } from "@/components/ui";

const TYPES = [
  { key: "products", label: "Products", hint: "Import products hint", icon: "📦" },
  { key: "customers", label: "Customers", hint: "Import customers hint", icon: "👥" },
  { key: "suppliers", label: "Suppliers", hint: "Import suppliers hint", icon: "🚚" },
  { key: "expenses", label: "Expenses", hint: "Import expenses hint", icon: "🧾" },
];
const EXPORTS = [["products", "Products"], ["customers", "Customers"], ["suppliers", "Suppliers"], ["expenses", "Expenses"], ["invoices", "Invoices"], ["sales", "Sales orders"]];

const FIELD: Record<string, string> = {
  sku: "SKU / code", name: "Name", category: "Category", unit: "Unit", cost_price: "Cost price", sale_price: "Sale price", min_stock: "Minimum stock",
  supplier_lead_time_days: "Supplier delivery (days)", opening_stock: "Opening stock", warehouse: "Warehouse", phone: "Phone", email: "Email",
  address: "City / address", customer_type: "Type", credit_limit: "Credit limit", opening_balance: "Opening balance", notes: "Notes",
  lead_time_days: "Delivery time (days)", payment_terms_days: "Payment within (days)", expense_date: "Date", description: "Description", amount: "Amount",
};

type Result = { dry_run: boolean; rows: number; created: number; updated: number; errors: { row: number; message: string }[]; preview: Record<string, any>[] };

export default function ImportPage() {
  const { t, lang } = useT();
  const [entity, setEntity] = useState("products");
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const reset = () => { setFile(null); setResult(null); if (input.current) input.current.value = ""; };
  const check = async (f: File) => {
    setFile(f); setResult(null); setBusy(true);
    try { setResult(await upload(`/api/data/import/${entity}?dry_run=true&lang=${lang}`, f)); } catch (e: any) { toast(e.message, "bad"); reset(); } finally { setBusy(false); }
  };
  const commit = async () => {
    if (!file) return;
    setBusy(true);
    try {
      const r: Result = await upload(`/api/data/import/${entity}?dry_run=false&lang=${lang}`, file);
      toast(t("Imported: {a} new, {b} updated", { a: r.created, b: r.updated }));
      reset(); batches.reload();
    } catch (e: any) { toast(e.message, "bad"); } finally { setBusy(false); }
  };
  const get = (path: string) => download(path).catch((e) => toast(e.message, "bad"));
  const cols = result?.preview.length ? Object.keys(result.preview[0]) : [];
  const batches = useApi<any[]>("/api/data/import/batches");
  const undo = async (id: number) => {
    if (!confirm(t("Undo this import? Rows already used elsewhere (a sale, a purchase…) are left as they are."))) return;
    try { const r = await api(`/api/data/import/batches/${id}/rollback`, { method: "POST" });
      toast(r.kept_in_use.length ? t("Removed {n}, {k} kept (already in use)", { n: r.removed, k: r.kept_in_use.length }) : t("Removed {n} rows", { n: r.removed }));
      batches.reload();
    } catch (e: any) { toast(e.message, "bad"); }
  };

  return (
    <>
      <PageTitle title={t("Import & export")} help={t("Import help")} />

      <section className="panel p-5">
        <h2 className="text-lg font-semibold">1. {t("What do you want to import?")}</h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {TYPES.map((x) => (
            <button key={x.key} onClick={() => { setEntity(x.key); reset(); }} className={`rounded-xl border p-4 text-start transition ${entity === x.key ? "border-signal bg-signal-soft ring-1 ring-signal" : "border-line hover:border-signal/60"}`}>
              <div className="text-2xl">{x.icon}</div>
              <div className="mt-1 font-semibold">{t(x.label)}</div>
              <div className="mt-0.5 text-xs leading-relaxed text-slate">{t(x.hint)}</div>
            </button>
          ))}
        </div>

        <h2 className="mt-6 text-lg font-semibold">2. {t("Download the template and fill it")}</h2>
        <p className="mt-1 text-sm text-slate">{t("Template help")}</p>
        <button className="btn-ghost mt-3" onClick={() => get(`/api/data/template/${entity}?lang=${lang}`)}>⬇ {t("Download Excel template")}</button>

        <h2 className="mt-6 text-lg font-semibold">3. {t("Upload the file")}</h2>
        <label className={`mt-3 flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-8 text-center ${file ? "border-signal bg-signal-soft/40" : "border-line hover:border-signal/60"}`}
          onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files?.[0]; if (f) check(f); }}>
          <input ref={input} type="file" className="hidden" accept=".xlsx,.xlsm,.csv" onChange={(e) => { const f = e.target.files?.[0]; if (f) check(f); }} />
          <div className="text-3xl">📄</div>
          <div className="mt-2 font-medium">{file ? file.name : t("Click to choose a file, or drop it here")}</div>
          <div className="text-xs text-slate">Excel (.xlsx) / CSV</div>
        </label>

        {busy && <div className="mt-4 text-sm text-slate">{t("Checking the file…")}</div>}

        {result && (
          <div className="mt-6">
            <h2 className="text-lg font-semibold">4. {t("Check before saving")}</h2>
            <div className="mt-3 flex flex-wrap gap-2 text-sm">
              <Badge tone="good">{t("{n} new", { n: result.created })}</Badge>
              <Badge tone="info">{t("{n} will be updated", { n: result.updated })}</Badge>
              {result.errors.length > 0 && <Badge tone="bad">{t("{n} rows with problems", { n: result.errors.length })}</Badge>}
            </div>
            {result.errors.length > 0 && (
              <div className="mt-3 rounded-lg bg-rust-soft p-3 text-sm text-rust">
                <div className="mb-1 font-medium">{t("These rows will be skipped:")}</div>
                <ul className="max-h-48 space-y-0.5 overflow-y-auto">{result.errors.map((e) => <li key={e.row}>{t("Row")} {e.row}: <span dir="auto">{e.message}</span></li>)}</ul>
              </div>
            )}
            {cols.length > 0 && (
              <div className="mt-3 overflow-x-auto rounded-lg border border-line">
                <table className="w-full text-sm">
                  <thead><tr>{cols.map((c) => <th key={c} className="th">{t(FIELD[c] ?? c)}</th>)}</tr></thead>
                  <tbody>{result.preview.map((r, i) => <tr key={i}>{cols.map((c) => <td key={c} className="td">{r[c] == null ? "—" : String(r[c])}</td>)}</tr>)}</tbody>
                </table>
              </div>
            )}
            <div className="mt-4 flex gap-2">
              <button className="btn-primary" disabled={busy || result.created + result.updated === 0} onClick={commit}>✓ {t("Import now")}</button>
              <button className="btn-ghost" onClick={reset}>{t("Cancel")}</button>
            </div>
          </div>
        )}
      </section>

      <section className="panel mt-6 p-5">
        <h2 className="text-lg font-semibold">{t("Export to Excel")}</h2>
        <p className="mt-1 text-sm text-slate">{t("Export help")}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          {EXPORTS.map(([k, label]) => <span key={k} className="inline-flex overflow-hidden rounded-lg border border-line">
            <button className="px-3 py-1.5 text-sm hover:bg-paper" onClick={() => get(`/api/data/export/${k}?lang=${lang}`)}>⬇ {t(label)}</button>
            <button className="border-s border-line px-2 py-1.5 text-xs text-slate hover:bg-paper" title="CSV" onClick={() => get(`/api/data/export/${k}?lang=${lang}&format=csv`)}>CSV</button>
          </span>)}
        </div>
      </section>

      {!!batches.data?.length && (
        <section className="panel mt-6 p-5">
          <h2 className="text-lg font-semibold">{t("Recent imports")}</h2>
          <p className="mt-1 text-sm text-slate">{t("Recent imports help")}</p>
          <div className="mt-3"><Table rows={batches.data} cols={[
            { h: t("File"), c: (b: any) => <span dir="ltr">{b.filename ?? "—"}</span> }, { h: t("Type"), c: (b: any) => t(TYPES.find((x) => x.key === b.entity)?.label ?? b.entity) },
            { h: t("Created"), c: (b: any) => b.created_count, end: true }, { h: t("Updated"), c: (b: any) => b.updated_count, end: true },
            { h: t("When"), c: (b: any) => date(b.created_at) }, { h: t("By"), c: (b: any) => b.user ?? "—" },
            { h: "", c: (b: any) => b.rolled_back_at
              ? <Badge tone="neutral">{t("Undone")} {b.rollback_report?.kept_in_use?.length ? `(${b.rollback_report.kept_in_use.length} ${t("kept")})` : ""}</Badge>
              : b.created_count > 0 && <button className="link-danger text-sm" onClick={() => undo(b.id)}>{t("Undo")}</button> },
          ]} /></div>
        </section>
      )}
    </>
  );
}
