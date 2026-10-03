"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { CaseInfo, Match, Notification, Report } from "@/lib/types";
import { Empty, ErrorBox, PageHeader, Protected, ReportCard, Spinner, StatusBadge } from "@/components/ui";
import { timeAgo } from "@/lib/format";

function Dashboard() {
  const { user } = useAuth();
  const [reports, setReports] = useState<Report[] | null>(null);
  const [matches, setMatches] = useState<Match[]>([]);
  const [cases, setCases] = useState<CaseInfo[]>([]);
  const [notes, setNotes] = useState<Notification[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      api<{ items: Report[] }>("/reports?mine=true&page_size=50"),
      api<{ matches: Match[] }>("/matches"),
      api<{ cases: CaseInfo[] }>("/cases"),
      api<{ notifications: Notification[] }>("/notifications?limit=5"),
    ])
      .then(([r, m, c, n]) => {
        setReports(r.items);
        setMatches(m.matches);
        setCases(c.cases);
        setNotes(n.notifications);
      })
      .catch((e) => setError(e.message));
  }, []);

  if (error) return <ErrorBox message={error} />;
  if (!reports) return <Spinner />;

  const actionable = matches.filter(
    (m) => (m.my_role === "owner" && ["POTENTIAL_MATCH", "VERIFICATION_PENDING"].includes(m.status)) ||
      (m.my_role === "finder" && m.status === "AWAITING_FINDER_REVIEW"),
  );
  const openCases = cases.filter((c) => c.status === "CONNECTED");

  return (
    <div className="space-y-8">
      <PageHeader
        title={`Hi, ${user?.name.split(" ")[0]}`}
        subtitle="Here's everything happening with your lost and found reports."
        action={
          <div className="flex gap-2">
            <Link href="/report/lost" className="btn-primary">Report lost item</Link>
            <Link href="/report/found" className="btn-secondary">Report found item</Link>
          </div>
        }
      />

      <div className="grid gap-4 sm:grid-cols-4">
        {[
          ["My reports", reports.length, "/dashboard"],
          ["Needs your action", actionable.length, "/matches"],
          ["Open cases", openCases.length, "/cases"],
          ["Recovered", reports.filter((r) => r.status === "RECOVERED").length, "/cases"],
        ].map(([label, n, href]) => (
          <Link key={label as string} href={href as string} className="card hover:shadow-md">
            <p className="text-sm text-slate-500">{label}</p>
            <p className="mt-1 text-3xl font-bold text-slate-900">{n}</p>
          </Link>
        ))}
      </div>

      {actionable.length > 0 && (
        <section className="card border-amber-200 bg-amber-50/50">
          <h2 className="mb-3 font-semibold text-slate-900">Needs your attention</h2>
          <ul className="space-y-2">
            {actionable.map((m) => (
              <li key={m.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-white p-3">
                <span className="text-sm">
                  {m.my_role === "owner"
                    ? <>Potential match for your item: <b>{m.other_report?.name}</b> ({m.score_percent}%)</>
                    : <>Someone answered verification questions for <b>{m.other_report?.name}</b></>}
                </span>
                <Link href={m.my_role === "finder" ? `/matches/${m.id}/verify` : `/matches/${m.id}`} className="btn-primary">
                  {m.my_role === "finder" ? "Review answers" : "View match"}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="grid gap-8 lg:grid-cols-3">
        <section className="lg:col-span-2">
          <h2 className="mb-3 font-semibold text-slate-900">My reports</h2>
          {reports.length === 0 ? (
            <Empty>No reports yet. Report a lost or found item to get started.</Empty>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              {reports.map((r) => <ReportCard key={r.id} report={r} />)}
            </div>
          )}
        </section>
        <section>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="font-semibold text-slate-900">Recent notifications</h2>
            <Link href="/notifications" className="text-sm text-brand-600 hover:underline">All</Link>
          </div>
          <div className="card divide-y divide-slate-100 p-0">
            {notes.length === 0 && <p className="p-4 text-sm text-slate-500">Nothing yet.</p>}
            {notes.map((n) => (
              <Link key={n.id} href={n.link ?? "/notifications"} className="block p-4 hover:bg-slate-50">
                <p className={`text-sm ${n.read ? "text-slate-600" : "font-semibold text-slate-900"}`}>{n.title}</p>
                <p className="text-xs text-slate-500">{timeAgo(n.created_at)}</p>
              </Link>
            ))}
          </div>
          {openCases.length > 0 && (
            <div className="mt-6 space-y-2">
              <h2 className="font-semibold text-slate-900">Open cases</h2>
              {openCases.map((c) => (
                <Link key={c.id} href={`/cases/${c.id}`} className="card flex items-center justify-between p-4 hover:shadow-md">
                  <span className="text-sm font-medium">{c.lost_report.name}</span>
                  <StatusBadge status={c.status} />
                </Link>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  return (
    <Protected>
      <Dashboard />
    </Protected>
  );
}
