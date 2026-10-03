/**
 * Client-side mirror of the backend geofence (backend/app/geo/geofence.py).
 * Used only for instant feedback; the backend re-validates every submission.
 * The boundary itself is loaded from GET /geo/config (single source of truth).
 */
import { api } from "./api";

export type Zone = "campus" | "nearby";

export interface GeoPlace {
  key: string;
  name: string;
  lat: number;
  lng: number;
  area: string;
}

export interface GeoConfig {
  id: string;
  name: string;
  zones: Record<Zone, string>;
  nearby_buffer_m: number;
  edge_tolerance_m: number;
  campus_polygon: [number, number][];
  places: GeoPlace[];
  attribution: string;
  out_of_area_message: string;
}

export interface LocationValue {
  type: "predefined" | "gps" | "map";
  placeKey: string | null;
  lat: number;
  lng: number;
  zone: Zone;
  label: string;
}

let cached: Promise<GeoConfig> | null = null;

export function loadGeoConfig(): Promise<GeoConfig> {
  if (!cached) cached = api<GeoConfig>("/geo/config").catch((e) => {
    cached = null; // allow retry
    throw e;
  });
  return cached;
}

const EARTH_M = 6371000;
const rad = (d: number) => (d * Math.PI) / 180;

function toXY(lat: number, lng: number, lat0: number): [number, number] {
  return [rad(lng) * EARTH_M * Math.cos(rad(lat0)), rad(lat) * EARTH_M];
}

export function pointInPolygon(lat: number, lng: number, poly: [number, number][]): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [y1, x1] = poly[i];
    const [y2, x2] = poly[j];
    if (y1 > lat !== y2 > lat) {
      const xCross = x1 + ((lat - y1) * (x2 - x1)) / (y2 - y1);
      if (lng < xCross) inside = !inside;
    }
  }
  return inside;
}

export function distanceToPolygonM(lat: number, lng: number, poly: [number, number][]): number {
  const lat0 = poly[0][0];
  const [px, py] = toXY(lat, lng, lat0);
  let best = Infinity;
  for (let i = 0; i < poly.length; i++) {
    const [ax, ay] = toXY(poly[i][0], poly[i][1], lat0);
    const [bx, by] = toXY(poly[(i + 1) % poly.length][0], poly[(i + 1) % poly.length][1], lat0);
    const dx = bx - ax;
    const dy = by - ay;
    const seg = dx * dx + dy * dy;
    const t = seg === 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / seg));
    best = Math.min(best, Math.hypot(px - (ax + t * dx), py - (ay + t * dy)));
  }
  return best;
}

export function distanceM(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const a = Math.sin(rad(lat2 - lat1) / 2) ** 2 + Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(rad(lng2 - lng1) / 2) ** 2;
  return 2 * EARTH_M * Math.asin(Math.sqrt(a));
}

/** 'campus', 'nearby' or null (outside the permitted area). */
export function classify(cfg: GeoConfig, lat: number, lng: number): Zone | null {
  if (pointInPolygon(lat, lng, cfg.campus_polygon)) return "campus";
  const edge = distanceToPolygonM(lat, lng, cfg.campus_polygon);
  if (edge <= cfg.edge_tolerance_m) return "campus";
  if (edge <= cfg.nearby_buffer_m) return "nearby";
  return null;
}

export function describePoint(cfg: GeoConfig, lat: number, lng: number, zone: Zone): string {
  let best: { p: GeoPlace; d: number } | null = null;
  for (const p of cfg.places) {
    const d = distanceM(lat, lng, p.lat, p.lng);
    if (!best || d < best.d) best = { p, d };
  }
  return best && best.d <= 250 ? `Near ${best.p.name}` : cfg.zones[zone];
}

/** Approximate outline of the nearby zone for display (convex hull of buffered vertices). */
export function nearbyOutline(cfg: GeoConfig, steps = 16): [number, number][] {
  const pts: [number, number][] = [];
  const r = cfg.nearby_buffer_m;
  for (const [lat, lng] of cfg.campus_polygon) {
    for (let k = 0; k < steps; k++) {
      const a = (2 * Math.PI * k) / steps;
      const dLat = ((r * Math.sin(a)) / EARTH_M) * (180 / Math.PI);
      const dLng = ((r * Math.cos(a)) / (EARTH_M * Math.cos(rad(lat)))) * (180 / Math.PI);
      pts.push([lat + dLat, lng + dLng]);
    }
  }
  // Monotone chain convex hull on (lng, lat)
  const s = pts.sort((p, q) => p[1] - q[1] || p[0] - q[0]);
  const cross = (o: number[], a: number[], b: number[]) => (a[1] - o[1]) * (b[0] - o[0]) - (a[0] - o[0]) * (b[1] - o[1]);
  const lower: [number, number][] = [];
  for (const p of s) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop();
    lower.push(p);
  }
  const upper: [number, number][] = [];
  for (let i = s.length - 1; i >= 0; i--) {
    const p = s[i];
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop();
    upper.push(p);
  }
  return lower.slice(0, -1).concat(upper.slice(0, -1));
}
