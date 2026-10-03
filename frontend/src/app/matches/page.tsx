"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Match } from "@/lib/types";
import { MatchCard } from "@/components/MatchCard";
import { Empty, ErrorBox, PageHeader, Protected, Spinner } from "@/components/ui";

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
        {asOwner.length === 0 ? <Empty>No potential matches for your lost items yet.</Empty> : (
          <div className="grid gap-4 md:grid-cols-2">{asOwner.map((m) => <MatchCard key={m.id} match={m} />)}</div>
        )}
      </section>
      <section>
        <h2 className="mb-3 font-semibold text-slate-900">For items you found</h2>
        {asFinder.length === 0 ? <Empty>No lost reports have matched items you found yet.</Empty> : (
          <div className="grid gap-4 md:grid-cols-2">{asFinder.map((m) => <MatchCard key={m.id} match={m} />)}</div>
        )}
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
