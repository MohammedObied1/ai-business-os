"use client";
import { useState } from "react";
import { API_URL, api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { date } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { Badge, ErrorNote, Field, Modal, PageTitle, Table, toast } from "@/components/ui";

export default function Integrations() {
  const { t } = useT();
  const data = useApi<any>("/api/integrations");
  const [keyForm, setKeyForm] = useState<{ name: string; scopes: string[]; expires_days: string; rate_limit_per_min: number } | null>(null);
  const [newKey, setNewKey] = useState<string | null>(null);
  const scopes = useApi<string[]>(keyForm ? "/api/integrations/keys/scopes" : null, [!!keyForm]);
  const [hook, setHook] = useState<{ url: string; events: string[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [wa, setWa] = useState<{ phone_number_id: string; secret: string } | null>(null);
  const [waTest, setWaTest] = useState("");

  const createKey = async () => {
    setError(null);
    try { const r = await api("/api/integrations/keys", { method: "POST", json: { name: keyForm!.name, scopes: keyForm!.scopes,
      expires_days: keyForm!.expires_days ? +keyForm!.expires_days : null, rate_limit_per_min: keyForm!.rate_limit_per_min } });
      setKeyForm(null); setNewKey(r.key); data.reload(); } catch (e: any) { setError(e.message); }
  };
  const createHook = async () => {
    setError(null);
    try { await api("/api/integrations/webhooks", { method: "POST", json: { url: hook!.url, events: hook!.events.length ? hook!.events : ["*"] } }); setHook(null); toast("Saved"); data.reload(); }
    catch (e: any) { setError(e.message); }
  };
  const test = async (id: number) => {
    try { const r = await api(`/api/integrations/webhooks/${id}/test`, { method: "POST" }); toast(`${t(r.status)} ${r.response_code ?? ""}`, r.status === "delivered" ? "good" : "bad"); data.reload(); }
    catch (e: any) { toast(e.message, "bad"); }
  };
  const copy = (s: string) => { navigator.clipboard?.writeText(s); toast("Copied"); };
  const waConn = data.data?.connections?.find((c: any) => c.provider === "whatsapp");
  const saveWa = async () => {
    setError(null);
    try { await api("/api/integrations/connections/whatsapp", { method: "PUT", json: { config: { phone_number_id: wa!.phone_number_id },
      secret: wa!.secret || null, is_active: true } }); setWa(null); toast("Saved"); data.reload(); } catch (e: any) { setError(e.message); }
  };
  const disconnectWa = async () => { if (confirm(t("Disconnect WhatsApp?"))) { await api("/api/integrations/connections/whatsapp", { method: "DELETE" }); data.reload(); } };
  const testWa = async () => {
    if (!waTest) return;
    try { const r = await api(`/api/integrations/connections/whatsapp/test?phone=${encodeURIComponent(waTest)}`, { method: "POST" });
      toast(r.sent ? t("Sent") : (r.error ?? t("Failed")), r.sent ? "good" : "bad"); } catch (e: any) { toast(e.message, "bad"); }
  };

  return (
    <>
      <PageTitle title={t("Integrations")} help={t("Integrations help")} />
      <section className="panel mb-6 p-5">
        <div className="flex items-center justify-between"><h2 className="text-base font-semibold">💬 {t("WhatsApp")}</h2>
          {waConn?.connected
            ? <button className="link-danger text-sm" onClick={disconnectWa}>{t("Disconnect")}</button>
            : <button className="btn-primary" onClick={() => { setError(null); setWa({ phone_number_id: waConn?.config?.phone_number_id ?? "", secret: "" }); }}>{t("Connect")}</button>}
        </div>
        <p className="mt-1 text-sm text-slate">{t("WhatsApp help")}</p>
        {waConn?.connected ? <>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
            <Badge tone={waConn.last_error ? "bad" : "good"}>{waConn.last_error ? t("Last message failed") : t("Connected")}</Badge>
            {waConn.last_used_at && <span className="text-xs text-slate">{t("Last used")}: {date(waConn.last_used_at)}</span>}
          </div>
          {waConn.last_error && <p className="mt-1 text-xs text-rust">{waConn.last_error}</p>}
          <div className="mt-3 flex gap-2"><input className="input" dir="ltr" placeholder="+9705…" value={waTest} onChange={(e) => setWaTest(e.target.value)} />
            <button className="btn-ghost shrink-0" onClick={testWa}>{t("Send test message")}</button></div>
        </> : <p className="mt-2 text-xs text-slate">{t("Not connected. Messages fall back to email/in-app.")}</p>}
      </section>
      <div className="grid gap-6 xl:grid-cols-2">
        <section className="panel p-5">
          <div className="flex items-center justify-between"><h2 className="text-base font-semibold">🔑 {t("API keys")}</h2>
            <button className="btn-primary" onClick={() => { setError(null); setKeyForm({ name: "", scopes: [], expires_days: "", rate_limit_per_min: 120 }); }}>+ {t("New key")}</button></div>
          <p className="mt-1 text-sm text-slate">{t("For your website, accounting app or any program that needs to read or add data. Send it in the X-API-Key header.")}</p>
          <div className="mt-4 rounded-lg border border-line"><Table rows={data.data?.keys ?? null} empty={t("No keys yet.")} cols={[
            { h: t("Name"), c: (k: any) => <span className="font-medium">{k.name}</span> }, { h: t("Key"), c: (k: any) => <span dir="ltr" className="font-mono text-xs">{k.prefix}…</span> },
            { h: t("Scope"), c: (k: any) => k.scopes.length ? <div className="flex flex-wrap gap-1">{k.scopes.map((s: string) => <Badge key={s} tone="info">{s}</Badge>)}</div> : <span className="text-xs text-slate">{t("Full access")}</span> },
            { h: t("Limit/min"), c: (k: any) => k.rate_limit_per_min, end: true }, { h: t("Requests"), c: (k: any) => k.request_count, end: true },
            { h: t("Expires"), c: (k: any) => k.expires_at ? <span className={k.expired ? "text-rust" : ""}>{date(k.expires_at)}</span> : t("Never") },
            { h: t("Last used"), c: (k: any) => date(k.last_used_at) },
            { h: "", c: (k: any) => k.is_active ? <button className="link-danger" onClick={async () => { if (confirm(t("Stop this key? Programs using it will stop working."))) { await api(`/api/integrations/keys/${k.id}`, { method: "DELETE" }); data.reload(); } }}>{t("Revoke")}</button>
              : <Badge>{t("Revoked")}</Badge> },
          ]} /></div>
          <div className="mt-4 rounded-lg bg-paper p-3 text-xs" dir="ltr">
            <div className="mb-1 font-semibold">Example</div>
            <code className="block whitespace-pre-wrap break-all">curl -H &quot;X-API-Key: bos_…&quot; {API_URL}/api/inventory/products</code>
            <a className="mt-2 inline-block text-signal" href={`${API_URL}/docs`} target="_blank" rel="noreferrer">{API_URL}/docs →</a>
          </div>
        </section>

        <section className="panel p-5">
          <div className="flex items-center justify-between"><h2 className="text-base font-semibold">🔔 {t("Webhooks")}</h2>
            <button className="btn-primary" onClick={() => { setError(null); setHook({ url: "https://", events: [] }); }}>+ {t("New webhook")}</button></div>
          <p className="mt-1 text-sm text-slate">{t("We call your address when something happens (new order, payment…). Signed with HMAC-SHA256 in the X-BizOS-Signature header.")}</p>
          <div className="mt-4 space-y-2">
            {data.data?.webhooks.length === 0 && <p className="text-sm text-slate">{t("No webhooks yet.")}</p>}
            {data.data?.webhooks.map((h: any) => (
              <div key={h.id} className="rounded-lg border border-line p-3 text-sm">
                <div className="flex items-center justify-between gap-2"><span dir="ltr" className="truncate font-mono text-xs">{h.url}</span>
                  <div className="flex shrink-0 gap-1"><button className="link" onClick={() => test(h.id)}>{t("Test")}</button>
                    <button className="link-danger" onClick={async () => { if (confirm(t("Delete?"))) { await api(`/api/integrations/webhooks/${h.id}`, { method: "DELETE" }); data.reload(); } }}>{t("Delete")}</button></div></div>
                <div className="mt-1 flex flex-wrap gap-1">{h.events.map((e: string) => <Badge key={e} tone="info">{e === "*" ? t("All events") : e}</Badge>)}</div>
                <div className="mt-2 text-xs text-slate">{t("Secret")}: <button dir="ltr" className="font-mono hover:text-signal" onClick={() => copy(h.secret)}>{h.secret}</button></div>
              </div>
            ))}
          </div>
          <h3 className="mb-2 mt-5 text-sm font-semibold">{t("Recent calls")}</h3>
          <div className="rounded-lg border border-line"><Table rows={data.data?.deliveries ?? null} pageSize={10} cols={[
            { h: t("Event"), c: (d: any) => <span dir="ltr" className="text-xs">{d.event}</span> },
            { h: t("Status"), c: (d: any) => <Badge tone={d.status === "delivered" ? "good" : d.status === "failed" ? "bad" : "warn"}>{t(d.status)}</Badge> },
            { h: "HTTP", c: (d: any) => d.response_code ?? "—" }, { h: t("Attempts"), c: (d: any) => d.attempts },
            { h: t("When"), c: (d: any) => date(d.created_at) },
          ]} /></div>
        </section>
      </div>

      <Modal title={t("New key")} open={!!keyForm} onClose={() => setKeyForm(null)} onSave={createKey}>
        {keyForm && <>
          <ErrorNote error={error} />
          <Field label={t("Name")}><input className="input" placeholder={t("e.g. Website")} value={keyForm.name} onChange={(e) => setKeyForm({ ...keyForm, name: e.target.value })} /></Field>
          <div className="mt-3 grid grid-cols-2 gap-3">
            <Field label={t("Expires in (days, empty = never)")}><input className="input" type="number" min={1} value={keyForm.expires_days} onChange={(e) => setKeyForm({ ...keyForm, expires_days: e.target.value })} /></Field>
            <Field label={t("Rate limit (requests/minute)")}><input className="input" type="number" min={1} max={6000} value={keyForm.rate_limit_per_min} onChange={(e) => setKeyForm({ ...keyForm, rate_limit_per_min: +e.target.value || 120 })} /></Field>
          </div>
          <p className="mb-2 mt-4 text-sm font-medium">{t("Limit to (none selected = your full permissions)")}</p>
          <div className="grid grid-cols-2 gap-1 text-sm">{scopes.data?.map((s: string) => (
            <label key={s} className="flex items-center gap-2" dir="ltr"><input type="checkbox" className="accent-signal" checked={keyForm.scopes.includes(s)}
              onChange={(e) => setKeyForm({ ...keyForm, scopes: e.target.checked ? [...keyForm.scopes, s] : keyForm.scopes.filter((x) => x !== s) })} />{s}</label>))}</div>
          <p className="mt-3 text-xs text-slate">{t("The key acts with your permissions.")}</p>
        </>}
      </Modal>
      <Modal title={t("Your new key")} open={!!newKey} onClose={() => setNewKey(null)}>
        <p className="mb-3 text-sm text-amber">{t("Copy it now. For security it will not be shown again.")}</p>
        <div className="flex gap-2"><input className="input font-mono text-xs" dir="ltr" readOnly value={newKey ?? ""} onFocus={(e) => e.target.select()} />
          <button className="btn-primary" onClick={() => copy(newKey!)}>{t("Copy")}</button></div>
      </Modal>
      <Modal title={t("New webhook")} open={!!hook} onClose={() => setHook(null)} onSave={createHook}>
        {hook && <>
          <ErrorNote error={error} />
          <Field label={t("Address (URL)")}><input className="input" dir="ltr" value={hook.url} onChange={(e) => setHook({ ...hook, url: e.target.value })} /></Field>
          <p className="mb-2 mt-4 text-sm font-medium">{t("Events (none selected = all)")}</p>
          <div className="grid grid-cols-2 gap-1 text-sm">{data.data?.events.map((ev: string) => (
            <label key={ev} className="flex items-center gap-2" dir="ltr"><input type="checkbox" className="accent-signal" checked={hook.events.includes(ev)}
              onChange={(e) => setHook({ ...hook, events: e.target.checked ? [...hook.events, ev] : hook.events.filter((x) => x !== ev) })} />{ev}</label>))}</div>
        </>}
      </Modal>
      <Modal title={t("Connect WhatsApp")} open={!!wa} onClose={() => setWa(null)} onSave={saveWa}>
        {wa && <>
          <ErrorNote error={error} />
          <p className="mb-3 text-sm text-slate">{t("WhatsApp connect help")}</p>
          <Field label="Phone number ID"><input className="input" dir="ltr" value={wa.phone_number_id} onChange={(e) => setWa({ ...wa, phone_number_id: e.target.value })} /></Field>
          <Field label={t("Access token")}><input className="input" dir="ltr" type="password" placeholder={waConn?.connected ? t("Leave empty to keep the current one") : ""} value={wa.secret} onChange={(e) => setWa({ ...wa, secret: e.target.value })} /></Field>
        </>}
      </Modal>
    </>
  );
}
