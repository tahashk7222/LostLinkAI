"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import type { Notification } from "@/lib/types";
import { Empty, ErrorBox, PageHeader, Protected, Spinner } from "@/components/ui";

function Notifications() {
  const router = useRouter();
  const [items, setItems] = useState<Notification[] | null>(null);
  const [error, setError] = useState("");

  const load = () =>
    api<{ notifications: Notification[] }>("/notifications").then((r) => setItems(r.notifications)).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  async function open(n: Notification) {
    if (!n.read) await api(`/notifications/${n.id}/read`, { method: "POST" }).catch(() => {});
    if (n.link) router.push(n.link);
    else load();
  }

  async function readAll() {
    await api("/notifications/read-all", { method: "POST" });
    load();
  }

  if (error) return <ErrorBox message={error} />;
  if (!items) return <Spinner />;
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="Notifications" action={items.some((n) => !n.read) && <button className="btn-secondary" onClick={readAll}>Mark all as read</button>} />
      {items.length === 0 ? <Empty>No notifications yet.</Empty> : (
        <div className="card divide-y divide-slate-100 p-0">
          {items.map((n) => (
            <button key={n.id} onClick={() => open(n)} className="flex w-full gap-3 p-4 text-left hover:bg-slate-50">
              <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${n.read ? "bg-transparent" : "bg-brand-600"}`} />
              <span className="flex-1">
                <span className={`block text-sm ${n.read ? "text-slate-700" : "font-semibold text-slate-900"}`}>{n.title}</span>
                <span className="block text-sm text-slate-600">{n.message}</span>
                <span className="mt-1 block text-xs text-slate-400">{timeAgo(n.created_at)}</span>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function NotificationsPage() {
  return (
    <Protected>
      <Notifications />
    </Protected>
  );
}
