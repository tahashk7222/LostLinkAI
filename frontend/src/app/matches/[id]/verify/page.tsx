"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Match, Question } from "@/lib/types";
import { ErrorBox, InfoBox, PageHeader, Protected, Spinner } from "@/components/ui";

interface VerificationState {
  status: string | null;
  match_status: string;
  questions?: Question[];
  my_answers?: Record<string, string> | null;
  answers?: Record<string, string>;
  advisory_score?: number;
  advisory_notes?: string[];
}

function Verify() {
  const { id } = useParams<{ id: string }>();
  const [match, setMatch] = useState<Match | null>(null);
  const [v, setV] = useState<VerificationState | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmReject, setConfirmReject] = useState(false);

  const load = useCallback(async () => {
    try {
      const [m, ver] = await Promise.all([api<Match>(`/matches/${id}`), api<VerificationState>(`/matches/${id}/verification`)]);
      setMatch(m);
      setV(ver);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [id]);
  useEffect(() => {
    load();
  }, [load]);

  async function submitAnswers(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api(`/matches/${id}/verification/answers`, { method: "POST", json: { answers } });
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function decide(decision: "ACCEPT" | "REJECT") {
    setBusy(true);
    setError("");
    try {
      await api(`/matches/${id}/verify`, { method: "POST", json: { decision } });
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (error && !match) return <ErrorBox message={error} />;
  if (!match || !v) return <Spinner />;
  const item = match.other_report?.name ?? "the item";

  // ---------- Owner ----------
  if (match.my_role === "owner") {
    return (
      <div className="mx-auto max-w-2xl space-y-6">
        <PageHeader title="Verify ownership" subtitle={`Answer privately to show that "${item}" is yours.`} />
        {error && <ErrorBox message={error} />}
        {match.status === "VERIFICATION_PENDING" && v.questions && (
          <form onSubmit={submitAnswers} className="card space-y-5">
            <InfoBox>
              Only the finder sees your answers. Describe details that are <b>not</b> in the public listing. Never share
              full card, bank or ID numbers.
            </InfoBox>
            {v.questions.map((q) => (
              <div key={q.id}>
                <label className="label" htmlFor={q.id}>{q.question}{q.optional ? "" : " *"}</label>
                <textarea id={q.id} rows={3} maxLength={1000} className="input" value={answers[q.id] ?? ""}
                  onChange={(e) => setAnswers({ ...answers, [q.id]: e.target.value })} />
              </div>
            ))}
            <button className="btn-primary w-full" disabled={busy}>{busy ? "Sending…" : "Send answers to finder"}</button>
          </form>
        )}
        {match.status === "AWAITING_FINDER_REVIEW" && (
          <InfoBox tone="info">Your answers were sent. The finder is checking them against the item, and we&apos;ll notify you.</InfoBox>
        )}
        {match.status === "VERIFIED" && (
          <InfoBox tone="success">
            Ownership verified by the finder. <Link className="font-semibold underline" href={`/cases/${match.case_id}`}>Open messages</Link> to arrange recovery.
          </InfoBox>
        )}
        {match.status === "REJECTED" && <InfoBox tone="warn">The finder could not confirm ownership from your answers. Your lost report stays active.</InfoBox>}
        {match.status === "POTENTIAL_MATCH" && (
          <Link href={`/matches/${id}`} className="btn-secondary">Back to match</Link>
        )}
      </div>
    );
  }

  // ---------- Finder ----------
  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <PageHeader title="Review ownership answers" subtitle={`Someone believes the "${item}" you found is theirs.`} />
      {error && <ErrorBox message={error} />}
      {match.status === "AWAITING_FINDER_REVIEW" && v.answers ? (
        <div className="space-y-4">
          <div className="card space-y-4">
            {v.questions?.map((q) => (
              <div key={q.id}>
                <p className="text-sm font-medium text-slate-700">{q.question}</p>
                <p className="mt-1 rounded-lg bg-slate-50 p-3 text-sm text-slate-800">{v.answers?.[q.id] || <i className="text-slate-400">No answer</i>}</p>
              </div>
            ))}
          </div>
          <div className="card space-y-2">
            <h2 className="font-semibold text-slate-900">LostLink AI check (advisory)</h2>
            <p className="text-sm">Consistency with your notes: <b>{Math.round((v.advisory_score ?? 0) * 100)}%</b></p>
            <ul className="list-disc pl-5 text-sm text-slate-600">
              {v.advisory_notes?.map((n) => <li key={n}>{n}</li>)}
            </ul>
          </div>
          <InfoBox tone="warn">
            You have the item, so you make the decision. Accept only if the answers clearly describe this item. Accepting
            opens an in-app chat. No contact details are shared automatically.
          </InfoBox>
          <div className="flex flex-wrap gap-2">
            <button className="btn-primary" disabled={busy} onClick={() => decide("ACCEPT")}>Answers match: confirm owner</button>
            {!confirmReject ? (
              <button className="btn-secondary" disabled={busy} onClick={() => setConfirmReject(true)}>Answers don&apos;t match</button>
            ) : (
              <button className="btn-danger" disabled={busy} onClick={() => decide("REJECT")}>Confirm: reject claim</button>
            )}
          </div>
        </div>
      ) : match.status === "VERIFIED" ? (
        <InfoBox tone="success">
          You confirmed the owner. <Link className="font-semibold underline" href={`/cases/${match.case_id}`}>Open messages</Link> to arrange the handover.
        </InfoBox>
      ) : match.status === "REJECTED" ? (
        <InfoBox tone="warn">You rejected this claim. Your found report remains active.</InfoBox>
      ) : (
        <InfoBox>No answers to review yet. We&apos;ll notify you when the possible owner submits them.</InfoBox>
      )}
    </div>
  );
}

export default function VerifyPage() {
  return (
    <Protected>
      <Verify />
    </Protected>
  );
}
