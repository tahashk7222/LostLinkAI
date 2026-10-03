"use client";

import dynamic from "next/dynamic";
import { useEffect, useId, useState } from "react";
import { classify, describePoint, loadGeoConfig, type GeoConfig, type LocationValue } from "@/lib/geo";

const CampusMap = dynamic(() => import("./CampusMap").then((m) => m.CampusMap), {
  ssr: false,
  loading: () => <div className="grid h-[280px] place-items-center rounded-xl bg-slate-100 text-sm text-slate-500">Loading map…</div>,
});

interface Props {
  mode: "LOST" | "FOUND";
  value: LocationValue | null;
  onChange: (v: LocationValue | null) => void;
  error?: string;
}

const GEO_ERRORS: Record<number, string> = {
  1: "Location permission was denied. Choose a place below or pick a spot on the map instead.",
  2: "Your location is currently unavailable. Choose a place below or pick a spot on the map.",
  3: "Getting your location took too long. Try again, or choose a place below.",
};

export function LocationPicker({ mode, value, onChange, error }: Props) {
  const ids = { heading: useId(), help: useId(), label: useId(), status: useId() };
  const [cfg, setCfg] = useState<GeoConfig | null>(null);
  const [loadError, setLoadError] = useState("");
  const [geoError, setGeoError] = useState("");
  const [locating, setLocating] = useState(false);
  const [accuracy, setAccuracy] = useState<number | null>(null);
  const [showMap, setShowMap] = useState(false);

  useEffect(() => {
    loadGeoConfig().then(setCfg).catch((e) => setLoadError(e.message));
  }, []);

  function choosePoint(lat: number, lng: number, type: "gps" | "map") {
    if (!cfg) return;
    const zone = classify(cfg, lat, lng);
    if (!zone) {
      setGeoError(cfg.out_of_area_message + (value ? " That spot wasn't used; your previous choice is kept." : ""));
      return false;
    }
    setGeoError("");
    onChange({ type, placeKey: null, lat, lng, zone, label: describePoint(cfg, lat, lng, zone) });
    return true;
  }

  function choosePlace(key: string) {
    const p = cfg?.places.find((x) => x.key === key);
    if (!cfg || !p) return;
    const zone = classify(cfg, p.lat, p.lng) ?? "campus";
    setGeoError("");
    setAccuracy(null);
    onChange({ type: "predefined", placeKey: p.key, lat: p.lat, lng: p.lng, zone, label: p.name });
  }

  function useMyLocation() {
    setGeoError("");
    // Check the value, not just the key: some webviews expose navigator.geolocation as undefined.
    if (typeof navigator === "undefined" || !navigator.geolocation?.getCurrentPosition) {
      setGeoError("Location isn't supported in this browser. Choose a place below or pick a spot on the map.");
      return;
    }
    if (!window.isSecureContext) {
      setGeoError("Location only works over a secure (https) connection. Choose a place below instead.");
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setLocating(false);
        const ok = choosePoint(pos.coords.latitude, pos.coords.longitude, "gps");
        setAccuracy(ok ? Math.round(pos.coords.accuracy) : null);
      },
      (err) => {
        setLocating(false);
        setGeoError(GEO_ERRORS[err.code] ?? GEO_ERRORS[2]);
      },
      // maximumAge 0: an explicit "use my location" must not return a stale cached position
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 },
    );
  }

  const where = mode === "LOST" ? "Where did you lose it?" : "Where did you find it?";
  const zoneName = value && cfg ? cfg.zones[value.zone] : "";

  return (
    <div role="group" aria-labelledby={ids.heading} aria-describedby={ids.help} className="space-y-3">
      <div>
        <p id={ids.heading} className="label">{where} *</p>
        <p id={ids.help} className="text-xs text-slate-500">LostLink currently covers UET Lahore and its immediate surroundings.</p>
      </div>

      {loadError && <p role="alert" className="text-sm text-rose-600">Couldn&apos;t load UET locations: {loadError}</p>}
      {!cfg && !loadError && <p className="text-sm text-slate-500">Loading UET locations…</p>}

      {cfg && (
        <>
          <div className="flex flex-wrap gap-1.5" aria-label="UET Lahore places">
            {cfg.places.map((p) => {
              const active = value?.type === "predefined" && value.placeKey === p.key;
              return (
                <button key={p.key} type="button" aria-pressed={active} onClick={() => choosePlace(p.key)}
                  className={`rounded-full border px-3 py-1 text-xs transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 ${
                    active ? "border-brand-500 bg-brand-600 text-white" : "border-slate-300 bg-white text-slate-700 hover:border-brand-500 hover:bg-brand-50"}`}>
                  {p.name}
                </button>
              );
            })}
          </div>

          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={useMyLocation} disabled={locating} className="btn-secondary">
              <PinIcon /> {locating ? "Finding you…" : "Use my location"}
            </button>
            <button type="button" onClick={() => setShowMap(!showMap)} aria-expanded={showMap} className="btn-secondary">
              <MapIcon /> {showMap ? "Hide map" : "Pick on map"}
            </button>
          </div>

          <div id={ids.status} aria-live="polite">
            {geoError && (
              <p role="alert" className="flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
                <span aria-hidden>⚠</span> {geoError}
              </p>
            )}
            {value && (
              <div className="flex flex-wrap items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm">
                <span aria-hidden>📍</span>
                <span className="font-medium text-slate-900">{value.label}</span>
                <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${value.zone === "campus" ? "bg-brand-600 text-white" : "bg-slate-600 text-white"}`}>
                  {zoneName}
                </span>
                {value.type === "gps" && accuracy !== null && (
                  <span className="text-xs text-slate-500">from your device{accuracy > 150 ? ` (approx. ±${accuracy} m: adjust on the map if needed)` : ""}</span>
                )}
                {value.type === "map" && <span className="text-xs text-slate-500">pinned on map</span>}
                <button type="button" onClick={() => onChange(null)} className="ml-auto text-xs text-slate-500 underline hover:text-slate-800">
                  Clear
                </button>
              </div>
            )}
          </div>

          {showMap && (
            <CampusMap config={cfg} point={value} onPick={(lat, lng) => choosePoint(lat, lng, "map")}
              label="Map of UET Lahore: click to choose where the item was" />
          )}

          {value && (
            <div>
              <label htmlFor={ids.label} className="label">Describe the spot <span className="font-normal text-slate-500">(optional)</span></label>
              <input id={ids.label} className="input" maxLength={200} value={value.label}
                placeholder="e.g. Bench outside the Lecture Theatre"
                onChange={(e) => onChange({ ...value, label: e.target.value })} />
              <p className="hint">Shown to others instead of your exact position.</p>
            </div>
          )}
          {error && !value && <p role="alert" className="text-sm text-rose-600">{error}</p>}
          <p className="text-[11px] text-slate-400">{cfg.attribution}</p>
        </>
      )}
    </div>
  );
}

function PinIcon() {
  return (
    <svg aria-hidden viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 21s-7-6.2-7-11a7 7 0 1 1 14 0c0 4.8-7 11-7 11z" /><circle cx="12" cy="10" r="2.5" />
    </svg>
  );
}

function MapIcon() {
  return (
    <svg aria-hidden viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2z" /><path d="M9 4v14M15 6v14" />
    </svg>
  );
}
