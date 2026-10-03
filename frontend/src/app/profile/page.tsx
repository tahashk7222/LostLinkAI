"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDate } from "@/lib/format";
import { ErrorBox, InfoBox, PageHeader, Protected } from "@/components/ui";

function Profile() {
  const { user, refresh } = useAuth();
  const [name, setName] = useState(user?.name ?? "");
  const [pw, setPw] = useState({ current_password: "", new_password: "" });
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  async function save(body: Record<string, string>) {
    setMsg("");
    setError("");
    try {
      await api("/auth/me", { method: "PUT", json: body });
      await refresh();
      setMsg("Saved.");
      setPw({ current_password: "", new_password: "" });
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (!user) return null;
  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <PageHeader title="Profile & settings" />
      {msg && <InfoBox tone="success">{msg}</InfoBox>}
      {error && <ErrorBox message={error} />}
      <div className="card space-y-4">
        <div>
          <p className="text-sm text-slate-500">Email (private, never shown to other users)</p>
          <p className="font-medium">{user.email}</p>
        </div>
        <p className="text-sm text-slate-500">Member since {formatDate(user.created_at)}</p>
        <form onSubmit={(e) => { e.preventDefault(); save({ name }); }} className="space-y-2">
          <label className="label" htmlFor="name">Name</label>
          <div className="flex gap-2">
            <input id="name" className="input" minLength={2} value={name} onChange={(e) => setName(e.target.value)} />
            <button className="btn-primary">Save</button>
          </div>
          <p className="hint">Other users see only your first name.</p>
        </form>
      </div>
      <form className="card space-y-3" onSubmit={(e) => { e.preventDefault(); save(pw); }}>
        <h2 className="font-semibold text-slate-900">Change password</h2>
        <input type="password" required className="input" placeholder="Current password" value={pw.current_password}
          onChange={(e) => setPw({ ...pw, current_password: e.target.value })} autoComplete="current-password" />
        <input type="password" required minLength={8} className="input" placeholder="New password (8+ characters)" value={pw.new_password}
          onChange={(e) => setPw({ ...pw, new_password: e.target.value })} autoComplete="new-password" />
        <button className="btn-secondary">Update password</button>
      </form>
      <div className="card text-sm text-slate-600">
        <h2 className="mb-1 font-semibold text-slate-900">Privacy</h2>
        Your reports are used only to find matches. They are not used to train AI models. Private details and exact
        locations are never shown to other users.
      </div>
    </div>
  );
}

export default function ProfilePage() {
  return (
    <Protected>
      <Profile />
    </Protected>
  );
}
