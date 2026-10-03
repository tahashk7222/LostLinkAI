"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { api, uploadFile } from "@/lib/api";
import { toLocalInput } from "@/lib/format";
import type { LocationValue } from "@/lib/geo";
import { CATEGORIES } from "@/lib/region";
import type { Report, ReportType } from "@/lib/types";
import { LocationPicker } from "./LocationPicker";
import { PhotoDropzone, type PhotoItem } from "./PhotoDropzone";
import { ErrorBox } from "./ui";

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
  });
  const [location, setLocation] = useState<LocationValue | null>(null);
  const [locationError, setLocationError] = useState("");
  const [photos, setPhotos] = useState<PhotoItem[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [more, setMore] = useState(false);
  const locationRef = useRef<HTMLDivElement>(null);

  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
    setF({ ...f, [k]: e.target.value });

  const patchPhoto = (id: string, patch: Partial<PhotoItem>) =>
    setPhotos((list) => list.map((p) => (p.id === id ? { ...p, ...patch } : p)));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (!location) {
      setLocationError("Please choose a UET Lahore location, use your location, or pick a spot on the map.");
      locationRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    setLocationError("");
    setBusy("Saving report…");
    try {
      const fields = Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v.trim() === "" ? null : v.trim()]));
      const payload = {
        report_type: type,
        ...fields,
        category: f.category || f.name,
        date_time: new Date(f.date_time).toISOString(),
        location: location.label.trim() || null,
        location_type: location.type,
        place_key: location.placeKey,
        // Coordinates are sent for GPS/map picks; for predefined places the server uses its own.
        latitude: location.type === "predefined" ? null : location.lat,
        longitude: location.type === "predefined" ? null : location.lng,
      };
      const report = await api<Report>("/reports", { method: "POST", json: payload });

      let failed = 0;
      for (let i = 0; i < photos.length; i++) {
        const p = photos[i];
        setBusy(`Uploading photo ${i + 1} of ${photos.length}…`);
        patchPhoto(p.id, { status: "uploading", progress: 0 });
        try {
          await uploadFile(`/reports/${report.id}/images`, p.file, (progress) => patchPhoto(p.id, { progress }));
          patchPhoto(p.id, { status: "done", progress: 1 });
        } catch (err) {
          failed++;
          patchPhoto(p.id, { status: "error", error: (err as Error).message });
        }
      }

      setBusy("Looking for matches…");
      try {
        await api(`/reports/${report.id}/match`, { method: "POST" });
      } catch {
        /* report is saved; the details page shows AI status and a retry button */
      }
      router.push(`/reports/${report.id}?created=1${failed ? `&photo_errors=${failed}` : ""}`);
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
            placeholder={lost ? "e.g. I lost my black backpack near the Lecture Theatre at around 3 PM." : "e.g. Found a black backpack on a bench near Allah Wala Chowk."} />
        </div>
        <PhotoDropzone photos={photos} onChange={setPhotos} disabled={!!busy} />
      </section>

      <section className="card space-y-5">
        <h2 className="font-semibold text-slate-900">Where and when? <span className="font-normal text-slate-500">(approximate is fine)</span></h2>
        <div ref={locationRef}>
          <LocationPicker mode={type} value={location} onChange={(v) => { setLocation(v); if (v) setLocationError(""); }} error={locationError} />
        </div>
        <div className="sm:max-w-xs">
          <label className="label" htmlFor="dt">{lost ? "When (approximately)" : "When you found it"} *</label>
          <input id="dt" type="datetime-local" required className="input" value={f.date_time} onChange={set("date_time")} max={toLocalInput(new Date())} />
        </div>
      </section>

      <section className="card space-y-4">
        <button type="button" onClick={() => setMore(!more)} aria-expanded={more} className="flex w-full items-center justify-between text-left font-semibold text-slate-900">
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
