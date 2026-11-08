"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { Badge, ErrorNote, Field, Modal, PageTitle, Status, Table, toast, useForm } from "@/components/ui";

const EMPTY = { full_name: "", email: "", password: "", department: "", role_id: 0, branch_id: 0, is_active: true, allowed_warehouse_ids: [] as number[] };

export default function Team() {
  const { t, tx } = useT();
  const { user: me, can } = useSession();
  const users = useApi<any[]>("/api/users");
  const roles = useApi<any[]>("/api/users/roles");
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const f = useForm(EMPTY);
  const { data: branches } = useApi<any[]>("/api/branches");
  const { data: catalog } = useApi<{ group: string; permissions: { name: string; label: string }[] }[]>("/api/users/permission-catalog");
  const { data: warehouses } = useApi<any[]>("/api/inventory/warehouses");
  const [roleOpen, setRoleOpen] = useState(false);
  const [role, setRole] = useState<{ id?: number; name: string; permissions: string[] }>({ name: "", permissions: [] });
  // an existing role opens with the granular permissions it really grants (older roles hold coarse ones like "sales:read")
  const openRole = (r: any = null) => { setError(null); setRole(r ? { id: r.id, name: r.name, permissions: [...(r.granted?.length ? r.granted : r.permissions)] } : { name: "", permissions: [] }); setRoleOpen(true); };
  const saveRole = async () => {
    setError(null);
    // save only the granular permissions shown in the editor (they cover everything the coarse ones did)
    const shown = new Set(catalog?.flatMap((g) => g.permissions.map((p) => p.name)) ?? []);
    const permissions = role.permissions.filter((p) => shown.has(p));
    try { await api(role.id ? `/api/users/roles/${role.id}` : "/api/users/roles", { method: role.id ? "PUT" : "POST", json: { name: role.name, permissions } }); setRoleOpen(false); toast("Saved"); roles.reload(); }
    catch (e: any) { setError(e.message); }
  };
  const togglePerm = (p: string) => setRole({ ...role, permissions: role.permissions.includes(p) ? role.permissions.filter((x) => x !== p) : [...role.permissions, p] });
  const canWrite = can("users:write");

  const openUser = (u: any = null) => {
    setError(null); setEditing(u);
    f.setV(u ? { full_name: u.full_name, email: u.email, password: "", department: u.department ?? "", role_id: u.role?.id ?? 0, branch_id: u.branch_id ?? 0, is_active: u.is_active, allowed_warehouse_ids: u.allowed_warehouse_ids ?? [] } : EMPTY);
    setOpen(true);
  };
  const save = async () => {
    setError(null);
    try {
      if (editing) {
        const { email, password, ...rest } = f.v;
        await api(`/api/users/${editing.id}`, { method: "PATCH", json: { ...rest, role_id: +rest.role_id || null, branch_id: +rest.branch_id || null, ...(password ? { password } : {}) } });
      } else {
        const { is_active, ...rest } = f.v;
        await api("/api/users", { method: "POST", json: { ...rest, role_id: +rest.role_id || null, branch_id: +rest.branch_id || null } });
      }
      setOpen(false); toast("Saved"); users.reload();
    } catch (e: any) { setError(e.message); }
  };

  return (
    <>
      <PageTitle title={t("Team")} help={t("Team help")} actions={canWrite && <button className="btn-primary" onClick={() => openUser()}>+ {t("Add person")}</button>} />
      <div className="panel"><Table rows={users.data} onRow={canWrite ? openUser : undefined} cols={[
        { h: t("Name"), c: (r: any) => <span className="font-medium">{r.full_name}{r.id === me.id && <span className="ms-2 text-xs text-slate">({t("you")})</span>}</span> },
        { h: t("Email"), c: (r: any) => <span dir="ltr">{r.email}</span> }, { h: t("Department"), c: (r: any) => r.department ?? "—" },
        { h: t("Role"), c: (r: any) => (r.role ? tx(r.role.name) : "—") }, { h: t("Status"), c: (r: any) => <Status value={r.is_active ? "active" : "inactive"} /> },
      ]} /></div>
      <div className="mb-3 mt-8 flex items-center justify-between"><h2 className="text-lg font-semibold">{t("Roles")}</h2>{canWrite && <button className="btn-ghost" onClick={() => openRole()}>+ {t("New role")}</button>}</div>
      <div className="panel"><Table rows={roles.data} onRow={canWrite ? (r: any) => !r.permissions.includes("*") && openRole(r) : undefined} cols={[
        { h: t("Role"), c: (r: any) => <span className="font-medium">{tx(r.name)}</span> },
        { h: t("Can do"), c: (r: any) => <div className="flex flex-wrap gap-1">{r.permissions.map((p: string) => <Badge key={p} tone={p === "*" ? "info" : "neutral"}>{p === "*" ? t("Everything") : t(`perm.${p}`) === `perm.${p}` ? p : t(`perm.${p}`)}</Badge>)}</div> },
      ]} /></div>
      <Modal title={editing ? t("Edit person") : t("Add person")} open={open} onClose={() => setOpen(false)} onSave={save} saveLabel={editing ? t("Save") : t("Create user")}>
        <ErrorNote error={error} />
        <div className="grid grid-cols-2 gap-3">
          <Field label={t("Full name")}><input className="input" value={f.v.full_name} onChange={f.set("full_name")} /></Field>
          <Field label={t("Email")}><input className="input" dir="ltr" disabled={!!editing} value={f.v.email} onChange={f.set("email")} /></Field>
          <Field label={editing ? t("New password (leave empty to keep)") : t("Temporary password")}><input className="input" type="password" dir="ltr" value={f.v.password} onChange={f.set("password")} /></Field>
          <Field label={t("Department")}><input className="input" value={f.v.department} onChange={f.set("department")} /></Field>
          <div className="col-span-2"><Field label={t("Role")}><select className="input" value={f.v.role_id} disabled={editing?.id === me.id} onChange={f.set("role_id")}><option value={0}>{t("Select…")}</option>{roles.data?.map((r) => <option key={r.id} value={r.id}>{tx(r.name)}</option>)}</select></Field></div>
          {branches && branches.length > 0 && <div className="col-span-2"><Field label={t("Branch")}><select className="input" value={f.v.branch_id} onChange={f.set("branch_id")}><option value={0}>{t("All branches")}</option>{branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select></Field></div>}
          {warehouses && warehouses.length > 1 && <div className="col-span-2"><Field label={t("Warehouses this person can work in (none ticked = all)")}>
            <div className="flex flex-wrap gap-2">{warehouses.map((w) => <label key={w.id} className="flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-sm">
              <input type="checkbox" className="accent-signal" checked={f.v.allowed_warehouse_ids.includes(w.id)}
                onChange={() => f.setV({ ...f.v, allowed_warehouse_ids: f.v.allowed_warehouse_ids.includes(w.id) ? f.v.allowed_warehouse_ids.filter((x: number) => x !== w.id) : [...f.v.allowed_warehouse_ids, w.id] })} />{w.name}</label>)}</div>
          </Field></div>}
          {editing && editing.id !== me.id && <label className="col-span-2 flex items-center gap-2 text-sm"><input type="checkbox" className="h-4 w-4 accent-signal" checked={f.v.is_active} onChange={f.set("is_active")} />{t("Account is active (can log in)")}</label>}
        </div>
      </Modal>
      <Modal title={role.id ? t("Edit role") : t("New role")} open={roleOpen} onClose={() => setRoleOpen(false)} onSave={saveRole}>
        <ErrorNote error={error} />
        <Field label={t("Name")}><input className="input" value={role.name} onChange={(e) => setRole({ ...role, name: e.target.value })} /></Field>
        <div className="mt-4 max-h-[60vh] space-y-4 overflow-y-auto">
          {catalog?.map((g) => {
            const names = g.permissions.map((p) => p.name);
            const all = names.every((n) => role.permissions.includes(n));
            return (
              <div key={g.group}>
                <label className="mb-1 flex items-center gap-2 text-sm font-semibold"><input type="checkbox" className="h-4 w-4 accent-signal" checked={all}
                  onChange={() => setRole({ ...role, permissions: all ? role.permissions.filter((x) => !names.includes(x)) : Array.from(new Set([...role.permissions, ...names])) })} />{t(g.group)}</label>
                <div className="grid grid-cols-1 gap-0.5 ps-6 sm:grid-cols-2">
                  {g.permissions.map((p) => <label key={p.name} className="flex items-center gap-2 rounded-md px-2 py-1 text-sm hover:bg-paper" title={p.name}>
                    <input type="checkbox" className="h-4 w-4 accent-signal" checked={role.permissions.includes(p.name)} onChange={() => togglePerm(p.name)} />{t(p.label)}</label>)}
                </div>
              </div>
            );
          })}
        </div>
      </Modal>
    </>
  );
}
