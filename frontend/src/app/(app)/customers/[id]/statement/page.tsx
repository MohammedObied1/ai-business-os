"use client";
import { useParams, useRouter } from "next/navigation";
import { useApi } from "@/lib/hooks";
import { date, money } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { DateRange, WhatsAppButton, useMonthRange } from "@/components/money";

/** Customer account statement (كشف حساب), printable. */
export default function CustomerStatement() {
  const { t, lang } = useT();
  const router = useRouter();
  const { company } = useSession();
  const { id } = useParams<{ id: string }>();
  const r = useMonthRange();
  const { data } = useApi<any>(`/api/customers/${id}/statement?start=${r.start}&end=${r.end}`, [r.start, r.end]);
  const kind = (k: string) => t(`st.${k}`) === `st.${k}` ? k : t(`st.${k}`);

  return (
    <>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3 print:hidden">
        <button className="link -ms-2" onClick={() => router.back()}>{lang === "ar" ? "→" : "←"} {t("Back")}</button>
        <DateRange start={r.start} end={r.end} onChange={r.set} />
        <div className="flex gap-2">
          {data && <WhatsAppButton phone={data.customer.phone} text={t("Statement message", { name: data.customer.name, amount: money(data.closing, undefined, 2), company: company?.name ?? "" })} />}
          <button className="btn-ghost" onClick={() => window.print()}>🖨 {t("Print / PDF")}</button>
        </div>
      </div>
      {!data ? <div className="text-sm text-slate">{t("Loading…")}</div> : (
        <article className="panel mx-auto max-w-4xl p-8 print:max-w-none print:border-0 print:p-0">
          <header className="mb-6 flex flex-wrap justify-between gap-4 border-b border-line pb-4">
            <div><div className="text-xl font-bold">{company?.name}</div><div className="text-sm text-slate">{company?.phone}</div></div>
            <div className="text-end">
              <div className="text-2xl font-light text-signal">{t("Account statement")}</div>
              <div className="font-semibold">{data.customer.name}</div>
              <div className="text-sm text-slate">{date(r.start)} – {date(r.end)}</div>
            </div>
          </header>
          <table className="w-full text-sm">
            <thead><tr className="border-y border-line bg-paper/60 text-xs text-slate">
              <th className="px-2 py-2 text-start">{t("Date")}</th><th className="px-2 py-2 text-start">{t("Number")}</th><th className="px-2 py-2 text-start">{t("Details")}</th>
              <th className="px-2 py-2 text-end">{t("Debit (owes)")}</th><th className="px-2 py-2 text-end">{t("Credit (paid)")}</th><th className="px-2 py-2 text-end">{t("Balance")}</th>
            </tr></thead>
            <tbody>
              <tr className="border-b border-line/60 bg-paper/30"><td className="px-2 py-2" colSpan={5}>{t("Opening balance")}</td><td className="num px-2 py-2 text-end font-medium">{money(data.opening, undefined, 2)}</td></tr>
              {data.rows.map((x: any, i: number) => (
                <tr key={i} className="border-b border-line/60">
                  <td className="px-2 py-2">{date(x.date)}</td><td className="px-2 py-2"><span dir="ltr">{x.number}</span></td><td className="px-2 py-2">{kind(x.kind)}</td>
                  <td className="num px-2 py-2 text-end">{x.debit ? money(x.debit, undefined, 2) : ""}</td><td className="num px-2 py-2 text-end text-moss">{x.credit ? money(x.credit, undefined, 2) : ""}</td>
                  <td className="num px-2 py-2 text-end">{money(x.balance, undefined, 2)}</td>
                </tr>
              ))}
              <tr className="font-semibold"><td className="px-2 py-3" colSpan={3}>{t("Total")}</td><td className="num px-2 py-3 text-end">{money(data.total_debit, undefined, 2)}</td>
                <td className="num px-2 py-3 text-end">{money(data.total_credit, undefined, 2)}</td><td className="num px-2 py-3 text-end" /></tr>
            </tbody>
          </table>
          <div className={`mt-4 flex justify-end`}><div className={`rounded-lg px-4 py-2 text-lg font-bold ${data.closing > 0.009 ? "bg-rust-soft text-rust" : "bg-moss-soft text-moss"}`}>{t("Balance due")}: {money(data.closing, undefined, 2)}</div></div>
        </article>
      )}
    </>
  );
}
