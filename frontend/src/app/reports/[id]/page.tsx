"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { api, imageUrl } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { Match, Report } from "@/lib/types";
import dynamic from "next/dynamic";
import { loadGeoConfig, type GeoConfig } from "@/lib/geo";
import { MatchCard } from "@/components/MatchCard";
import { Empty, ErrorBox, InfoBox, Protected, Spinner, StatusBadge, TypeBadge, ZoneBadge } from "@/components/ui";

const CampusMap = dynamic(() => import("@/components/CampusMap").then((m) => m.CampusMap), { ssr: false });

function Field({ label, value }: { label: string; value?: string | null }) {
  if (!value) return null;
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="text-sm text-slate-800">{value}</dd>
    </div>
  );
}

function ReportDetails() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const params = useSearchParams();
  const [report, setReport] = useState<Report | null>(null);
  const [matches, setMatches] = useState<Match[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [flagging, setFlagging] = useState(false);
  const [flagReason, setFlagReason] = useState("");
  const [notice, setNotice] = useState(params.get("created") ? "Report saved." : "");
  const photoErrors = Number(params.get("photo_errors") ?? 0);
  const [geo, setGeo] = useState<GeoConfig | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api<Report>(`/reports/${id}`);
      setReport(r);
      if (r.is_owner) {
        setMatches((await api<{ matches: Match[] }>(`/reports/${id}/matches`)).matches);
        if (r.latitude != null && r.zone) loadGeoConfig().then(setGeo).catch(() => {});
      }
    } catch (e) {
      setError((e as Error).message);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  async function rematch() {
    setBusy(true);
    setError("");
    try {
      const r = await api<{ matches: Match[] }>(`/reports/${id}/match`, { method: "POST" });
      setNotice(r.matches.length ? `Found ${r.matches.length} potential match(es).` : "No potential matches yet. We'll keep looking as new reports arrive.");
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function addPhoto(file: File | undefined) {
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    setBusy(true);
    try {
      await api(`/reports/${id}/images`, { method: "POST", body });
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function closeReport() {
    try {
      await api(`/reports/${id}`, { method: "PUT", json: { status: "CLOSED" } });
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function remove() {
    try {
      await api(`/reports/${id}`, { method: "DELETE" });
      router.push("/dashboard");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function flag() {
    try {
      await api("/flags", { method: "POST", json: { entity_type: "report", entity_id: Number(id), reason: flagReason } });
      setFlagging(false);
      setNotice("Thanks. A moderator will review this report.");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (error && !report) return <ErrorBox message={error} />;
  if (!report) return <Spinner />;
  const open = ["ACTIVE", "POTENTIAL_MATCH"].includes(report.status);
  const userAttrs = report.attributes?.filter((a) => a.source === "RULE") ?? [];

  return (
    <div className="grid gap-8 lg:grid-cols-5">
      <div className="space-y-4 lg:col-span-3">
        {notice && <InfoBox tone="success">{notice}</InfoBox>}
        {photoErrors > 0 && (
          <InfoBox tone="warn">{photoErrors} photo{photoErrors > 1 ? "s" : ""} failed to upload. You can add photos again below.</InfoBox>
        )}
        {error && <ErrorBox message={error} />}
        <div className="card space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <TypeBadge type={report.report_type} />
            <StatusBadge status={report.status} />
            {report.is_owner && <span className="text-xs text-slate-500">Your report</span>}
          </div>
          <h1 className="text-2xl font-bold text-slate-900">{report.name}</h1>
          {report.images.length > 0 ? (
            <div className="grid grid-cols-2 gap-2">
              {report.images.map((img) => (
                // eslint-disable-next-line @next/next/no-img-element
                <img key={img.id} src={imageUrl(img.url)} alt={report.name} className="h-56 w-full rounded-xl object-cover" />
              ))}
            </div>
          ) : (
            <div className="grid h-40 place-items-center rounded-xl bg-slate-100 text-sm text-slate-400">No photo</div>
          )}
          <p className="text-slate-700">{report.description}</p>
          <dl className="grid gap-3 sm:grid-cols-2">
            <Field label="Category" value={report.category} />
            <Field label={report.report_type === "LOST" ? "Lost around" : "Found around"} value={formatDate(report.date_time)} />
            <div>
              <dt className="text-xs uppercase tracking-wide text-slate-500">Location</dt>
              <dd className="flex flex-wrap items-center gap-2 text-sm text-slate-800">{report.location} <ZoneBadge zone={report.zone} /></dd>
            </div>
            <Field label="Colour" value={report.color} />
            <Field label="Brand" value={report.brand} />
            <Field label="Model" value={report.model} />
            <Field label="Distinctive features" value={report.distinctive_features} />
            <Field label="Reported by" value={report.is_owner ? "You" : report.reporter_name} />
          </dl>
          {report.is_owner && geo && report.latitude != null && report.longitude != null && (
            <div>
              <p className="mb-1 text-xs text-slate-500">🔒 Exact pin (only you see this; others see &ldquo;{report.location}&rdquo;)</p>
              <CampusMap config={geo} point={{ lat: report.latitude, lng: report.longitude }} height={200} label="Map showing where you reported the item" />
            </div>
          )}
          {report.is_owner && report.private_details && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm">
              <p className="font-medium text-amber-900">🔒 Private details (only you)</p>
              <p className="text-amber-900">{report.private_details}</p>
            </div>
          )}
        </div>

        {report.is_owner ? (
          <div className="card flex flex-wrap gap-2">
            {open && report.images.length < 4 && (
              <label className="btn-secondary cursor-pointer">
                Add photo
                <input type="file" accept="image/jpeg,image/png,image/webp" hidden onChange={(e) => addPhoto(e.target.files?.[0])} />
              </label>
            )}
            {open && <button className="btn-secondary" onClick={closeReport}>Close report</button>}
            {!confirmDelete ? (
              <button className="btn-secondary text-rose-600" onClick={() => setConfirmDelete(true)}>Delete</button>
            ) : (
              <span className="flex items-center gap-2 text-sm">
                Delete permanently?
                <button className="btn-danger" onClick={remove}>Yes, delete</button>
                <button className="btn-secondary" onClick={() => setConfirmDelete(false)}>Cancel</button>
              </span>
            )}
          </div>
        ) : (
          <div className="text-right">
            {!flagging ? (
              <button className="text-xs text-slate-500 hover:text-rose-600" onClick={() => setFlagging(true)}>Report this listing</button>
            ) : (
              <div className="card space-y-2 text-left">
                <label className="label">Why should a moderator review this?</label>
                <input className="input" value={flagReason} onChange={(e) => setFlagReason(e.target.value)} />
                <div className="flex gap-2">
                  <button className="btn-danger" disabled={flagReason.trim().length < 5} onClick={flag}>Submit</button>
                  <button className="btn-secondary" onClick={() => setFlagging(false)}>Cancel</button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {report.is_owner && (
        <aside className="space-y-4 lg:col-span-2">
          <div className="card space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold text-slate-900">Potential matches</h2>
              {open && <button className="btn-secondary" onClick={rematch} disabled={busy}>{busy ? "Searching…" : "Search again"}</button>}
            </div>
            {report.ai_status === "FAILED" && <ErrorBox message={report.ai_error ?? "Automatic matching failed. Please retry."} />}
            {report.ai_status === "PENDING" && <p className="text-sm text-slate-500">Analysing your report…</p>}
            {matches === null ? <Spinner /> : matches.length === 0 ? (
              <Empty>No potential matches yet. LostLink AI checks again whenever a new {report.report_type === "LOST" ? "found" : "lost"} report is added.</Empty>
            ) : (
              <div className="space-y-3">{matches.map((m) => <MatchCard key={m.id} match={m} />)}</div>
            )}
          </div>
          {userAttrs.length > 0 && (
            <div className="card">
              <h3 className="mb-2 text-sm font-semibold text-slate-900">What LostLink AI understood</h3>
              <p className="mb-2 text-xs text-slate-500">Inferred automatically from your description. These are not facts you entered.</p>
              <div className="flex flex-wrap gap-1.5">
                {userAttrs.map((a, i) => (
                  <span key={i} className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs text-slate-700">
                    {a.attribute_name}: {a.attribute_value}
                  </span>
                ))}
              </div>
            </div>
          )}
        </aside>
      )}
    </div>
  );
}

export default function ReportDetailsPage() {
  return (
    <Protected>
      <Suspense>
        <ReportDetails />
      </Suspense>
    </Protected>
  );
}
