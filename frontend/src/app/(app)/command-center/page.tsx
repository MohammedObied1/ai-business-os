"use client";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { money, pct } from "@/lib/format";
import { useT } from "@/lib/i18n";
import Link from "next/link";
import { useSession } from "@/lib/session";
import { WhatsAppButton } from "@/components/money";
import { ErrorNote, StatCard, toast } from "@/components/ui";

function SetupChecklist() {
  const { t, lang } = useT();
  const { company } = useSession();
  const wh = useApi<any[]>("/api/inventory/warehouses");
  const products = useApi<any[]>("/api/inventory/products");
  const customers = useApi<any[]>("/api/customers?limit=1");
  const orders = useApi<any[]>("/api/sales/orders?limit=1");
  if (!wh.data || !products.data || !customers.data || !orders.data) return null;
  const steps: [boolean, string, string, string][] = [
    [!!(company?.phone || company?.address), "Add your company info", "Shown on your invoices", "/company"],
    [wh.data.length > 0, "Add a warehouse", "Where you keep your goods", "/inventory"],
    [products.data.length > 0, "Add your products", "By hand, or all at once from Excel", "/import"],
    [customers.data.length > 0, "Add your customers", "By hand, or all at once from Excel", "/import"],
    [orders.data.length > 0, "Make your first sale", "The reports and AI start working from here", "/sales"],
  ];
  const done = steps.filter((x) => x[0]).length;
  if (done === steps.length) return null;
  return (
    <section className="panel overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 bg-signal px-5 py-4 text-white">
        <div><div className="text-lg font-semibold">{t("Let's set up your company")}</div><div className="text-sm text-white/80">{t("{a} of {b} steps done", { a: done, b: steps.length })}</div></div>
        <div className="h-2 w-40 overflow-hidden rounded-full bg-white/25"><div className="h-full rounded-full bg-white" style={{ width: `${(done / steps.length) * 100}%` }} /></div>
      </div>
      <ol className="divide-y divide-line">
        {steps.map(([ok, title, hint, href], i) => (
          <li key={title}>
            <Link href={href} className="flex items-center gap-4 px-5 py-3 hover:bg-paper">
              <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-sm font-semibold ${ok ? "bg-moss text-white" : "border-2 border-line text-slate"}`}>{ok ? "✓" : i + 1}</span>
              <span className="flex-1"><span className={`block font-medium ${ok ? "text-slate line-through" : ""}`}>{t(title)}</span><span className="block text-xs text-slate">{t(hint)}</span></span>
              {!ok && <span className="text-signal">{lang === "ar" ? "←" : "→"}</span>}
            </Link>
          </li>
        ))}
      </ol>
    </section>
  );
}

const SUGGESTIONS = [
  "How is the business doing?",
  "Which products may stock out?",
  "Who are the top customers this year?",
  "Which products make the most profit?",
  "Which invoices are overdue?",
  "Which customers owe more than 5,000?",
];

type Msg = { role: "user" | "assistant"; content: string };

/** Yesterday in one card — the same text the owner can get by email every morning. */
function DailySummary() {
  const { t } = useT();
  const { can } = useSession();
  const { data } = useApi<any>(can("reports:read") ? "/api/insights/daily" : null);
  if (!data) return null;
  const copy = () => { navigator.clipboard?.writeText(data.text); toast("Copied"); };
  return (
    <section className="panel p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold">☀️ {t("Yesterday at a glance")}</h2>
        <div className="flex gap-2"><button className="btn-ghost !py-1.5" onClick={copy}>{t("Copy")}</button><WhatsAppButton phone={null} anyone text={data.text} className="!py-1.5" /></div>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <div><div className="text-slate">{t("Sales")}</div><div className="font-semibold">{money(data.sales)} <span className="text-xs text-slate">({data.orders})</span></div></div>
        <div><div className="text-slate">{t("Gross profit")}</div><div className="font-semibold">{money(data.gross_profit)}</div></div>
        <div><div className="text-slate">{t("Money in")}</div><div className="font-semibold">{money(data.received)}</div></div>
        <div><div className="text-slate">{t("Expenses")}</div><div className="font-semibold">{money(data.expenses)}</div></div>
      </div>
      <div className="mt-3 flex flex-wrap gap-2 text-xs">
        {data.top_product && <span className="rounded-full bg-paper px-2 py-1">🏆 {data.top_product}</span>}
        {data.overdue_count > 0 && <span className="rounded-full bg-rust-soft px-2 py-1 text-rust">{t("{n} late invoices", { n: data.overdue_count })} · {money(data.overdue_total)}</span>}
        {data.cheques_due > 0 && <span className="rounded-full bg-amber-soft px-2 py-1 text-amber">{t("Cheques due")}: {data.cheques_due}</span>}
        {data.low_stock > 0 && <span className="rounded-full bg-amber-soft px-2 py-1 text-amber">{t("{n} products running low", { n: data.low_stock })}</span>}
        {data.pending_approvals > 0 && <Link href="/approvals" className="rounded-full bg-signal-soft px-2 py-1 text-signal">{t("Waiting for your approval")}: {data.pending_approvals}</Link>}
      </div>
    </section>
  );
}

/** Speak the question (Chrome / Edge / Android). Arabic or English, following the app language. */
function useVoice(lang: string, onText: (s: string) => void) {
  const [listening, setListening] = useState(false);
  const recRef = useRef<any>(null);
  const supported = typeof window !== "undefined" && !!((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition);
  const start = () => {
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR) return;
    if (listening) { recRef.current?.stop(); return; }
    const rec = new SR();
    rec.lang = lang === "ar" ? "ar-JO" : "en-US";
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    rec.onresult = (e: any) => onText(e.results[0][0].transcript);
    rec.onend = () => setListening(false);
    rec.onerror = () => setListening(false);
    recRef.current = rec;
    setListening(true);
    rec.start();
  };
  return { supported, listening, start };
}

export default function Home() {
  const { t, lang } = useT();
  const cc = useApi<any>(`/api/command-center?lang=${lang}`);
  const { data: me } = useApi<any>("/api/auth/me");
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const voice = useVoice(lang, (text) => ask(text));
  const { can } = useSession();
  const drafts = useApi<any[]>(can("ai.actions") ? "/api/ai/drafts" : null, []);
  const decide = async (id: number, how: "confirm" | "reject") => {
    try { await api(`/api/ai/drafts/${id}/${how}`, { method: "POST" }); toast(how === "confirm" ? "Done" : "Rejected"); drafts.reload(); }
    catch (e: any) { toast(e.message, "bad"); }
  };

  useEffect(() => { api("/api/ai/history?limit=6").then((h: any[]) => setMsgs(h.flatMap((r) => [{ role: "user" as const, content: r.question }, { role: "assistant" as const, content: r.answer }]))).catch(() => {}); }, []);
  // scroll only the chat box, never the page
  useEffect(() => { const box = endRef.current?.parentElement; if (box) box.scrollTop = box.scrollHeight; }, [msgs, busy]);

  const ask = async (question: string) => {
    if (!question.trim() || busy) return;
    setQ(""); setError(null); setBusy(true);
    const history = msgs.slice(-6).map((m) => ({ role: m.role, content: m.content }));
    setMsgs((m) => [...m, { role: "user", content: question }]);
    try {
      const r = await api("/api/ai/ask", { method: "POST", json: { question, history, lang } });
      setMsgs((m) => [...m, { role: "assistant", content: r.answer }]);
      if (Object.values(r.data ?? {}).some((v: any) => v?.draft_id)) drafts.reload();
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  };

  const d = cc.data;
  const k = d?.kpis;
  const health = d?.health as "healthy" | "attention" | "critical" | undefined;
  const healthStyle = health === "healthy" ? "border-moss bg-moss-soft text-moss" : health === "critical" ? "border-rust bg-rust-soft text-rust" : "border-amber bg-amber-soft text-amber";
  const growth = (n: number | null) => (n == null ? undefined : `${pct(n)} ${t("vs last month")}`);
  const tone = (n: number | null) => (n == null ? "neutral" : n >= 0 ? "good" : "bad") as "good" | "bad" | "neutral";

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-semibold tracking-tight">{t("Hello")}{me ? `${lang === "ar" ? "،" : ","} ${me.full_name.split(" ")[0]}` : ""} 👋</h1>

      <SetupChecklist />
      <DailySummary />
      {!!drafts.data?.length && (
        <section className="panel border-s-4 border-s-signal p-5">
          <h2 className="mb-1 text-base font-semibold">🤖 {t("AI drafts waiting for you")}</h2>
          <p className="mb-3 text-sm text-slate">{t("AI drafts help")}</p>
          <ul className="space-y-2">
            {drafts.data.map((d: any) => (
              <li key={d.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-paper p-3">
                <span className="text-sm">{d.summary}</span>
                <div className="flex gap-2">
                  <button className="btn-primary !px-3 !py-1.5 text-sm" onClick={() => decide(d.id, "confirm")}>✓ {t("Confirm")}</button>
                  <button className="btn-ghost !px-3 !py-1.5 text-sm" onClick={() => decide(d.id, "reject")}>{t("Reject")}</button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {!d ? <div className="text-sm text-slate">{cc.error ?? t("Analyzing your business…")}</div> : !d.limited && (
        <>
          <div className={`rounded-xl border-s-4 p-5 ${healthStyle}`}>
            <div className="text-lg font-semibold">{health === "healthy" ? t("Healthy") : health === "critical" ? t("Needs action") : t("Needs attention")}</div>
            <p className="mt-1 text-sm leading-relaxed text-ink/80">{d.summary}</p>
          </div>

          {k && (
            <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
              <StatCard label={t("Sales this month")} value={money(k.revenue)} note={growth(k.revenue_growth_pct)} tone={tone(k.revenue_growth_pct)} />
              <StatCard label={t("Profit this month")} value={money(k.net_profit)} note={growth(k.profit_growth_pct)} tone={tone(k.profit_growth_pct)} />
              <StatCard label={t("Customers owe you")} value={money(k.receivables)} note={t("{n} late invoices", { n: k.overdue_invoices })} tone={k.overdue_invoices ? "bad" : "neutral"} />
              <StatCard label={t("Goods in stock")} value={money(k.inventory_value)} note={t("{n} products running low", { n: k.low_stock_count })} tone={k.low_stock_count ? "bad" : "neutral"} />
            </div>
          )}
        </>
      )}

      <div className="grid gap-6 lg:grid-cols-5">
        <section className="lg:col-span-2">
          <h2 className="mb-3 text-lg font-semibold">{t("Needs your attention")}</h2>
          <ul className="space-y-2">
            {d?.signals.map((s: any, i: number) => (
              <li key={i} className={`panel border-s-4 p-4 ${s.kind === "risk" ? "border-s-rust" : s.kind === "positive" ? "border-s-moss" : "border-s-line"}`}>
                <div className="font-medium">{s.title}</div>
                <div className="mt-0.5 text-sm text-slate">{s.detail}</div>
                {s.action && <button className="link -ms-2 mt-2" onClick={() => ask(s.action)}>{t("Ask about this")} {lang === "ar" ? "←" : "→"}</button>}
              </li>
            ))}
            {d && !d.signals.length && <li className="panel p-4 text-sm text-slate">{t("Nothing needs your attention right now.")}</li>}
          </ul>
        </section>

        <section className="flex flex-col lg:col-span-3">
          <h2 className="text-lg font-semibold">{t("Ask your AI assistant")}</h2>
          <p className="mb-3 text-sm text-slate">{t("Ask in plain words, it reads your data and answers.")}</p>
          <div className="panel flex h-[520px] flex-col">
            <div className="flex-1 space-y-3 overflow-y-auto p-4">
              {!msgs.length && (
                <div>
                  <div className="mb-2 text-sm text-slate">{t("Try one of these:")}</div>
                  <div className="flex flex-wrap gap-2">
                    {SUGGESTIONS.map((s) => <button key={s} className="rounded-full border border-line px-3 py-1.5 text-sm hover:border-signal hover:bg-signal-soft" onClick={() => ask(t(s))}>{t(s)}</button>)}
                  </div>
                </div>
              )}
              {msgs.map((m, i) => (
                <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                  <div dir="auto" className={`max-w-[88%] whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${m.role === "user" ? "bg-signal text-white" : "bg-paper"}`}>{m.content}</div>
                </div>
              ))}
              {busy && <div className="text-sm text-slate">{t("Thinking…")}</div>}
              <div ref={endRef} />
            </div>
            <div className="border-t border-line p-3">
              <ErrorNote error={error} />
              {msgs.length > 0 && (
                <div className="mb-2 flex gap-2 overflow-x-auto pb-1">
                  {SUGGESTIONS.slice(0, 4).map((s) => <button key={s} className="whitespace-nowrap rounded-full border border-line px-3 py-1 text-xs text-slate hover:border-signal hover:text-ink" onClick={() => ask(t(s))}>{t(s)}</button>)}
                </div>
              )}
              <div className="flex gap-2">
                <input className="input" dir="auto" placeholder={t("Type your question…")} value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && ask(q)} />
                {voice.supported && <button className={`btn-ghost !px-3 ${voice.listening ? "!border-rust !text-rust animate-pulse" : ""}`} onClick={voice.start} title={t("Ask by voice")} aria-label={t("Ask by voice")}>🎤</button>}
                <button className="btn-primary" disabled={busy} onClick={() => ask(q)}>{t("Ask")}</button>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
