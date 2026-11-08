"use client";
import { useState } from "react";
import { API_URL, api, getToken } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { date } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { Badge, Drawer, ErrorNote, Field, Modal, PageTitle, Table, toast } from "@/components/ui";

const DOC_TYPES = ["policy", "contract", "catalog", "price_list", "manual", "procedure"];

export default function Documents() {
  const { t } = useT();
  const docs = useApi<any[]>("/api/documents");
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<any[] | null>(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [docType, setDocType] = useState("policy");
  const [content, setContent] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [viewId, setViewId] = useState<number | null>(null);
  const view = useApi<any>(viewId ? `/api/documents/${viewId}` : null, [viewId]);

  const search = async () => { if (!q.trim()) return; setHits(await api(`/api/documents/search?q=${encodeURIComponent(q)}`)); };
  const save = async () => {
    setError(null);
    try {
      if (file) {
        const fd = new FormData(); fd.append("file", file);
        const r = await fetch(`${API_URL}/api/documents/upload?doc_type=${docType}`, { method: "POST", body: fd, headers: { Authorization: `Bearer ${getToken()}` } });
        if (!r.ok) throw new Error((await r.json()).detail);
      } else await api("/api/documents/text", { method: "POST", json: { title, doc_type: docType, content } });
      setOpen(false); setTitle(""); setContent(""); setFile(null); docs.reload(); toast("Saved");
    } catch (e: any) { setError(e.message); }
  };

  return (
    <>
      <PageTitle title={t("Company files")} help={t("Files help")} actions={<button className="btn-primary" onClick={() => { setError(null); setOpen(true); }}>+ {t("Add file")}</button>} />
      <div className="mb-6 flex max-w-2xl gap-2"><input className="input" dir="auto" placeholder={t("Search inside your files, e.g. who approves big discounts?")} value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && search()} /><button className="btn-ghost" onClick={search}>{t("Search")}</button></div>
      {hits && <ul className="mb-8 space-y-2">
        {hits.map((h, i) => <li key={i} className="panel p-4"><Badge tone="info">{h.document_title}</Badge><p dir="auto" className="mt-2 text-sm leading-relaxed">{h.content}</p></li>)}
        {!hits.length && <li className="panel p-4 text-sm text-slate">{t("No matches. Try other words.")}</li>}
      </ul>}
      <div className="panel"><Table rows={docs.data} onRow={(r: any) => setViewId(r.id)} empty={t("No files yet. Add a policy, contract or price list.")} cols={[
        { h: t("Title"), c: (r: any) => <span className="font-medium">{r.title}</span> }, { h: t("Type"), c: (r: any) => t(r.doc_type) }, { h: t("File"), c: (r: any) => r.filename ?? t("written text") },
        { h: t("Added"), c: (r: any) => date(r.created_at) },
        { h: "", c: (r: any) => <div className="flex justify-end"><button className="link-danger" onClick={async (e) => { e.stopPropagation(); if (confirm(t("Delete this file?"))) { await api(`/api/documents/${r.id}`, { method: "DELETE" }); docs.reload(); } }}>{t("Delete")}</button></div> },
      ]} /></div>
      <Drawer title={view.data?.title ?? "…"} open={!!viewId} onClose={() => setViewId(null)}>
        {!view.data ? <div className="text-sm text-slate">{t("Loading…")}</div> : <>
          <div className="mb-4 flex flex-wrap gap-2 text-xs"><Badge tone="info">{t(view.data.doc_type)}</Badge>{view.data.filename && <Badge>{view.data.filename}</Badge>}<Badge>{date(view.data.created_at)}</Badge></div>
          <div dir="auto" className="whitespace-pre-wrap text-sm leading-relaxed">{view.data.content || t("No readable text in this file.")}</div>
        </>}
      </Drawer>
      <Modal title={t("Add file")} open={open} onClose={() => setOpen(false)} onSave={save}>
        <ErrorNote error={error} />
        <div className="grid gap-3">
          <Field label={t("Type")}><select className="input" value={docType} onChange={(e) => setDocType(e.target.value)}>{DOC_TYPES.map((d) => <option key={d} value={d}>{t(d)}</option>)}</select></Field>
          <Field label={t("Upload a file (PDF, Word, TXT)")}><input className="input" type="file" accept=".pdf,.docx,.txt,.md" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></Field>
          <div className="text-center text-xs text-slate">— {t("or write the text here")} —</div>
          <Field label={t("Title")}><input className="input" value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
          <Field label={t("Text")}><textarea className="input h-32" dir="auto" value={content} onChange={(e) => setContent(e.target.value)} /></Field>
        </div>
      </Modal>
    </>
  );
}
