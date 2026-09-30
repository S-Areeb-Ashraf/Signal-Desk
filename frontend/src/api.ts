import type { Lead, PipelineResponse, Profile } from "./types";
import { API_URL } from "./config";
const base = API_URL.replace(/\/$/, "");
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${base}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!response.ok) {
    const raw = await response.text();
    let message = raw || "Request failed";
    try {
      const payload = JSON.parse(raw);
      message = payload.detail || payload.message || message;
    } catch {}
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}
export const api = {
  leads: () => request<PipelineResponse>("/api/leads"),
  demo: () => request<PipelineResponse>("/api/pipeline/demo"),
  discover: (
    industry: string,
    city: string,
    country = "United States",
    limit = 20,
  ) =>
    request<PipelineResponse>("/api/pipeline/discover", {
      method: "POST",
      body: JSON.stringify({ industry, city, country, limit }),
    }),
  score: (leads: Lead[], profile: Profile) =>
    request<PipelineResponse>("/api/scoring/preview", {
      method: "POST",
      body: JSON.stringify({ leads, profile }),
    }),
  importCsv: (csv_text: string) =>
    request<PipelineResponse>("/api/pipeline/import", {
      method: "POST",
      body: JSON.stringify({ csv_text }),
    }),
  draft: (lead: Lead) =>
    request<{ subject: string; body: string }>("/api/outreach/draft", {
      method: "POST",
      body: JSON.stringify({ lead }),
    }),
};
