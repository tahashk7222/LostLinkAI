"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, getToken } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { CaseInfo, ChatMessage } from "@/lib/types";
import { ErrorBox, InfoBox, Protected, ReportThumb, Spinner, StatusBadge } from "@/components/ui";

const STEPS = ["Potential match", "Verification passed", "Connected", "Recovered"];

function CaseView() {
  const { id } = useParams<{ id: string }>();
  const [c, setC] = useState<CaseInfo | null>(null);
  const [msgs, setMsgs] = useState<ChatMessage[]>([]);
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [confirm, setConfirm] = useState<"RECOVERED" | "CLOSED" | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const pollStopped = useRef(false);  // set when the session ends (401): polling must not continue

  const load = useCallback(async () => {
    try {
      const [cs, m] = await Promise.all([
        api<CaseInfo>(`/cases/${id}`),
        api<{ messages: ChatMessage[] }>(`/cases/${id}/messages`),
      ]);
      setC(cs);
      setMsgs(m.messages);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) pollStopped.current = true;
      setError((e as Error).message);
    }
  }, [id]);

  useEffect(() => {
    if (!getToken()) return;  // no session: nothing to poll
    pollStopped.current = false;
    load();
    const t = setInterval(() => {
      if (pollStopped.current || !getToken()) clearInterval(t);  // stop on 401, and never poll without a token
      else load();
    }, 8000);
    return () => clearInterval(t);
  }, [load]);

  useEffect(() => {
    // Block body on purpose: newer browsers return a Promise from scrollIntoView, and an effect
    // must not return anything except a cleanup function.
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs.length]);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    try {
      const m = await api<ChatMessage>(`/cases/${id}/messages`, { method: "POST", json: { message: text } });
      setMsgs([...msgs, m]);
      setText("");
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function setStatus(status: "RECOVERED" | "CLOSED") {
    try {
      await api(`/cases/${id}/status`, { method: "PUT", json: { status } });
      setConfirm(null);
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  if (error && !c) return <ErrorBox message={error} />;
  if (!c) return <Spinner />;
  const step = c.status === "RECOVERED" ? 4 : 3;
  const other = c.my_role === "owner" ? c.finder_name : c.owner_name;

  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <aside className="space-y-4">
        <div className="card space-y-3">
          <div className="flex items-center justify-between">
            <h1 className="font-semibold text-slate-900">Case #{c.id}</h1>
            <StatusBadge status={c.status} />
          </div>
          <ReportThumb report={c.found_report} className="h-40" />
          <p className="font-medium">{c.lost_report.name}</p>
          <p className="text-xs text-slate-500">
            {c.my_role === "owner" ? `Found by ${c.finder_name}` : `Owner: ${c.owner_name}`} · opened {formatDate(c.created_at)}
          </p>
          <ol className="space-y-1.5 pt-2">
            {STEPS.map((s, i) => (
              <li key={s} className="flex items-center gap-2 text-sm">
                <span className={`grid h-5 w-5 place-items-center rounded-full text-xs ${i < step ? "bg-emerald-600 text-white" : "bg-slate-200 text-slate-500"}`}>
                  {i < step ? "✓" : i + 1}
                </span>
                <span className={i < step ? "text-slate-800" : "text-slate-400"}>{s}</span>
              </li>
            ))}
          </ol>
          <Link href={`/matches/${c.match_id}`} className="text-sm text-brand-600 hover:underline">View match details</Link>
        </div>
        {c.status === "CONNECTED" && (
          <div className="card space-y-2">
            {!confirm ? (
              <>
                <button className="btn-primary w-full" onClick={() => setConfirm("RECOVERED")}>Item returned: mark recovered</button>
                <button className="btn-secondary w-full" onClick={() => setConfirm("CLOSED")}>Close without recovery</button>
              </>
            ) : (
              <>
                <p className="text-sm">{confirm === "RECOVERED" ? "Confirm the item has been handed over?" : "Close this case? Both reports will reopen."}</p>
                <div className="flex gap-2">
                  <button className="btn-primary" onClick={() => setStatus(confirm)}>Confirm</button>
                  <button className="btn-secondary" onClick={() => setConfirm(null)}>Cancel</button>
                </div>
              </>
            )}
          </div>
        )}
        {c.status === "RECOVERED" && <InfoBox tone="success">🎉 Item recovered. Thank you for using LostLink AI!</InfoBox>}
      </aside>

      <section className="card flex h-[70vh] flex-col p-0 lg:col-span-2">
        <div className="border-b border-slate-100 p-4">
          <h2 className="font-semibold text-slate-900">Messages with {other}</h2>
          <p className="text-xs text-slate-500">
            Arrange a safe handover. Meet in a public place such as a library desk or security office. Share personal
            contact details only if you choose to.
          </p>
        </div>
        {error && <div className="p-3"><ErrorBox message={error} /></div>}
        <div className="flex-1 space-y-3 overflow-y-auto p-4">
          {msgs.length === 0 && <p className="text-center text-sm text-slate-400">No messages yet. Say hello 👋</p>}
          {msgs.map((m) => (
            <div key={m.id} className={`flex ${m.mine ? "justify-end" : "justify-start"}`}>
              <div className={`max-w-[75%] rounded-2xl px-4 py-2 text-sm ${m.mine ? "bg-brand-600 text-white" : "bg-slate-100 text-slate-800"}`}>
                {!m.mine && <p className="text-xs font-semibold opacity-70">{m.sender_name}</p>}
                <p className="whitespace-pre-wrap">{m.message}</p>
                <p className="mt-1 text-[10px] opacity-60">{formatDate(m.created_at)}</p>
              </div>
            </div>
          ))}
          <div ref={bottom} />
        </div>
        {c.status !== "CLOSED" && (
          <form onSubmit={send} className="flex gap-2 border-t border-slate-100 p-3">
            <input className="input" maxLength={2000} placeholder="Write a message…" value={text} onChange={(e) => setText(e.target.value)} />
            <button className="btn-primary" disabled={!text.trim()}>Send</button>
          </form>
        )}
      </section>
    </div>
  );
}

export default function CasePage() {
  return (
    <Protected>
      <CaseView />
    </Protected>
  );
}
