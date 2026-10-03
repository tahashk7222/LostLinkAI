"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { CATEGORIES } from "@/lib/region";
import type { Report } from "@/lib/types";
import { Empty, ErrorBox, PageHeader, Protected, ReportCard, Spinner } from "@/components/ui";

function Browse() {
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [category, setCategory] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<{ items: Report[]; total: number; page_size: number } | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const params = new URLSearchParams({ page: String(page), page_size: "12" });
    if (q.trim()) params.set("q", q.trim());
    if (type) params.set("report_type", type);
    if (category) params.set("category", category);
    const t = setTimeout(() => {
      api(`/reports?${params}`).then(setData).catch((e) => setError(e.message));
    }, 250);
    return () => clearTimeout(t);
  }, [q, type, category, page]);

  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <div>
      <PageHeader title="Browse reports" subtitle="Open lost and found reports in the region. Private details and contact info are never shown." />
      <div className="card mb-6 grid gap-3 sm:grid-cols-4">
        <input className="input sm:col-span-2" placeholder="Search: backpack, library, keys…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        <select className="input" value={type} onChange={(e) => { setType(e.target.value); setPage(1); }}>
          <option value="">Lost &amp; found</option>
          <option value="LOST">Lost only</option>
          <option value="FOUND">Found only</option>
        </select>
        <select className="input" value={category} onChange={(e) => { setCategory(e.target.value); setPage(1); }}>
          <option value="">All categories</option>
          {CATEGORIES.map((c) => <option key={c}>{c}</option>)}
        </select>
      </div>
      {error && <ErrorBox message={error} />}
      {!data ? (
        <Spinner />
      ) : data.items.length === 0 ? (
        <Empty>No reports match your search.</Empty>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {data.items.map((r) => <ReportCard key={r.id} report={r} />)}
          </div>
          {pages > 1 && (
            <div className="mt-6 flex items-center justify-center gap-3 text-sm">
              <button className="btn-secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
              <span>Page {page} of {pages}</span>
              <button className="btn-secondary" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default function BrowsePage() {
  return (
    <Protected>
      <Browse />
    </Protected>
  );
}
