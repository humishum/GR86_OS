import type {
  Calibration,
  CornerSummary,
  DisplayUnits,
  JobStatus,
  LapSummary,
  MediaEntry,
  SessionManifest,
  TelemetryWindow,
  TrackConfig,
} from "./types";

export class ApiError extends Error {
  readonly status: number | null;
  readonly path: string;
  readonly retryable: boolean;

  constructor(
    message: string,
    options: { status?: number | null; path: string; retryable?: boolean; cause?: unknown },
  ) {
    super(message, { cause: options.cause });
    this.name = "ApiError";
    this.status = options.status ?? null;
    this.path = options.path;
    this.retryable = options.retryable ?? (this.status == null || this.status >= 500);
  }
}

function errorDetail(value: unknown): string | null {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (Array.isArray(value)) {
    const details = value.map(errorDetail).filter((item): item is string => item != null);
    return details.length ? details.join("; ") : null;
  }
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    const message = errorDetail(record.msg ?? record.message);
    const location = Array.isArray(record.loc) ? record.loc.join(".") : null;
    if (message) return location ? `${location}: ${message}` : message;
  }
  return null;
}

function responseMessage(status: number, detail: string | null): string {
  if (detail) return detail;
  if (status === 404) return "The requested race review data could not be found.";
  if (status === 409) return "This action conflicts with the session's current state. Refresh and try again.";
  if (status === 422) return "Some submitted values are invalid. Review them and try again.";
  if (status === 401 || status === 403) return "The server refused this action. Check access and media-root settings.";
  if (status >= 500) return "The race review server could not complete the request. Try again.";
  return `The request could not be completed (${status}).`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch (cause) {
    throw new ApiError(
      "Could not reach the race review server. Check that it is running, then try again.",
      { path, cause },
    );
  }
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null);
    const detail = payload && typeof payload === "object" && "detail" in payload
      ? errorDetail((payload as { detail: unknown }).detail)
      : errorDetail(payload);
    throw new ApiError(responseMessage(response.status, detail || response.statusText), {
      status: response.status,
      path,
      retryable: response.status === 408 || response.status === 429 || response.status >= 500,
    });
  }
  try {
    return await response.json() as T;
  } catch (cause) {
    throw new ApiError("The server returned an unreadable response. Refresh and try again.", {
      status: response.status,
      path,
      cause,
    });
  }
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
  retryImport: (id: string) =>
    request<{ session_id: string; status: string }>(`/api/sessions/${id}/retry`, {
      method: "POST",
    }),
  cancelImport: (id: string) =>
    request<{ session_id: string; status: string }>(`/api/sessions/${id}/cancel`, {
      method: "POST",
    }),
  rebuildProxy: (id: string) =>
    request<{ session_id: string; status: string }>(`/api/sessions/${id}/media/proxy/rebuild`, {
      method: "POST",
    }),
  relocateSource: (id: string, chapterIndex: number, path: string) =>
    request<SessionManifest>(`/api/sessions/${id}/relocate-source`, {
      method: "POST",
      body: JSON.stringify({ chapter_index: chapterIndex, path }),
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
  saveDisplayUnits: (id: string, value: DisplayUnits) =>
    request<SessionManifest>(`/api/sessions/${id}/display-units`, {
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
