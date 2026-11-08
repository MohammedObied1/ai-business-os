"use client";
import { useParams, useRouter } from "next/navigation";
import { useApi } from "@/lib/hooks";
import { date, money } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { DateRange, useMonthRange } from "@/components/money";

/** Supplier account statement: what we owe them. */
export default function SupplierStatement() {
  const { t, lang } = useT();
  const router = useRouter();
  const { company } = useSession();
  const { id } = useParams<{ id: string }>();
  const r = useMonthRange();
  const { data } = useApi<any>(`/api/purchasing/suppliers/${id}/statement?start=${r.start}&end=${r.end}`, [r.start, r.end]);
  const kind = (k: string) => t(`st.${k}`) === `st.${k}` ? k : t(`st.${k}`);

  return (
    <>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3 print:hidden">
        <button className="link -ms-2" onClick={() => router.back()}>{lang === "ar" ? "→" : "←"} {t("Back")}</button>
        <DateRange start={r.start} end={r.end} onChange={r.set} />
        <button className="btn-ghost" onClick={() => window.print()}>🖨 {t("Print / PDF")}</button>
      </div>
      {!data ? <div className="text-sm text-slate">{t("Loading…")}</div> : (
        <article className="panel mx-auto max-w-4xl p-8 print:max-w-none print:border-0 print:p-0">
          <header className="mb-6 flex flex-wrap justify-between gap-4 border-b border-line pb-4">
            <div className="text-xl font-bold">{company?.name}</div>
            <div className="text-end">
              <div className="text-2xl font-light text-signal">{t("Supplier statement")}</div>
              <div className="font-semibold">{data.supplier.name}</div>
              <div className="text-sm text-slate">{date(r.start)} – {date(r.end)}</div>
            </div>
          </header>
          <table className="w-full text-sm">
            <thead><tr className="border-y border-line bg-paper/60 text-xs text-slate">
              <th className="px-2 py-2 text-start">{t("Date")}</th><th className="px-2 py-2 text-start">{t("Number")}</th><th className="px-2 py-2 text-start">{t("Details")}</th>
              <th className="px-2 py-2 text-end">{t("We owe")}</th><th className="px-2 py-2 text-end">{t("We paid")}</th><th className="px-2 py-2 text-end">{t("Balance")}</th>
            </tr></thead>
            <tbody>
              <tr className="border-b border-line/60 bg-paper/30"><td className="px-2 py-2" colSpan={5}>{t("Opening balance")}</td><td className="num px-2 py-2 text-end font-medium">{money(data.opening, undefined, 2)}</td></tr>
              {data.rows.map((x: any, i: number) => (
                <tr key={i} className="border-b border-line/60">
                  <td className="px-2 py-2">{date(x.date)}</td><td className="px-2 py-2"><span dir="ltr">{x.number}</span></td><td className="px-2 py-2">{kind(x.kind)}</td>
                  <td className="num px-2 py-2 text-end">{x.amount_owed ? money(x.amount_owed, undefined, 2) : ""}</td><td className="num px-2 py-2 text-end text-moss">{x.paid ? money(x.paid, undefined, 2) : ""}</td>
                  <td className="num px-2 py-2 text-end">{money(x.balance, undefined, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-4 flex justify-end"><div className="rounded-lg bg-paper px-4 py-2 text-lg font-bold">{t("We owe them")}: {money(data.closing, undefined, 2)}</div></div>
        </article>
      )}
    </>
  );
}
