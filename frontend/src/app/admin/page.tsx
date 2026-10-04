"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { ErrorBox, PageHeader, Protected, Spinner, StatusBadge, TypeBadge } from "@/components/ui";

type Tab = "overview" | "reports" | "verification" | "flags" | "users" | "cases" | "audit";

interface Dashboard {
  cards: Record<string, number>;
  totals: { users: number; matches: number; cases: number; open_flags: number };
  reports_by_status: Record<string, number>;
  recent_reports: { id: number; report_type: string; name: string; status: string; zone: string | null; created_at: string }[];
  recent_matches: { id: number; status: string; lead: string | null; relevance_percent: number; created_at: string }[];
  recent_actions: { id: number; action: string; entity_type: string | null; entity_id: number | null; timestamp: string }[];
}

// Operational cards, shown in this order. Every number comes from the dashboard endpoint.
const CARDS: [string, string][] = [
  ["active_lost", "Active lost items"],
  ["active_found", "Active found items"],
  ["potential_matches", "Potential matches"],
  ["verification_open", "Verification in progress"],
  ["recovery_pending", "Recovery pending"],
  ["recovered", "Recovered (archived)"],
  ["rejected", "Rejected reports"],
  ["open_flags_on_reports", "Suspicious reports (open flags)"],
];

const VERIFICATION_LABEL: Record<string, string> = {
  pending: "Pending", in_progress: "In progress", verified: "Verified", failed: "Failed", cancelled: "Cancelled",
};

function Admin() {
  const [tab, setTab] = useState<Tab>("overview");
  const [dash, setDash] = useState<Dashboard | null>(null);
  const [health, setHealth] = useState<{ status: string; database: boolean } | null>(null);
  const [rows, setRows] = useState<any[] | null>(null);
  const [q, setQ] = useState("");
  const [error, setError] = useState("");

  const loadTab = useCallback(async () => {
    setError("");
    setRows(null);
    try {
      if (tab === "overview") {
        setDash(await api<Dashboard>("/admin/dashboard"));
        setHealth(await api("/health"));
        setRows([]);
      } else if (tab === "reports") setRows((await api(`/admin/reports${q ? `?q=${encodeURIComponent(q)}` : ""}`)).items);
      else if (tab === "verification") setRows((await api("/admin/verification")).verifications);
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
    ["overview", "Overview"], ["reports", "Reports"], ["verification", "Verification"], ["flags", "Flagged"],
    ["users", "Users"], ["cases", "Cases"], ["audit", "Audit log"],
  ];

  return (
    <div>
      <PageHeader title="Admin dashboard" subtitle="Moderation and oversight. Private details, exact locations, messages and verification answers are not shown here." />
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
          {tab === "overview" && dash && (
            <div className="space-y-8">
              <p className="text-sm text-slate-600">
                System: {health ? `${health.status} (database ${health.database ? "OK" : "down"})` : "…"}. Users: {dash.totals.users}.
              </p>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                {CARDS.map(([key, label]) => (
                  <div key={key} className="card">
                    <p className="text-sm text-slate-500">{label}</p>
                    <p className="mt-1 text-2xl font-bold text-slate-900">{dash.cards[key] ?? 0}</p>
                  </div>
                ))}
              </div>
              <div className="grid gap-6 lg:grid-cols-3">
                <Panel title="Recent reports">
                  {dash.recent_reports.map((r) => (
                    <li key={r.id} className="flex items-center justify-between gap-2 py-2 text-sm">
                      <Link className="text-brand-600 hover:underline" href={`/admin/reports/${r.id}`}>#{r.id} {r.name}</Link>
                      <StatusBadge status={r.status} />
                    </li>
                  ))}
                  {dash.recent_reports.length === 0 && <li className="py-2 text-sm text-slate-500">No reports yet.</li>}
                </Panel>
                <Panel title="Recent matches">
                  {dash.recent_matches.map((m) => (
                    <li key={m.id} className="flex items-center justify-between gap-2 py-2 text-sm">
                      <span>Match #{m.id} · {m.lead ?? "—"} lead</span>
                      <span className="text-xs text-slate-500">relevance {m.relevance_percent}%</span>
                    </li>
                  ))}
                  {dash.recent_matches.length === 0 && <li className="py-2 text-sm text-slate-500">No matches yet.</li>}
                </Panel>
                <Panel title="Recent admin and recovery actions">
                  {dash.recent_actions.map((a) => (
                    <li key={a.id} className="py-2 text-sm">
                      <span className="font-mono text-xs">{a.action}</span>
                      <div className="text-xs text-slate-500">{a.entity_type ? `${a.entity_type} #${a.entity_id}` : ""} · {formatDate(a.timestamp)}</div>
                    </li>
                  ))}
                  {dash.recent_actions.length === 0 && <li className="py-2 text-sm text-slate-500">No actions yet.</li>}
                </Panel>
              </div>
            </div>
          )}

          {tab === "reports" && (
            <Table head={["Report", "Type", "Status", "AI", "Created", ""]}>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td><Link className="text-brand-600 hover:underline" href={`/admin/reports/${r.id}`}>#{r.id} {r.name}</Link><div className="text-xs text-slate-500">{r.location}</div></td>
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

          {tab === "verification" && (
            <Table head={["Verification", "Match", "Progress", "Started", "Decided"]}>
              {rows.length === 0 && <tr><td colSpan={5} className="text-slate-500">No ownership verifications yet.</td></tr>}
              {rows.map((v) => (
                <tr key={v.id}>
                  <td>#{v.id}</td>
                  <td><Link className="text-brand-600 hover:underline" href={`/matches/${v.match_id}`}>Match #{v.match_id}</Link></td>
                  <td>{VERIFICATION_LABEL[v.display_status] ?? v.display_status}</td>
                  <td className="text-xs">{formatDate(v.created_at)}</td>
                  <td className="text-xs">{v.decided_at ? formatDate(v.decided_at) : "—"}</td>
                </tr>
              ))}
            </Table>
          )}

          {tab === "flags" && (
            <Table head={["Target", "Reason", "Reported", ""]}>
              {rows.length === 0 && <tr><td colSpan={4} className="text-slate-500">No open flags.</td></tr>}
              {rows.map((f) => (
                <tr key={f.id}>
                  <td>{f.entity_type === "report" ? <Link className="text-brand-600 hover:underline" href={`/admin/reports/${f.entity_id}`}>Report #{f.entity_id}</Link> : `User #${f.entity_id}`}</td>
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
                  <td><Link className="text-brand-600 hover:underline" href={`/admin/cases/${c.id}`}>#{c.id}</Link></td>
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

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="card">
      <h2 className="mb-2 font-semibold text-slate-900">{title}</h2>
      <ul className="divide-y divide-slate-100">{children}</ul>
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
