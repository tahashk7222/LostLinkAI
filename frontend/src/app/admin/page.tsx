"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { ErrorBox, PageHeader, Protected, Spinner, StatusBadge, TypeBadge } from "@/components/ui";

type Tab = "overview" | "reports" | "flags" | "users" | "cases" | "audit";

interface Stats {
  users: number;
  reports_by_status: Record<string, number>;
  reports_by_type: Record<string, number>;
  matches: number;
  cases: number;
  open_flags: number;
  ai_failures: number;
  failed_logins_recent: number;
}

function Admin() {
  const [tab, setTab] = useState<Tab>("overview");
  const [stats, setStats] = useState<Stats | null>(null);
  const [health, setHealth] = useState<{ status: string; database: boolean } | null>(null);
  const [rows, setRows] = useState<any[] | null>(null);
  const [q, setQ] = useState("");
  const [error, setError] = useState("");

  const loadTab = useCallback(async () => {
    setError("");
    setRows(null);
    try {
      if (tab === "overview") {
        setStats(await api<Stats>("/admin/stats"));
        setHealth(await api("/health"));
        setRows([]);
      } else if (tab === "reports") setRows((await api(`/admin/reports${q ? `?q=${encodeURIComponent(q)}` : ""}`)).items);
      else if (tab === "flags") setRows((await api("/admin/flags")).flags);
      else if (tab === "users") setRows((await api(`/admin/users${q ? `?q=${encodeURIComponent(q)}` : ""}`)).users);
      else if (tab === "cases") setRows((await api("/admin/cases")).cases);
      else if (tab === "audit") setRows((await api("/admin/audit")).entries);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [tab, q]);

  useEffect(() => {
    const t = setTimeout(loadTab, 200);
    return () => clearTimeout(t);
  }, [loadTab]);

  async function act(path: string) {
    try {
      await api(path, { method: "POST" });
      loadTab();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const tabs: [Tab, string][] = [
    ["overview", "Overview"], ["reports", "Reports"], ["flags", "Flagged"], ["users", "Users"], ["cases", "Cases"], ["audit", "Audit log"],
  ];

  return (
    <div>
      <PageHeader title="Admin dashboard" subtitle="Moderation and oversight. Private details, exact locations and messages are not shown here." />
      <div className="mb-6 flex flex-wrap gap-2">
        {tabs.map(([t, label]) => (
          <button key={t} onClick={() => { setTab(t); setQ(""); }} className={tab === t ? "btn-primary" : "btn-secondary"}>{label}</button>
        ))}
      </div>
      {error && <ErrorBox message={error} />}
      {(tab === "reports" || tab === "users") && (
        <input className="input mb-4 max-w-md" placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} />
      )}
      {rows === null ? <Spinner /> : (
        <>
          {tab === "overview" && stats && (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {[
                ["System health", health ? `${health.status} (database ${health.database ? "OK" : "down"})` : "…"],
                ["Users", stats.users],
                ["Lost reports", stats.reports_by_type.LOST ?? 0],
                ["Found reports", stats.reports_by_type.FOUND ?? 0],
                ["Potential matches", stats.matches],
                ["Cases", stats.cases],
                ["Recovered reports", stats.reports_by_status.RECOVERED ?? 0],
                ["Open flags", stats.open_flags],
                ["AI matching failures", stats.ai_failures],
                ["Failed logins (total)", stats.failed_logins_recent],
              ].map(([k, v]) => (
                <div key={k as string} className="card">
                  <p className="text-sm text-slate-500">{k}</p>
                  <p className="mt-1 text-2xl font-bold text-slate-900">{v}</p>
                </div>
              ))}
            </div>
          )}

          {tab === "reports" && (
            <Table head={["Report", "Type", "Status", "AI", "Created", ""]}>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td><Link className="text-brand-600 hover:underline" href={`/reports/${r.id}`}>#{r.id} {r.name}</Link><div className="text-xs text-slate-500">{r.location}</div></td>
                  <td><TypeBadge type={r.report_type} /></td>
                  <td><StatusBadge status={r.status} /></td>
                  <td className="text-xs">{r.ai_status}</td>
                  <td className="text-xs">{formatDate(r.created_at)}</td>
                  <td>
                    {r.status === "DEACTIVATED"
                      ? <button className="btn-secondary" onClick={() => act(`/admin/reports/${r.id}/reactivate`)}>Reactivate</button>
                      : <button className="btn-danger" onClick={() => act(`/admin/reports/${r.id}/deactivate`)}>Deactivate</button>}
                  </td>
                </tr>
              ))}
            </Table>
          )}

          {tab === "flags" && (
            <Table head={["Target", "Reason", "Reported", ""]}>
              {rows.length === 0 && <tr><td colSpan={4} className="text-slate-500">No open flags.</td></tr>}
              {rows.map((f) => (
                <tr key={f.id}>
                  <td>{f.entity_type === "report" ? <Link className="text-brand-600 hover:underline" href={`/reports/${f.entity_id}`}>Report #{f.entity_id}</Link> : `User #${f.entity_id}`}</td>
                  <td className="max-w-sm">{f.reason}</td>
                  <td className="text-xs">{formatDate(f.created_at)}</td>
                  <td className="space-x-2 whitespace-nowrap">
                    {f.entity_type === "report" && <button className="btn-danger" onClick={() => act(`/admin/reports/${f.entity_id}/deactivate`).then(() => act(`/admin/flags/${f.id}/resolve`))}>Deactivate report</button>}
                    <button className="btn-secondary" onClick={() => act(`/admin/flags/${f.id}/resolve`)}>Resolve</button>
                    <button className="btn-secondary" onClick={() => act(`/admin/flags/${f.id}/dismiss`)}>Dismiss</button>
                  </td>
                </tr>
              ))}
            </Table>
          )}

          {tab === "users" && (
            <Table head={["User", "Email", "Role", "Reports", "Flags", "Status", ""]}>
              {rows.map((u) => (
                <tr key={u.id}>
                  <td>#{u.id} {u.name}</td>
                  <td className="text-xs">{u.email}</td>
                  <td className="text-xs">{u.role}</td>
                  <td>{u.reports}</td>
                  <td className={u.flags ? "font-semibold text-rose-600" : ""}>{u.flags}</td>
                  <td className="text-xs">{u.is_active ? "Active" : "Deactivated"}</td>
                  <td>
                    {u.role !== "ADMIN" && (u.is_active
                      ? <button className="btn-danger" onClick={() => act(`/admin/users/${u.id}/deactivate`)}>Deactivate</button>
                      : <button className="btn-secondary" onClick={() => act(`/admin/users/${u.id}/activate`)}>Activate</button>)}
                  </td>
                </tr>
              ))}
            </Table>
          )}

          {tab === "cases" && (
            <Table head={["Case", "Item", "Match score", "Status", "Updated"]}>
              {rows.length === 0 && <tr><td colSpan={5} className="text-slate-500">No cases yet.</td></tr>}
              {rows.map((c) => (
                <tr key={c.id}>
                  <td>#{c.id}</td>
                  <td>{c.match.lost_report?.name}</td>
                  <td>{c.match.score_percent}%</td>
                  <td><StatusBadge status={c.status} /></td>
                  <td className="text-xs">{formatDate(c.updated_at)}</td>
                </tr>
              ))}
            </Table>
          )}

          {tab === "audit" && (
            <Table head={["Time", "Actor", "Action", "Entity", "Details"]}>
              {rows.map((a) => (
                <tr key={a.id}>
                  <td className="whitespace-nowrap text-xs">{formatDate(a.timestamp)}</td>
                  <td className="text-xs">{a.actor_id ?? "system"}</td>
                  <td className="font-mono text-xs">{a.action}</td>
                  <td className="text-xs">{a.entity_type ? `${a.entity_type} #${a.entity_id}` : ""}</td>
                  <td className="max-w-xs truncate font-mono text-xs text-slate-500">{a.meta ? JSON.stringify(a.meta) : ""}</td>
                </tr>
              ))}
            </Table>
          )}
        </>
      )}
    </div>
  );
}

function Table({ head, children }: { head: string[]; children: React.ReactNode }) {
  return (
    <div className="card overflow-x-auto p-0">
      <table className="w-full text-left text-sm [&_td]:px-4 [&_td]:py-3 [&_th]:px-4 [&_th]:py-3">
        <thead className="bg-slate-50 text-xs uppercase text-slate-500">
          <tr>{head.map((h) => <th key={h}>{h}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-slate-100">{children}</tbody>
      </table>
    </div>
  );
}

export default function AdminPage() {
  return (
    <Protected admin>
      <Admin />
    </Protected>
  );
}
