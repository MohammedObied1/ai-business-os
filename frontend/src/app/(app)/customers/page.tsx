"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, download } from "@/lib/api";
import { usePaged } from "@/lib/hooks";
import { money } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { CustomerExtraFields } from "@/components/CustomerFields";
import { ErrorNote, Field, Modal, PageTitle, PagedTable, toast, useForm } from "@/components/ui";
import { useSession } from "@/lib/session";

function ScorePill({ score }: { score: number }) {
  const c = score >= 60 ? "bg-moss-soft text-moss" : score < 30 ? "bg-rust-soft text-rust" : "bg-amber-soft text-amber";
  return <span className={`num inline-block min-w-[2.5rem] rounded-full px-2 py-0.5 text-center text-xs font-semibold ${c}`}>{score}</span>;
}

const EMPTY = { name: "", email: "", phone: "", address: "", customer_type: "business", credit_limit: 0, price_list_id: null as number | null, assigned_user_id: null as number | null, visit_days: "" };

export default function Customers() {
  const router = useRouter();
  const { t, lang } = useT();
  const { can } = useSession();
  const [q, setQ] = useState("");
  const [qq, setQq] = useState("");
  const [mine, setMine] = useState(false);
  useEffect(() => { const h = setTimeout(() => setQq(q.trim()), 300); return () => clearTimeout(h); }, [q]);
  const list = usePaged<any>(`/api/customers?q=${encodeURIComponent(qq)}${mine ? "&assigned_to_me=true" : ""}`, [qq, mine]);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const f = useForm({ ...EMPTY });

  const save = async () => {
    setError(null);
    try { await api("/api/customers", { method: "POST", json: { ...f.v, visit_days: f.v.visit_days || null } }); setOpen(false); f.reset(); list.reload(); toast("Saved"); } catch (e: any) { setError(e.message); }
  };

  return (
    <>
      <PageTitle title={t("Customers")} help={t("Customers help")} actions={<>
        <button className="btn-ghost" onClick={() => download(`/api/data/export/customers?lang=${lang}`).catch((e) => toast(e.message, "bad"))}>⬇ {t("Excel")}</button>
        {can("customers:write") && <button className="btn-primary" onClick={() => { setError(null); f.setV({ ...EMPTY }); setOpen(true); }}>+ {t("New customer")}</button>}</>} />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <input className="input max-w-sm" placeholder={`🔍 ${t("Search by name or phone")}`} value={q} onChange={(e) => setQ(e.target.value)} />
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="accent-signal" checked={mine} onChange={(e) => setMine(e.target.checked)} />{t("My customers only")}</label>
      </div>
      <div className="panel">
        <PagedTable paged={list} empty={t("No customers yet. Add one, or import them from Excel.")} onRow={(r: any) => router.push(`/customers/${r.id}`)} cols={[
          { h: t("Name"), c: (r: any) => <span className="font-medium">{r.name}</span> },
          { h: t("Phone"), c: (r: any) => <span dir="ltr">{r.phone ?? "—"}</span> }, { h: t("City"), c: (r: any) => r.address ?? "—" },
          { h: t("Credit limit"), c: (r: any) => money(r.credit_limit), end: true },
          { h: t("Score"), c: (r: any) => <ScorePill score={r.score} />, end: true },
        ]} />
      </div>
      <Modal title={t("New customer")} open={open} onClose={() => setOpen(false)} onSave={save} saveLabel={t("Save customer")}>
        <ErrorNote error={error} />
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2"><Field label={t("Name")}><input className="input" value={f.v.name} onChange={f.set("name")} /></Field></div>
          <Field label={t("Phone")}><input className="input" dir="ltr" value={f.v.phone} onChange={f.set("phone")} /></Field>
          <Field label={t("Email")}><input className="input" dir="ltr" value={f.v.email} onChange={f.set("email")} /></Field>
          <Field label={t("City / address")}><input className="input" value={f.v.address} onChange={f.set("address")} /></Field>
          <Field label={t("Type")}><select className="input" value={f.v.customer_type} onChange={f.set("customer_type")}><option value="business">{t("Business")}</option><option value="individual">{t("Individual")}</option></select></Field>
          <Field label={t("Credit limit")}><input className="input" type="number" value={f.v.credit_limit} onChange={f.set("credit_limit")} /></Field>
          <CustomerExtraFields v={f.v} onChange={(patch) => f.setV({ ...f.v, ...patch })} />
        </div>
      </Modal>
    </>
  );
}
