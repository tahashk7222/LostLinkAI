/**
 * Region configuration for the MVP.
 *
 * SAMPLE VALUES: replace these landmarks with real places (and their coordinates)
 * in your deployment region. They help users pick a location quickly and give the
 * matcher coordinates for distance-based scoring. Users can always type any
 * location or use their device location instead.
 */
export const REGION_NAME = "Campus (sample region)";

export const LANDMARKS: { name: string; lat: number; lng: number }[] = [
  { name: "Main Library", lat: 33.6425, lng: 72.993 },
  { name: "Library Courtyard", lat: 33.6431, lng: 72.9941 },
  { name: "Cafeteria", lat: 33.645, lng: 72.9905 },
  { name: "Sports Complex", lat: 33.6478, lng: 72.9872 },
  { name: "Main Gate", lat: 33.6392, lng: 72.9968 },
  { name: "Admin Block", lat: 33.6441, lng: 72.9952 },
  { name: "Hostel Area", lat: 33.6502, lng: 72.9915 },
];

export const CATEGORIES = [
  "Backpack", "Handbag", "Wallet", "Phone", "Laptop", "Tablet", "Headphones", "Charger", "Keys", "ID card",
  "Documents", "Watch", "Glasses", "Jewelry", "Clothing", "Umbrella", "Water bottle", "Book", "Other",
];
