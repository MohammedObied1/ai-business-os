"use client";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, logoUrl } from "@/lib/api";
import { date, money } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";

/** Printable voucher: receipt (سند قبض), payment (سند صرف) or transfer. */
export default function Voucher() {
  const { t, lang } = useT();
  const router = useRouter();
  const { company } = useSession();
  const { number } = useParams<{ number: string }>();
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        if (number.startsWith("RV")) {
          try { const r = await api(`/api/sales/receipts/${number}`); setData({ kind: "customer", ...r }); return; } catch {}
        }
        const v = await api(`/api/vouchers/${number}`);
        setData({ kind: "general", ...v });
      } catch (e: any) { setError(e.message); }
    })();
  }, [number]);

  if (error) return <div className="text-rust">{error}</div>;
  if (!data) return <div className="text-sm text-slate">{t("Loading…")}</div>;

  const isIn = number.startsWith("RV");
  const title = number.startsWith("TR") ? t("Transfer") : isIn ? t("Receipt voucher") : t("Payment voucher");
  const rows = data.kind === "general" ? data.rows : [];
  const amount = data.kind === "customer" ? data.amount : Math.abs(rows.find((r: any) => (isIn ? r.amount > 0 : r.amount < 0))?.amount ?? rows[0]?.amount ?? 0);
  const first = rows[0];
  const party = data.kind === "customer" ? data.customer?.name : first?.party_name;

  return (
    <>
      <div className="mb-4 flex justify-between print:hidden">
        <button className="link -ms-2" onClick={() => router.back()}>{lang === "ar" ? "→" : "←"} {t("Back")}</button>
        <button className="btn-ghost" onClick={() => window.print()}>🖨 {t("Print / PDF")}</button>
      </div>
      <article className="panel mx-auto max-w-2xl p-8 print:max-w-none print:border-0">
        <header className="flex items-start justify-between gap-4 border-b border-line pb-5">
          <div className="flex items-center gap-3">
            {company?.logo_path && <img src={logoUrl(company.id, company.logo_path)} alt="" className="h-14 w-14 object-contain" />}
            <div><div className="text-xl font-bold">{company?.name}</div><div className="text-sm text-slate">{company?.phone}</div></div>
          </div>
          <div className="text-end">
            <div className="text-2xl font-light text-signal">{title}</div>
            <div className="font-semibold" dir="ltr">{number}</div>
            <div className="text-sm text-slate">{date(data.kind === "customer" ? data.date : first?.date)}</div>
          </div>
        </header>
        {data.status === "bounced" && <div className="mt-4 rounded-lg bg-rust-soft p-2 text-center font-semibold text-rust">{t("Cheque bounced")}</div>}
        <dl className="mt-6 space-y-4 text-base">
          {party && <div className="flex gap-3 border-b border-dashed border-line pb-3"><dt className="w-40 text-slate">{isIn ? t("Received from") : t("Paid to")}</dt><dd className="font-semibold">{party}</dd></div>}
          <div className="flex gap-3 border-b border-dashed border-line pb-3"><dt className="w-40 text-slate">{t("Amount")}</dt><dd className="text-xl font-bold">{money(amount, undefined, 2)}</dd></div>
          {data.kind === "customer" && <>
            <div className="flex gap-3 border-b border-dashed border-line pb-3"><dt className="w-40 text-slate">{t("Method")}</dt><dd>{t(data.method)}{data.cheque && <> — {t("Cheque")} <span dir="ltr">{data.cheque.number}</span> · {data.cheque.bank} · {date(data.cheque.due_date)}</>}</dd></div>
            <div className="flex gap-3 border-b border-dashed border-line pb-3"><dt className="w-40 text-slate">{t("For invoices")}</dt><dd>{data.invoices.map((i: any) => <div key={i.number}><span dir="ltr">{i.number}</span>: {money(i.amount, undefined, 2)}</div>)}</dd></div>
          </>}
          {data.kind === "general" && rows.map((r: any) => (
            <div key={r.id} className="flex gap-3 border-b border-dashed border-line pb-3"><dt className="w-40 text-slate">{r.account}</dt><dd>{r.description || r.reference || ""} <span className={r.amount < 0 ? "text-rust" : "text-moss"}>({money(r.amount, undefined, 2)})</span></dd></div>
          ))}
        </dl>
        <footer className="mt-16 grid grid-cols-2 gap-10 text-center text-sm text-slate">
          <div className="border-t border-line pt-2">{t("Received by")}</div>
          <div className="border-t border-line pt-2">{t("Signature")}</div>
        </footer>
      </article>
    </>
  );
}
