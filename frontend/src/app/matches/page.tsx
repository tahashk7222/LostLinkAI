"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Match } from "@/lib/types";
import { MatchCard } from "@/components/MatchCard";
import { Empty, ErrorBox, PageHeader, Protected, Spinner } from "@/components/ui";

// Weak leads are kept for reference, but only this many are listed before "Show more".
const WEAK_LEADS_SHOWN = 5;

function MatchList({ matches, empty }: { matches: Match[]; empty: string }) {
  const [showAllWeak, setShowAllWeak] = useState(false);
  if (matches.length === 0) return <Empty>{empty}</Empty>;
  const stronger = matches.filter((m) => m.lead !== "WEAK");
  const weak = matches.filter((m) => m.lead === "WEAK");
  const shownWeak = showAllWeak ? weak : weak.slice(0, WEAK_LEADS_SHOWN);
  const hidden = weak.length - shownWeak.length;
  return (
    <div className="space-y-4">
      {stronger.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2">{stronger.map((m) => <MatchCard key={m.id} match={m} />)}</div>
      )}
      {weak.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-sm font-semibold text-slate-600">
            Weak leads ({weak.length}). Shared general details only. These do not notify you and cannot be verified.
          </h3>
          <div className="grid gap-4 md:grid-cols-2">{shownWeak.map((m) => <MatchCard key={m.id} match={m} />)}</div>
          {hidden > 0 && (
            <button type="button" className="btn-secondary" onClick={() => setShowAllWeak(true)}>
              Show {hidden} more weak {hidden === 1 ? "lead" : "leads"}
            </button>
          )}
          {showAllWeak && weak.length > WEAK_LEADS_SHOWN && (
            <button type="button" className="btn-secondary" onClick={() => setShowAllWeak(false)}>
              Show fewer weak leads
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function Matches() {
  const [matches, setMatches] = useState<Match[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api<{ matches: Match[] }>("/matches").then((r) => setMatches(r.matches)).catch((e) => setError(e.message));
  }, []);

  if (error) return <ErrorBox message={error} />;
  if (!matches) return <Spinner />;
  const asOwner = matches.filter((m) => m.my_role === "owner");
  const asFinder = matches.filter((m) => m.my_role === "finder");

  return (
    <div className="space-y-8">
      <PageHeader title="Potential matches" subtitle="Suggested by LostLink AI. A match is a lead, not proof. Ownership is always verified by people." />
      <section>
        <h2 className="mb-3 font-semibold text-slate-900">For items you lost</h2>
        <MatchList matches={asOwner} empty="No potential matches for your lost items yet." />
      </section>
      <section>
        <h2 className="mb-3 font-semibold text-slate-900">For items you found</h2>
        <MatchList matches={asFinder} empty="No lost reports have matched items you found yet." />
      </section>
    </div>
  );
}

export default function MatchesPage() {
  return (
    <Protected>
      <Matches />
    </Protected>
  );
}
