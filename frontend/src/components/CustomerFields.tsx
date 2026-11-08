"use client";
import { useApi } from "@/lib/hooks";
import { useT } from "@/lib/i18n";
import { Field } from "./ui";

/** Price list, sales rep and visit days — shared by the new-customer and edit-customer forms. */
export function CustomerExtraFields({ v, onChange }: { v: { price_list_id: number | null; assigned_user_id: number | null; visit_days: string }; onChange: (patch: any) => void }) {
  const { t, lang } = useT();
  const lists = useApi<any[]>("/api/price-lists");
  const users = useApi<any[]>("/api/users");
  const days = (v.visit_days || "").split(",").filter(Boolean);
  // Python weekday numbers: Monday = 0 … Sunday = 6
  const names = lang === "ar" ? ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"] : ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const order = [5, 6, 0, 1, 2, 3, 4];
  const toggle = (d: string) => onChange({ visit_days: (days.includes(d) ? days.filter((x) => x !== d) : [...days, d]).sort().join(",") });
  return (
    <>
      <Field label={t("Price list")}><select className="input" value={v.price_list_id ?? ""} onChange={(e) => onChange({ price_list_id: e.target.value ? +e.target.value : null })}>
        <option value="">{t("Normal prices")}</option>{lists.data?.filter((p) => p.is_active).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
      <Field label={t("Sales rep")}><select className="input" value={v.assigned_user_id ?? ""} onChange={(e) => onChange({ assigned_user_id: e.target.value ? +e.target.value : null })}>
        <option value="">—</option>{users.data?.filter((u) => u.is_active).map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}</select></Field>
      <div className="col-span-2"><Field label={t("Visit days (for the sales rep)")}>
        <div className="flex flex-wrap gap-1">{order.map((d) => (
          <button key={d} type="button" onClick={() => toggle(String(d))} className={`rounded-md border px-2 py-1 text-xs ${days.includes(String(d)) ? "border-signal bg-signal-soft text-signal" : "border-line text-slate"}`}>{names[d]}</button>
        ))}</div></Field></div>
    </>
  );
}
