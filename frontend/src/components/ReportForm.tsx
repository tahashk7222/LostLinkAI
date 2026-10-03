"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { toLocalInput } from "@/lib/format";
import { CATEGORIES, LANDMARKS } from "@/lib/region";
import type { Report, ReportType } from "@/lib/types";
import { ErrorBox } from "./ui";

const MAX_MB = 5;
const TYPES = ["image/jpeg", "image/png", "image/webp"];

export function ReportForm({ type }: { type: ReportType }) {
  const router = useRouter();
  const lost = type === "LOST";
  const [f, setF] = useState({
    category: "",
    name: "",
    description: "",
    color: "",
    brand: "",
    model: "",
    distinctive_features: "",
    private_details: "",
    date_time: toLocalInput(new Date()),
    location: "",
  });
  const [coords, setCoords] = useState<{ lat: number; lng: number } | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [more, setMore] = useState(false);

  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
    setF({ ...f, [k]: e.target.value });

  function pickLandmark(name: string) {
    const l = LANDMARKS.find((x) => x.name === name);
    if (l) {
      setF({ ...f, location: l.name });
      setCoords({ lat: l.lat, lng: l.lng });
    }
  }

  function useMyLocation() {
    if (!navigator.geolocation) return setError("Location is not available in this browser.");
    navigator.geolocation.getCurrentPosition(
      (p) => {
        setCoords({ lat: p.coords.latitude, lng: p.coords.longitude });
        if (!f.location) setF({ ...f, location: "Near my current location" });
      },
      () => setError("Could not get your location. You can type it instead."),
    );
  }

  function onFiles(list: FileList | null) {
    if (!list) return;
    const picked = Array.from(list).slice(0, 4);
    const bad = picked.find((x) => !TYPES.includes(x.type) || x.size > MAX_MB * 1024 * 1024);
    if (bad) {
      setError(`"${bad.name}" must be a JPEG, PNG or WebP image under ${MAX_MB} MB.`);
      return;
    }
    setError("");
    setFiles(picked);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setBusy("Saving report…");
    try {
      const payload = {
        report_type: type,
        ...Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v.trim() === "" ? null : v.trim()])),
        category: f.category || f.name,
        date_time: new Date(f.date_time).toISOString(),
        latitude: coords?.lat ?? null,
        longitude: coords?.lng ?? null,
      };
      const report = await api<Report>("/reports", { method: "POST", json: payload });
      for (let i = 0; i < files.length; i++) {
        setBusy(`Uploading photo ${i + 1} of ${files.length}…`);
        const body = new FormData();
        body.append("file", files[i]);
        try {
          await api(`/reports/${report.id}/images`, { method: "POST", body });
        } catch (err) {
          setError(`Report saved, but a photo failed to upload: ${(err as Error).message}`);
        }
      }
      setBusy("Looking for matches…");
      try {
        await api(`/reports/${report.id}/match`, { method: "POST" });
      } catch {
        /* report is saved; the details page shows AI status and a retry button */
      }
      router.push(`/reports/${report.id}?created=1`);
    } catch (err) {
      setError((err as Error).message);
      setBusy("");
    }
  }

  return (
    <form onSubmit={submit} className="space-y-6">
      {error && <ErrorBox message={error} />}

      <section className="card space-y-4">
        <h2 className="font-semibold text-slate-900">What {lost ? "did you lose" : "did you find"}?</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="name">Item *</label>
            <input id="name" required minLength={2} className="input" placeholder="e.g. Black backpack" value={f.name} onChange={set("name")} />
          </div>
          <div>
            <label className="label" htmlFor="category">Type of item</label>
            <select id="category" className="input" value={f.category} onChange={set("category")}>
              <option value="">Choose (optional)</option>
              {CATEGORIES.map((c) => <option key={c}>{c}</option>)}
            </select>
          </div>
        </div>
        <div>
          <label className="label" htmlFor="description">Description *</label>
          <textarea id="description" required minLength={5} rows={3} className="input" value={f.description} onChange={set("description")}
            placeholder={lost ? "e.g. I lost my black backpack near the library at around 3 PM." : "e.g. Found a black backpack on a bench outside the library."} />
        </div>
        <div>
          <label className="label">Photos (recommended)</label>
          <input type="file" accept="image/jpeg,image/png,image/webp" multiple onChange={(e) => onFiles(e.target.files)} className="block text-sm" />
          <p className="hint">Up to 4 photos, {MAX_MB} MB each. Location metadata is removed from photos automatically.</p>
          {files.length > 0 && <p className="mt-1 text-xs text-slate-600">{files.map((x) => x.name).join(", ")}</p>}
        </div>
      </section>

      <section className="card space-y-4">
        <h2 className="font-semibold text-slate-900">Where and when? <span className="font-normal text-slate-500">(approximate is fine)</span></h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="location">{lost ? "Where you lost it" : "Where you found it"} *</label>
            <input id="location" required minLength={2} className="input" placeholder="e.g. Main library entrance" value={f.location}
              onChange={(e) => { setF({ ...f, location: e.target.value }); setCoords(null); }} />
            <div className="mt-2 flex flex-wrap gap-1.5">
              {LANDMARKS.map((l) => (
                <button type="button" key={l.name} onClick={() => pickLandmark(l.name)}
                  className={`rounded-full border px-2.5 py-0.5 text-xs ${f.location === l.name ? "border-brand-500 bg-brand-50 text-brand-700" : "border-slate-300 text-slate-600 hover:bg-slate-50"}`}>
                  {l.name}
                </button>
              ))}
              <button type="button" onClick={useMyLocation} className="rounded-full border border-slate-300 px-2.5 py-0.5 text-xs text-slate-600 hover:bg-slate-50">
                📍 Use my location
              </button>
            </div>
            {coords && <p className="hint">Location pinned. Only an approximate area is shown to others.</p>}
          </div>
          <div>
            <label className="label" htmlFor="dt">{lost ? "When (approximately)" : "When you found it"} *</label>
            <input id="dt" type="datetime-local" required className="input" value={f.date_time} onChange={set("date_time")} max={toLocalInput(new Date())} />
          </div>
        </div>
      </section>

      <section className="card space-y-4">
        <button type="button" onClick={() => setMore(!more)} className="flex w-full items-center justify-between text-left font-semibold text-slate-900">
          More details (helps matching)
          <span className="text-sm text-brand-600">{more ? "Hide" : "Add"}</span>
        </button>
        {more && (
          <div className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-3">
              <div>
                <label className="label" htmlFor="color">Colour</label>
                <input id="color" className="input" placeholder="e.g. Black" value={f.color} onChange={set("color")} />
              </div>
              <div>
                <label className="label" htmlFor="brand">Brand</label>
                <input id="brand" className="input" placeholder="e.g. JanSport" value={f.brand} onChange={set("brand")} />
              </div>
              <div>
                <label className="label" htmlFor="model">Model</label>
                <input id="model" className="input" value={f.model} onChange={set("model")} />
              </div>
            </div>
            <div>
              <label className="label" htmlFor="features">Distinctive features (public)</label>
              <input id="features" className="input" placeholder="e.g. Red keychain on the zipper" value={f.distinctive_features} onChange={set("distinctive_features")} />
            </div>
          </div>
        )}
      </section>

      <section className="card space-y-2 border-amber-200 bg-amber-50/40">
        <label className="label" htmlFor="private">🔒 Private details (only you can see this)</label>
        <textarea id="private" rows={2} className="input" value={f.private_details} onChange={set("private_details")}
          placeholder={lost ? "e.g. What was inside, a hidden scratch. Never enter full card or ID numbers." : "e.g. What's inside the item. Used to check a claimed owner's answers. Never shown to them."} />
        <p className="hint">
          {lost
            ? "Helps you answer verification questions. Never shown to other users."
            : "Not shown to anyone. When someone claims the item, LostLink AI uses these notes to help you check their answers."}
        </p>
      </section>

      <button className="btn-primary w-full py-3 text-base" disabled={!!busy}>
        {busy || (lost ? "Report lost item" : "Report found item")}
      </button>
    </form>
  );
}
