"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, imageUrl } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { LeadBadge, LeadDescription, MatchEvidence, ReferenceBadge } from "@/components/MatchEvidence";
import type { Match } from "@/lib/types";
import { ErrorBox, InfoBox, Protected, Spinner, StatusBadge, TypeBadge } from "@/components/ui";

const SIGNAL_LABELS: Record<string, string> = {
  category: "Item type",
  text: "Description",
  color: "Colour",
  brand: "Brand",
  features: "Distinctive features",
  image: "Photo similarity",
  location: "Location",
  time: "Time",
};

function MatchDetails() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [m, setM] = useState<Match | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api<Match>(`/matches/${id}`).then(setM).catch((e) => setError(e.message));
  }, [id]);
  useEffect(() => {
    load();
  }, [load]);

  async function startVerification() {
    setBusy(true);
    try {
      await api(`/matches/${id}/verification`, { method: "POST" });
      router.push(`/matches/${id}/verify`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  async function dismiss() {
    try {
      await api(`/matches/${id}/dismiss`, { method: "POST" });
      router.push("/matches");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (error && !m) return <ErrorBox message={error} />;
  if (!m) return <Spinner />;
  const other = m.other_report;

  return (
    <div className="space-y-6">
      {error && <ErrorBox message={error} />}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm text-slate-500">Potential match #{m.id}</p>
          <h1 className="text-2xl font-bold text-slate-900">{other?.name}</h1>
        </div>
        <div className="flex items-center gap-2">
          <LeadBadge lead={m.lead} percent={m.score_percent} />
          {m.lead === "WEAK" ? <ReferenceBadge /> : <StatusBadge status={m.status} />}
        </div>
      </div>

      <InfoBox tone="warn">{m.disclaimer}</InfoBox>

      <div className="grid gap-6 lg:grid-cols-2">
        {other && (
          <div className="card space-y-3">
            <div className="flex items-center gap-2">
              <TypeBadge type={other.report_type} />
              <span className="text-sm text-slate-500">reported by {other.reporter_name}</span>
            </div>
            {other.images.length > 0 && (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={imageUrl(other.images[0].url)} alt={other.name} className="h-64 w-full rounded-xl object-cover" />
            )}
            <p className="text-slate-700">{other.description}</p>
            <ul className="space-y-1 text-sm text-slate-600">
              <li>📍 {other.location}</li>
              <li>🕒 {formatDate(other.date_time)}</li>
              {other.color && <li>🎨 {other.color}</li>}
              {other.brand && <li>🏷️ {other.brand} {other.model ?? ""}</li>}
              {other.distinctive_features && <li>✨ {other.distinctive_features}</li>}
            </ul>
          </div>
        )}

        <div className="space-y-6">
          <div className="card space-y-4">
            <h2 className="font-semibold text-slate-900">Why LostLink suggested this</h2>
            <LeadDescription lead={m.lead} />
            {m.evidence.length > 0 ? (
              <MatchEvidence evidence={m.evidence} lead={m.lead} />
            ) : (
              <ul className="space-y-1.5 text-sm">
                {m.explanation.map((r) => (
                  <li key={r} className={r.startsWith("Note:") ? "text-amber-700" : "text-slate-700"}>
                    {r.startsWith("Note:") ? `⚠ ${r.slice(6)}` : `✓ ${r}`}
                  </li>
                ))}
              </ul>
            )}
            <div className="space-y-2 border-t border-slate-100 pt-4">
              {Object.entries(m.signals).map(([k, v]) => (
                <div key={k} className="flex items-center gap-3 text-xs">
                  <span className="w-36 text-slate-500">{SIGNAL_LABELS[k] ?? k}</span>
                  <div className="h-2 flex-1 rounded-full bg-slate-100">
                    <div className="h-2 rounded-full bg-brand-500" style={{ width: `${Math.round(v * 100)}%` }} />
                  </div>
                  <span className="w-9 text-right text-slate-600">{Math.round(v * 100)}%</span>
                </div>
              ))}
            </div>
            <p className="mt-3 text-xs text-slate-500">
              Signal values come from fixed rules. They are not probabilities, and a missing bar means that detail could not be compared.
            </p>
            {m.signals.image !== undefined && (
              <p className="mt-3 text-xs text-slate-500">Photo similarity compares colours and overall shape. It does not recognise the object itself.</p>
            )}
          </div>

          <div className="card space-y-3">
            <h2 className="font-semibold text-slate-900">Next step</h2>
            {m.my_role === "owner" && m.status === "POTENTIAL_MATCH" && m.lead !== "WEAK" && (
              <>
                <p className="text-sm text-slate-600">
                  If this looks like yours, verify ownership by answering a few private questions. The finder will compare
                  your answers with the item. Your contact details stay private.
                </p>
                <div className="flex flex-wrap gap-2">
                  <button className="btn-primary" onClick={startVerification} disabled={busy}>Verify ownership</button>
                  <button className="btn-secondary" onClick={dismiss}>Not mine</button>
                </div>
              </>
            )}
            {m.my_role === "owner" && m.status === "POTENTIAL_MATCH" && m.lead === "WEAK" && (
              <>
                <p className="text-sm text-slate-600">
                  This is a Weak lead. Shared general details are not enough to show that the item is yours, so ownership
                  cannot be verified from it. If it is not yours, mark it so it is removed from your list.
                </p>
                <div className="flex flex-wrap gap-2">
                  <button className="btn-secondary" onClick={dismiss}>Not mine</button>
                </div>
              </>
            )}
            {m.my_role === "owner" && m.status === "VERIFICATION_PENDING" && (
              <Link href={`/matches/${m.id}/verify`} className="btn-primary">Continue verification</Link>
            )}
            {m.status === "AWAITING_FINDER_REVIEW" && (
              m.my_role === "finder"
                ? <Link href={`/matches/${m.id}/verify`} className="btn-primary">Review ownership answers</Link>
                : <p className="text-sm text-slate-600">Your answers were sent. The finder is reviewing them, and we&apos;ll notify you.</p>
            )}
            {m.my_role === "finder" && ["POTENTIAL_MATCH", "VERIFICATION_PENDING"].includes(m.status) && (
              <p className="text-sm text-slate-600">The possible owner hasn&apos;t submitted verification answers yet. We&apos;ll notify you when they do.</p>
            )}
            {m.status === "VERIFIED" && m.case_id && (
              <Link href={`/cases/${m.case_id}`} className="btn-primary">Open case &amp; messages</Link>
            )}
            {m.my_role === "owner" && m.status === "REJECTED" && (m.verification_attempts_left ?? 0) > 0 && (
              <>
                <p className="text-sm text-slate-600">
                  Ownership was not confirmed for this match. Your report remains active. You can try again
                  ({m.verification_attempts_left} {m.verification_attempts_left === 1 ? "attempt" : "attempts"} left).
                </p>
                <button className="btn-primary" onClick={startVerification} disabled={busy}>Try verification again</button>
              </>
            )}
            {m.my_role === "owner" && m.status === "REJECTED" && (m.verification_attempts_left ?? 0) === 0 && (
              <p className="text-sm text-slate-600">
                Ownership could not be confirmed for this match, and no verification attempts are left. Your report remains active.
              </p>
            )}
            {m.status === "REJECTED" && m.my_role !== "owner" && (
              <p className="text-sm text-slate-600">Ownership was not confirmed for this match. Your report remains active.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function MatchPage() {
  return (
    <Protected>
      <MatchDetails />
    </Protected>
  );
}
