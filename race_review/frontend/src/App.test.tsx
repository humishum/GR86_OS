import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { SessionManifest } from "./types";

const { api } = vi.hoisted(() => ({
  api: {
    sessions: vi.fn(),
    archiveSession: vi.fn(),
    restoreSession: vi.fn(),
    deleteSession: vi.fn(),
    backupCatalog: vi.fn(),
    cleanupArtifacts: vi.fn(),
    exportBundle: vi.fn(),
  },
}));

vi.mock("./api", () => ({ api, ApiError: class ApiError extends Error {} }));

import App from "./App";

function sessionFixture(status: SessionManifest["status"] = "ready"): SessionManifest {
  return {
    schema_version: 1,
    session_id: "sess-123abc",
    name: "Sonoma Raceway",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    status,
    duration_seconds: 120,
    chapters: [],
    streams: [],
    coordinate_origin: null,
    processing_versions: { race_review: "test" },
    processing_options: { generate_proxy: true },
    artifacts: {},
    warnings: [],
    edits: {
      track: {
        start_finish_a: null,
        start_finish_b: null,
        crossing_direction: 1,
        minimum_lap_seconds: 20,
        exclude_out_lap: true,
        exclude_in_lap: true,
      },
      calibration: {
        transform: { forward_axis: "x", lateral_axis: "y", forward_sign: 1, lateral_sign: 1 },
        confidence: 0,
        method: "unavailable",
        overridden: false,
        diagnostics: {},
      },
      corner_edits: [],
      display_units: { speed: "mph", acceleration: "g", distance: "ft", time: "s" },
      reference_lap: null,
      bookmarks: [],
    },
  };
}

describe("library archive workflow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.history.replaceState(null, "", "/");
  });

  it("moves a session to the recoverable list after archive confirmation", async () => {
    const active = sessionFixture("ready");
    const archived = { ...active, status: "archived", archived_from_status: "ready" };
    let current = [active];
    api.sessions.mockImplementation(async () => current);
    api.archiveSession.mockImplementation(async () => {
      current = [archived];
      return archived;
    });

    render(<App />);
    expect(await screen.findByRole("heading", { name: "Race library" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Archive" }));
    const dialog = screen.getByRole("dialog", { name: "Archive session" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Archive" }));
    expect(await screen.findByRole("heading", { name: "Recoverable sessions" })).toBeInTheDocument();
    expect(api.archiveSession).toHaveBeenCalledWith("sess-123abc");
    expect(screen.getByRole("button", { name: "Restore" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });
});
