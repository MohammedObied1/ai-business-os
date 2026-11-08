"use client";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { API_URL } from "@/lib/api";
import { setFormatCurrency } from "@/lib/format";
import { LangSwitch, useT } from "@/lib/i18n";
import InvoiceView from "@/components/InvoiceView";

/** Public invoice page opened from a WhatsApp / shared link. No login needed. */
export default function SharedInvoice() {
  const { t } = useT();
  const { token } = useParams<{ token: string }>();
  const [d, setD] = useState<any>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    fetch(`${API_URL}/api/public/invoices/${token}`).then((r) => (r.ok ? r.json() : Promise.reject())).then((x) => { setFormatCurrency(x.company.currency); setD(x); }).catch(() => setError(true));
  }, [token]);

  return (
    <main className="min-h-screen px-4 py-6">
      <div className="mx-auto mb-4 flex max-w-3xl justify-end gap-2 print:hidden">
        <LangSwitch />
        {d && <button className="btn-primary" onClick={() => window.print()}>🖨 {t("Print / PDF")}</button>}
      </div>
      {error ? <div className="panel mx-auto max-w-md p-8 text-center text-slate">{t("This invoice link is not valid.")}</div>
        : !d ? <div className="text-center text-sm text-slate">{t("Loading…")}</div> : <InvoiceView d={d} />}
    </main>
  );
}
