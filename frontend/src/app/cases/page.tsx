"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { CaseInfo } from "@/lib/types";
import { Empty, ErrorBox, PageHeader, Protected, ReportThumb, Spinner, StatusBadge } from "@/components/ui";

function Cases() {
  const [cases, setCases] = useState<CaseInfo[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api<{ cases: CaseInfo[] }>("/cases").then((r) => setCases(r.cases)).catch((e) => setError(e.message));
  }, []);
  if (error) return <ErrorBox message={error} />;
  if (!cases) return <Spinner />;
  return (
    <div>
      <PageHeader title="Recovery cases" subtitle="Cases open once a finder has confirmed ownership." />
      {cases.length === 0 ? <Empty>No cases yet.</Empty> : (
        <div className="grid gap-4 md:grid-cols-2">
          {cases.map((c) => (
            <Link key={c.id} href={`/cases/${c.id}`} className="card flex gap-4 hover:shadow-md">
              <div className="w-24 shrink-0"><ReportThumb report={c.found_report} className="h-20" /></div>
              <div className="space-y-1">
                <StatusBadge status={c.status} />
                <p className="font-semibold text-slate-900">{c.lost_report.name}</p>
                <p className="text-xs text-slate-500">
                  {c.my_role === "owner" ? `Found by ${c.finder_name}` : `Owner: ${c.owner_name}`} · updated {formatDate(c.updated_at)}
                </p>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

export default function CasesPage() {
  return (
    <Protected>
      <Cases />
    </Protected>
  );
}
