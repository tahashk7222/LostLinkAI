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
  my_answers?: Record<string, string> | null;  // owner only: their own answers
}

interface CaseInfo {
  id: number;
  status: string;
  possession_confirmed_at: string | null;
}

function Verify() {
  const { id } = useParams<{ id: string }>();
  const [match, setMatch] = useState<Match | null>(null);
  const [v, setV] = useState<VerificationState | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmReject, setConfirmReject] = useState(false);
  const [caseInfo, setCaseInfo] = useState<CaseInfo | null>(null);

  const load = useCallback(async () => {
    try {
      const [m, ver] = await Promise.all([api<Match>(`/matches/${id}`), api<VerificationState>(`/matches/${id}/verification`)]);
      setMatch(m);
      setV(ver);
      if (m.case_id && m.my_role === "finder") setCaseInfo(await api<CaseInfo>(`/cases/${m.case_id}`));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [id]);

  // Possession is a separate statement from ownership: "I still have this item" or "I no longer have this item".
  async function confirmPossession(stillHave: boolean) {
    if (!match?.case_id) return;
    setBusy(true);
    setError("");
    try {
      setCaseInfo(await api<CaseInfo>(`/cases/${match.case_id}/possession`, { method: "POST", json: { still_have: stillHave } }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }
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
            Verification completed successfully. The finder will confirm whether they still have the item. <Link className="font-semibold underline" href={`/cases/${match.case_id}`}>Open messages</Link> to arrange recovery.
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
      <PageHeader title="Verify ownership claim" subtitle={`Someone believes the "${item}" you found is theirs.`} />
      {error && <ErrorBox message={error} />}
      {match.status === "AWAITING_FINDER_REVIEW" ? (
        <div className="space-y-4">
          <InfoBox>
            The potential owner has submitted ownership verification. Their details are private and are not shown to you.
            Confirm only if you are sure this person is the owner.
          </InfoBox>
          <InfoBox tone="warn">
            Accepting opens an in-app chat. No contact details are shared automatically.
          </InfoBox>
          <div className="flex flex-wrap gap-2">
            <button className="btn-primary" disabled={busy} onClick={() => decide("ACCEPT")}>Confirm this person is the owner</button>
            {!confirmReject ? (
              <button className="btn-secondary" disabled={busy} onClick={() => setConfirmReject(true)}>This is not the owner</button>
            ) : (
              <button className="btn-danger" disabled={busy} onClick={() => decide("REJECT")}>Confirm: reject claim</button>
            )}
          </div>
        </div>
      ) : match.status === "VERIFIED" && caseInfo?.status === "CLOSED" ? (
        <InfoBox>
          You told us you no longer have this item. The case is closed, and the item is back in circulation.
        </InfoBox>
      ) : match.status === "VERIFIED" && caseInfo?.possession_confirmed_at ? (
        <InfoBox tone="success">
          Thank you. The owner has been asked to arrange the handover in{" "}
          <Link className="font-semibold underline" href={`/cases/${match.case_id}`}>messages</Link>. Once the item is returned,
          the owner marks it recovered.
        </InfoBox>
      ) : match.status === "VERIFIED" ? (
        <div className="card space-y-4">
          <div>
            <h2 className="font-semibold text-slate-900">Verification passed</h2>
            <p className="mt-1 text-sm text-slate-600">Ownership verification completed successfully.</p>
          </div>
          <p className="font-medium text-slate-900">Please confirm whether you still have this item.</p>
          <div className="flex flex-wrap gap-2">
            <button className="btn-primary" disabled={busy} onClick={() => confirmPossession(true)}>I still have this item</button>
            <button className="btn-secondary" disabled={busy} onClick={() => confirmPossession(false)}>I no longer have this item</button>
          </div>
        </div>
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
