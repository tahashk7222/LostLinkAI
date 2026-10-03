export function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function timeAgo(iso: string): string {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

/** Value for <input type="datetime-local"> in the user's local time. */
export function toLocalInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export const STATUS_LABELS: Record<string, string> = {
  DRAFT: "Draft",
  ACTIVE: "Active",
  POTENTIAL_MATCH: "Potential match",
  VERIFICATION_PENDING: "Verification pending",
  AWAITING_FINDER_REVIEW: "Awaiting finder review",
  VERIFIED: "Verified",
  REJECTED: "Not confirmed",
  DISMISSED: "Dismissed",
  CONNECTED: "Connected",
  RECOVERED: "Recovered",
  CLOSED: "Closed",
  EXPIRED: "Expired",
  DEACTIVATED: "Deactivated",
};
