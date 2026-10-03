import Link from "next/link";
import type { Match } from "@/lib/types";
import { ConfidenceBadge, ReportThumb, StatusBadge, TypeBadge } from "./ui";

export function MatchCard({ match }: { match: Match }) {
  const other = match.other_report;
  if (!other) return null;
  return (
    <Link href={`/matches/${match.id}`} className="card flex gap-4 transition hover:shadow-md">
      <div className="w-28 shrink-0">
        <ReportThumb report={other} className="h-24" />
      </div>
      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <ConfidenceBadge confidence={match.confidence} percent={match.score_percent} />
          <StatusBadge status={match.status} />
        </div>
        <p className="font-semibold text-slate-900">
          <TypeBadge type={other.report_type} /> {other.name}
        </p>
        <ul className="text-xs text-slate-600">
          {match.explanation.filter((e) => !e.startsWith("Note:")).slice(0, 3).map((e) => <li key={e}>✓ {e}</li>)}
        </ul>
      </div>
    </Link>
  );
}
