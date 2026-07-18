import type {
  Calibration,
  CornerSummary,
  JobStatus,
  LapSummary,
  MediaEntry,
  SessionManifest,
  TelemetryWindow,
  TrackConfig,
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(detail.detail ?? `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  sessions: () => request<SessionManifest[]>("/api/sessions"),
  session: (id: string) => request<SessionManifest>(`/api/sessions/${id}`),
  media: () => request<MediaEntry[]>("/api/media"),
  status: (id: string) => request<JobStatus>(`/api/sessions/${id}/status`),
  telemetry: (id: string) => request<TelemetryWindow>(`/api/sessions/${id}/telemetry?max_points=30000`),
  laps: (id: string) => request<LapSummary[]>(`/api/sessions/${id}/laps`),
  corners: (id: string) => request<CornerSummary[]>(`/api/sessions/${id}/corners`),
  import: (chapters: string[], name?: string) =>
    request<{ session_id: string; status: string }>("/api/sessions/import", {
      method: "POST",
      body: JSON.stringify({ chapters, name, generate_proxy: true }),
    }),
  saveTrack: (id: string, value: TrackConfig) =>
    request<SessionManifest>(`/api/sessions/${id}/track`, {
      method: "PUT",
      body: JSON.stringify(value),
    }),
  saveCalibration: (id: string, value: Calibration) =>
    request<SessionManifest>(`/api/sessions/${id}/calibration`, {
      method: "PUT",
      body: JSON.stringify(value),
    }),
  saveCorners: (id: string, edits: Array<Record<string, unknown>>) =>
    request<CornerSummary[]>(`/api/sessions/${id}/corners`, {
      method: "PUT",
      body: JSON.stringify(edits),
    }),
  comparison: (id: string, reference: number, comparison: number) =>
    request<Record<string, number[]>>(
      `/api/sessions/${id}/comparison?reference_lap=${reference}&comparison_lap=${comparison}`,
    ),
};
