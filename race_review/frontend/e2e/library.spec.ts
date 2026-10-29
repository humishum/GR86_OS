import { expect, test, type Page } from "@playwright/test";

const session = {
  schema_version: 1,
  session_id: "sess-123abc",
  name: "Sonoma Raceway",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  status: "ready",
  duration_seconds: 120,
  chapters: [],
  streams: [],
  processing_versions: { race_review: "test" },
  processing_options: { generate_proxy: true },
  artifacts: {},
  warnings: [],
  edits: {
    track: { start_finish_a: null, start_finish_b: null, crossing_direction: 1, minimum_lap_seconds: 20, exclude_out_lap: true, exclude_in_lap: true },
    calibration: { transform: { forward_axis: "x", lateral_axis: "y", forward_sign: 1, lateral_sign: 1 }, confidence: 0, method: "unavailable", overridden: false, diagnostics: {} },
    corner_edits: [],
    display_units: { speed: "mph", acceleration: "g", distance: "ft", time: "s" },
    reference_lap: null,
    bookmarks: [],
  },
};

async function mockLibrary(page: Page) {
  let items = [{ ...session, status: "ready" as string, archived_from_status: null as string | null }];
  await page.route("**/api/**", async (route) => {
    const url = route.request().url();
    const method = route.request().method();
    if (url.endsWith("/api/sessions") && method === "GET") {
      return route.fulfill({ json: items });
    }
    if (url.includes("/archive") && method === "POST") {
      items = items.map((item) => ({ ...item, status: "archived", archived_from_status: "ready" }));
      return route.fulfill({ json: items[0] });
    }
    if (url.includes("/restore") && method === "POST") {
      items = items.map((item) => ({ ...item, status: "ready", archived_from_status: null }));
      return route.fulfill({ json: items[0] });
    }
    if (url.includes("/api/sessions/sess-123abc") && method === "DELETE") {
      items = [];
      return route.fulfill({ status: 204, body: "" });
    }
    if (url.includes("/api/catalog/backup")) {
      return route.fulfill({
        json: { path: "/tmp/catalog-backup.sqlite3", created_at: "2026-01-01T00:00:00Z", size_bytes: 12 },
      });
    }
    if (url.includes("/api/catalog/cleanup")) {
      return route.fulfill({
        json: { dry_run: false, removed_paths: ["/tmp/export"], skipped_paths: [], recovered_bytes: 4 },
      });
    }
    return route.fulfill({ json: [] });
  });
}

test("library archive requires confirmation and delete requires the session id", async ({ page }) => {
  await mockLibrary(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Race library" })).toBeVisible();
  await page.getByRole("button", { name: "Archive" }).click();
  const archiveDialog = page.getByRole("dialog", { name: "Archive session" });
  await expect(archiveDialog).toBeVisible();
  await archiveDialog.getByRole("button", { name: "Archive", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Recoverable sessions" })).toBeVisible();
  await expect(page.getByText("archived", { exact: false }).first()).toBeVisible();

  await page.getByRole("button", { name: "Delete" }).click();
  const deleteDialog = page.getByRole("dialog", { name: "Delete session" });
  await expect(deleteDialog).toBeVisible();
  await expect(deleteDialog.getByRole("button", { name: "Delete permanently" })).toBeDisabled();
  await deleteDialog.getByLabel("Type the session id to permanently delete it").fill("sess-123abc");
  await deleteDialog.getByRole("button", { name: "Delete permanently" }).click();
  await expect(page.getByRole("heading", { name: "Choose GoPro chapters" })).toBeVisible();
});
