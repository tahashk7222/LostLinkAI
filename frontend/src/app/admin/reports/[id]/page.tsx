"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api, imageUrl } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { ErrorBox, InfoBox, PageHeader, Protected, Spinner, StatusBadge, TypeBadge } from "@/components/ui";

interface ModerationView {
  id: number;
  report_type: "LOST" | "FOUND";
  name: string;
  description: string;
  category: string;
  brand: string | null;
  model: string | null;
  color: string | null;
  distinctive_features: string | null;
  location: string;
  zone: string | null;
  location_type: string | null;
  date_time: string;
  created_at: string;
  status: string;
  reporter_name: string;
  reporter_email: string;
  ai_status: string;
  images: { id: number; url: string }[];
  attributes: { name: string; value: string; source: string }[];
  moderation: { reason: string | null; note: string | null; moderated_at: string | null };
  archived_at: string | null;
  matches: { id: number; status: string; lead: string | null; relevance_percent: number; case_id: number | null }[];
}

// Reasons come from the backend's closed list (ModerationReason). Labels are for admins only.
const REASONS: [string, string][] = [
  ["FAKE_OR_JOKE", "Fake or joke"],
  ["OUTSIDE_UET_AREA", "Outside the UET Lahore area"],
  ["INVALID_ITEM", "Invalid item"],
  ["INAPPROPRIATE_CONTENT", "Inappropriate content"],
  ["DUPLICATE_REPORT", "Duplicate report"],
  ["INSUFFICIENT_INFORMATION", "Insufficient information"],
  ["SUSPICIOUS_ACTIVITY", "Suspicious activity"],
  ["OTHER", "Other"],
];

function Review() {
  const { id } = useParams<{ id: string }>();
  const [r, setR] = useState<ModerationView | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [reason, setReason] = useState("FAKE_OR_JOKE");
  const [note, setNote] = useState("");

  function load() {
    api<ModerationView>(`/admin/reports/${id}`).then(setR).catch((e) => setError(e.message));
  }
  useEffect(load, [id]);

  async function approve() {
    setBusy(true);
    setError("");
    try {
      await api(`/admin/reports/${id}/approve`, { method: "POST" });
      setMessage("Approved. The report stays live and its review is recorded in the audit log.");
      load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function reject() {
    const label = REASONS.find(([k]) => k === reason)?.[1] ?? reason;
    if (!window.confirm(`Reject this report (${label})? It will leave matching immediately. The owner will be notified.`)) return;
    setBusy(true);
    setError("");
    try {
      await api(`/admin/reports/${id}/reject`, { method: "POST", json: { reason, note: note.trim() || null } });
      setMessage("Rejected. The report no longer takes part in matching.");
      setNote("");
      load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (error && !r) return <ErrorBox message={error} />;
  if (!r) return <Spinner />;

  const open = r.status === "ACTIVE" || r.status === "POTENTIAL_MATCH";
  return (
    <div className="space-y-6">
      <Link href="/admin" className="text-sm text-brand-600 hover:underline">← Back to the admin dashboard</Link>
      <PageHeader title={`Review report #${r.id}`} subtitle="Moderation view. Private details, exact coordinates and verification answers are not shown." />
      {error && <ErrorBox message={error} />}
      {message && <InfoBox tone="success">{message}</InfoBox>}
      {r.zone === "nearby" && (
        <InfoBox tone="warn">⚠ Within the nearby area, outside the campus boundary. Check the location before approving.</InfoBox>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="card space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <TypeBadge type={r.report_type} />
            <StatusBadge status={r.status} />
            {r.archived_at && <span className="rounded-full bg-slate-200 px-2.5 py-0.5 text-xs font-semibold text-slate-700">Archived {formatDate(r.archived_at)}</span>}
          </div>
          {r.images.length > 0 && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={imageUrl(r.images[0].url)} alt={r.name} className="h-64 w-full rounded-xl object-cover" />
          )}
          <h2 className="text-lg font-semibold text-slate-900">{r.name}</h2>
          <p className="text-slate-700">{r.description}</p>
          <ul className="space-y-1 text-sm text-slate-600">
            <li>Category: {r.category}</li>
            {r.brand && <li>Brand: {r.brand} {r.model ?? ""}</li>}
            {r.color && <li>Colour: {r.color}</li>}
            {r.distinctive_features && <li>Distinctive features: {r.distinctive_features}</li>}
            <li>Location: {r.location}{r.zone ? ` (${r.zone})` : ""}</li>
            <li>Date and time: {formatDate(r.date_time)}</li>
            <li>Created: {formatDate(r.created_at)}</li>
            <li>Reported by: {r.reporter_name} ({r.reporter_email})</li>
          </ul>
        </div>

        <div className="space-y-6">
          <div className="card space-y-3">
            <h2 className="font-semibold text-slate-900">Automated checks</h2>
            <p className="text-xs text-slate-500">Signals from the system, not decisions. The admin decides below.</p>
            <p className="text-sm text-slate-700">AI matching: {r.ai_status}</p>
            <ul className="space-y-1 text-sm text-slate-600">
              {r.attributes.map((a) => (
                <li key={`${a.name}-${a.value}`}>{a.name}: {a.value} <span className="text-xs text-slate-400">({a.source.toLowerCase()})</span></li>
              ))}
              {r.attributes.length === 0 && <li className="text-slate-500">No extracted attributes.</li>}
            </ul>
          </div>

          <div className="card space-y-3">
            <h2 className="font-semibold text-slate-900">Matches</h2>
            {r.matches.length === 0 && <p className="text-sm text-slate-500">No matches for this report.</p>}
            {r.matches.map((m) => (
              <div key={m.id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
                <span>Match #{m.id} · {m.lead ?? "—"} lead · {m.status}</span>
                <span className="text-xs text-slate-500">
                  relevance {m.relevance_percent}%{m.case_id ? <> · <Link className="text-brand-600 hover:underline" href={`/admin/cases/${m.case_id}`}>Case #{m.case_id}</Link></> : ""}
                </span>
              </div>
            ))}
          </div>

          <div className="card space-y-4">
            <h2 className="font-semibold text-slate-900">Moderation decision</h2>
            {r.moderation.reason && (
              <p className="text-sm text-slate-700">Rejected: {REASONS.find(([k]) => k === r.moderation.reason)?.[1] ?? r.moderation.reason}
                {r.moderation.note ? ` · “${r.moderation.note}”` : ""}</p>
            )}
            {open ? (
              <>
                <button className="btn-secondary" onClick={approve} disabled={busy}>Approve (keep live)</button>
                <div className="space-y-3 border-t border-slate-100 pt-4">
                  <label className="label" htmlFor="reason">Reason for rejecting</label>
                  <select id="reason" className="input" value={reason} onChange={(e) => setReason(e.target.value)}>
                    {REASONS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                  </select>
                  <label className="label" htmlFor="note">Note for the record (optional)</label>
                  <textarea id="note" rows={2} maxLength={500} className="input" value={note} onChange={(e) => setNote(e.target.value)} />
                  <button className="btn-danger" onClick={reject} disabled={busy}>Reject report</button>
                </div>
              </>
            ) : (
              <p className="text-sm text-slate-600">This report is not open ({r.status}). Decisions apply to open reports only.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function ReportReviewPage() {
  return (
    <Protected admin>
      <Review />
    </Protected>
  );
}
