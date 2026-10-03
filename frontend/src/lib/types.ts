export type ReportType = "LOST" | "FOUND";

export interface User {
  id: number;
  name: string;
  email: string;
  role: "USER" | "ADMIN";
  created_at: string;
}

export interface Report {
  id: number;
  report_type: ReportType;
  category: string;
  name: string;
  description: string;
  color: string | null;
  brand: string | null;
  model: string | null;
  distinctive_features: string | null;
  date_time: string;
  location: string;
  approx_latitude: number | null;
  approx_longitude: number | null;
  status: string;
  created_at: string;
  reporter_name: string;
  images: { id: number; url: string }[];
  is_owner: boolean;
  // owner-only
  private_details?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  ai_status?: "PENDING" | "DONE" | "FAILED";
  ai_error?: string | null;
  attributes?: { attribute_name: string; attribute_value: string; source: "USER" | "AI"; confidence: number }[];
}

export interface Match {
  id: number;
  score: number;
  score_percent: number;
  confidence: "HIGH" | "MEDIUM" | "LOW";
  explanation: string[];
  signals: Record<string, number>;
  status: string;
  my_role: "owner" | "finder" | "admin" | null;
  my_report_id: number | null;
  case_id: number | null;
  verification_status: string | null;
  disclaimer: string;
  created_at: string;
  other_report?: Report;
  lost_report?: Report;
  found_report?: Report;
}

export interface Question {
  id: string;
  question: string;
  evidence_type: string;
  optional?: boolean;
}

export interface Notification {
  id: number;
  type: string;
  title: string;
  message: string;
  link: string | null;
  read: boolean;
  created_at: string;
}

export interface CaseInfo {
  id: number;
  status: "CONNECTED" | "RECOVERED" | "CLOSED";
  match_id: number;
  my_role: "owner" | "finder" | "admin";
  owner_name: string;
  finder_name: string;
  lost_report: Report;
  found_report: Report;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: number;
  message: string;
  created_at: string;
  sender_name: string;
  mine: boolean;
}
