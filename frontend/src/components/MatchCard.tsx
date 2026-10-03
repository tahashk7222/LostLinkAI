import Link from "next/link";
import type { Match } from "@/lib/types";
import { CONTEXT_SIGNALS, LeadBadge } from "./MatchEvidence";
import { ReportThumb, StatusBadge, TypeBadge } from "./ui";

export function MatchCard({ match }: { match: Match }) {
  const other = match.other_report;
  if (!other) return null;
  // Only identity details are listed here. Weak and context details appear on the match page.
  const top = match.evidence
    .filter((e) => e.direction === "supports" && e.strength !== "WEAK" && !CONTEXT_SIGNALS.includes(e.signal))
    .slice(0, 2);
  return (
    <Link href={`/matches/${match.id}`} className="card flex gap-4 transition hover:shadow-md">
      <div className="w-28 shrink-0">
        <ReportThumb report={other} className="h-24" />
      </div>
      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <LeadBadge lead={match.lead} percent={match.score_percent} />
          <StatusBadge status={match.status} />
        </div>
        <p className="font-semibold text-slate-900">
          <TypeBadge type={other.report_type} /> {other.name}
        </p>
        {match.lead === "WEAK" ? (
          <p className="text-xs text-amber-800">Only general details match. Not enough to notify you.</p>
        ) : (
          <ul className="text-xs text-slate-600">
            {top.map((e) => <li key={e.text}>✓ {e.text}</li>)}
          </ul>
        )}
      </div>
    </Link>
  );
}
