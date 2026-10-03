"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/lib/auth";
import { STATUS_LABELS } from "@/lib/format";
import { imageUrl } from "@/lib/api";
import type { Report } from "@/lib/types";

/** Renders children only for signed-in users (optionally admins); redirects otherwise. */
export function Protected({ children, admin = false }: { children: React.ReactNode; admin?: boolean }) {
  const { user, loading } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (!loading && !user) router.replace(`/login?next=${encodeURIComponent(window.location.pathname)}`);
  }, [loading, user, router]);
  if (loading || !user) return <Spinner />;
  if (admin && user.role !== "ADMIN") return <ErrorBox message="Admin access required." />;
  return <>{children}</>;
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 py-10 text-sm text-slate-500">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-brand-600" />
      {label}
    </div>
  );
}

export function ErrorBox({ message }: { message: string }) {
  return <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{message}</div>;
}

export function InfoBox({ children, tone = "info" }: { children: React.ReactNode; tone?: "info" | "success" | "warn" }) {
  const styles = {
    info: "border-brand-100 bg-brand-50 text-brand-700",
    success: "border-emerald-200 bg-emerald-50 text-emerald-800",
    warn: "border-amber-200 bg-amber-50 text-amber-800",
  }[tone];
  return <div className={`rounded-lg border px-4 py-3 text-sm ${styles}`}>{children}</div>;
}

const STATUS_COLORS: Record<string, string> = {
  ACTIVE: "bg-sky-100 text-sky-800",
  POTENTIAL_MATCH: "bg-amber-100 text-amber-800",
  VERIFICATION_PENDING: "bg-amber-100 text-amber-800",
  AWAITING_FINDER_REVIEW: "bg-violet-100 text-violet-800",
  VERIFIED: "bg-emerald-100 text-emerald-800",
  CONNECTED: "bg-emerald-100 text-emerald-800",
  RECOVERED: "bg-emerald-600 text-white",
  REJECTED: "bg-rose-100 text-rose-800",
  DEACTIVATED: "bg-rose-100 text-rose-800",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_COLORS[status] ?? "bg-slate-100 text-slate-700"}`}>
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}

export function TypeBadge({ type }: { type: "LOST" | "FOUND" }) {
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold ${type === "LOST" ? "bg-rose-100 text-rose-700" : "bg-emerald-100 text-emerald-700"}`}>
      {type === "LOST" ? "Lost" : "Found"}
    </span>
  );
}

export function ConfidenceBadge({ confidence, percent }: { confidence: string; percent: number }) {
  const c = { HIGH: "bg-emerald-600", MEDIUM: "bg-amber-500", LOW: "bg-slate-400" }[confidence] ?? "bg-slate-400";
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-sm font-semibold text-white ${c}`}>
      {percent}% · {confidence.toLowerCase()} relevance
    </span>
  );
}

export function ReportThumb({ report, className = "h-40" }: { report: Report; className?: string }) {
  const img = report.images[0];
  return img ? (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={imageUrl(img.url)} alt={report.name} className={`w-full rounded-xl object-cover ${className}`} />
  ) : (
    <div className={`grid w-full place-items-center rounded-xl bg-slate-100 text-sm text-slate-400 ${className}`}>No photo</div>
  );
}

export function ReportCard({ report }: { report: Report }) {
  return (
    <Link href={`/reports/${report.id}`} className="card block transition hover:-translate-y-0.5 hover:shadow-md">
      <ReportThumb report={report} />
      <div className="mt-3 flex items-center gap-2">
        <TypeBadge type={report.report_type} />
        <StatusBadge status={report.status} />
      </div>
      <h3 className="mt-2 font-semibold text-slate-900">{report.name}</h3>
      <p className="line-clamp-2 text-sm text-slate-600">{report.description}</p>
      <p className="mt-2 text-xs text-slate-500">
        📍 {report.location} · {new Date(report.date_time).toLocaleDateString()}
      </p>
    </Link>
  );
}

export function PageHeader({ title, subtitle, action }: { title: string; subtitle?: string; action?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-600">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="rounded-2xl border border-dashed border-slate-300 p-10 text-center text-sm text-slate-500">{children}</div>;
}
