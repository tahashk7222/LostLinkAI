"use client";

import "leaflet/dist/leaflet.css";
import { useEffect, useRef } from "react";
import type { Map as LeafletMap, CircleMarker, LeafletMouseEvent } from "leaflet";
import { nearbyOutline, type GeoConfig } from "@/lib/geo";

interface Props {
  config: GeoConfig;
  point?: { lat: number; lng: number } | null;
  onPick?: (lat: number, lng: number) => void;
  height?: number;
  label?: string;
}

/**
 * Lightweight Leaflet map of the permitted UET Lahore area.
 * Leaflet is imported dynamically so it never runs during server rendering.
 */
export function CampusMap({ config, point, onPick, height = 280, label = "Map of UET Lahore" }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<LeafletMap | null>(null);
  const marker = useRef<CircleMarker | null>(null);
  const pickRef = useRef(onPick);
  pickRef.current = onPick;
  const pointRef = useRef(point);
  pointRef.current = point;

  useEffect(() => {
    let disposed = false;
    import("leaflet").then((L) => {
      if (disposed || !el.current || map.current) return;
      const m = L.map(el.current, { scrollWheelZoom: false, attributionControl: true });
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      }).addTo(m);
      const outline = L.polygon(nearbyOutline(config), {
        color: "#64748b", weight: 1.5, dashArray: "6 6", fillColor: "#94a3b8", fillOpacity: 0.08, interactive: false,
      }).addTo(m);
      L.polygon(config.campus_polygon, {
        color: "#1f63d8", weight: 2, fillColor: "#2f7bf5", fillOpacity: 0.12, interactive: false,
      }).addTo(m);
      m.fitBounds(outline.getBounds(), { padding: [8, 8] });
      m.on("click", (e: LeafletMouseEvent) => pickRef.current?.(e.latlng.lat, e.latlng.lng));
      map.current = m;
      const p = pointRef.current; // latest value: Leaflet loads asynchronously
      if (p) marker.current = L.circleMarker([p.lat, p.lng], markerStyle).addTo(m);
    });
    return () => {
      disposed = true;
      map.current?.remove();
      map.current = null;
      marker.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config]);

  useEffect(() => {
    const m = map.current;
    if (!m) return;
    import("leaflet").then((L) => {
      if (!point) {
        marker.current?.remove();
        marker.current = null;
        return;
      }
      if (marker.current) marker.current.setLatLng([point.lat, point.lng]);
      else marker.current = L.circleMarker([point.lat, point.lng], markerStyle).addTo(m);
      if (!m.getBounds().contains([point.lat, point.lng])) m.panTo([point.lat, point.lng]);
    });
  }, [point]);

  return (
    <div>
      <div ref={el} role="application" aria-label={label} style={{ height }} className="z-0 w-full overflow-hidden rounded-xl border border-slate-200" />
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
        <span className="flex items-center gap-1.5"><span className="h-3 w-3 rounded-sm border-2 border-brand-600 bg-brand-500/20" /> UET Lahore Campus</span>
        <span className="flex items-center gap-1.5"><span className="h-3 w-3 rounded-sm border border-dashed border-slate-500 bg-slate-400/10" /> Nearby area (approximate outline)</span>
        {onPick && <span>Tap or click the map to drop a pin.</span>}
      </div>
    </div>
  );
}

const markerStyle = { radius: 9, color: "#ffffff", weight: 3, fillColor: "#e11d48", fillOpacity: 1 };
