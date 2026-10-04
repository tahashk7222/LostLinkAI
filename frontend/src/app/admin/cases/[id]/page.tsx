"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { ErrorBox, InfoBox, PageHeader, Protected, Spinner, StatusBadge } from "@/components/ui";

interface Item {
  id: number;
  report_type: string;
  name: string;
  status: string;
  active_listing: boolean;
  matching_eligible: boolean;
  archived: boolean;
  archived_at: string | null;
}

interface CaseView {
  id: number;
  status: string;
  created_at: string;
  updated_at: string;
  match: { id: number; status: string; score_percent: number; lead: string | null };
  lost: Item;
  found: Item;
  verification_status: string | null;
  recovery_confirmed: boolean;
  actions: { id: number; action: string; entity_type: string | null; entity_id: number | null; timestamp: string; meta: any }[];
}

const VERIFICATION_LABEL: Record<string, string> = {
  pending: "Pending", in_progress: "In progress", verified: "Verified", failed: "Failed", cancelled: "Cancelled",
};

function Flag({ on, yes, no }: { on: boolean; yes: string; no: string }) {
  return (
    <li className="flex items-center justify-between gap-4 py-2 text-sm">
      <span className="text-slate-600">{on ? yes : no}</span>
      <span className={on ? "font-semibold text-emerald-700" : "font-semibold text-slate-500"}>{on ? "Yes" : "No"}</span>
    </li>
  );
}

function CaseRecovery() {
  const { id } = useParams<{ id: string }>();
  const [c, setC] = useState<CaseView | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  function load() {
    api<CaseView>(`/admin/cases/${id}`).then(setC).catch((e) => setError(e.message));
  }
  useEffect(load, [id]);

  async function close() {
    if (!window.confirm("Close this case? Both items leave circulation and the record is kept in the audit log.")) return;
    try {
      await api(`/admin/cases/${id}/close`, { method: "POST" });
      setMessage("Case closed. Both users have been notified.");
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (error && !c) return <ErrorBox message={error} />;
  if (!c) return <Spinner />;

  const canClose = c.status === "CONNECTED" || c.status === "RECOVERED";
  return (
    <div className="space-y-6">
      <Link href="/admin" className="text-sm text-brand-600 hover:underline">← Back to the admin dashboard</Link>
      <PageHeader title={`Recovery case #${c.id}`} subtitle="Confirms what happened to the items. Owner answers and messages are not shown here." />
      {error && <ErrorBox message={error} />}
      {message && <InfoBox tone="success">{message}</InfoBox>}

      <div className="flex flex-wrap items-center gap-3">
        <StatusBadge status={c.status} />
        <span className="text-sm text-slate-600">Match #{c.match.id} · {c.match.lead ?? "—"} lead · relevance {c.match.score_percent}%</span>
        <span className="text-sm text-slate-600">Ownership verification: {VERIFICATION_LABEL[c.verification_status ?? ""] ?? "None"}</span>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {[c.lost, c.found].map((item) => (
          <div key={item.id} className="card">
            <p className="text-xs uppercase text-slate-500">{item.report_type === "LOST" ? "Lost item" : "Found item"}</p>
            <h2 className="mb-2 font-semibold text-slate-900">
              <Link className="text-brand-600 hover:underline" href={`/admin/reports/${item.id}`}>#{item.id} {item.name}</Link>
            </h2>
            <div className="mb-2"><StatusBadge status={item.status} /></div>
            <ul className="divide-y divide-slate-100">
              <Flag on={item.active_listing} yes="Shown in active listings" no="Not in active listings" />
              <Flag on={item.matching_eligible} yes="Eligible for matching" no="Not eligible for matching" />
              <Flag on={item.archived} yes={`Archived ${item.archived_at ? formatDate(item.archived_at) : ""}`} no="Not archived" />
            </ul>
          </div>
        ))}
      </div>

      <div className="card space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-semibold text-slate-900">Recovery confirmation</h2>
          <span className={c.recovery_confirmed ? "font-semibold text-emerald-700" : "text-slate-500"}>
            {c.recovery_confirmed ? "Item recovered" : "Not recovered yet"}
          </span>
        </div>
        <p className="text-sm text-slate-600">
          Recovered items leave active listings and matching, and their records are archived rather than deleted.
        </p>
        {canClose && (
          <button className="btn-danger" onClick={close}>Close case</button>
        )}
      </div>

      <div className="card">
        <h2 className="mb-2 font-semibold text-slate-900">Admin and case activity</h2>
        {c.actions.length === 0 && <p className="text-sm text-slate-500">No recorded actions yet.</p>}
        <ul className="divide-y divide-slate-100">
          {c.actions.map((a) => (
            <li key={a.id} className="py-2 text-sm">
              <span className="font-mono text-xs">{a.action}</span>
              <span className="ml-2 text-xs text-slate-500">{a.entity_type ? `${a.entity_type} #${a.entity_id}` : ""} · {formatDate(a.timestamp)}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export default function CaseRecoveryPage() {
  return (
    <Protected admin>
      <CaseRecovery />
    </Protected>
  );
}
