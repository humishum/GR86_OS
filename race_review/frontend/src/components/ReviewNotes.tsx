import { useEffect, useRef, useState } from "react";
import type { Bookmark } from "../types";
import { formatTime } from "../telemetry";
import { ActionableError, errorMessage } from "./ActionableError";

function emptyBookmark(seconds: number): Bookmark {
  return {
    id: crypto.randomUUID(),
    seconds,
    label: "",
    note: "",
    tags: [],
    clip: null,
  };
}

function parseTags(value: string) {
  return [...new Set(value.split(",").map((item) => item.trim()).filter(Boolean))];
}

export function ReviewNotes({
  bookmarks,
  time,
  onSeek,
  onSave,
}: {
  bookmarks: Bookmark[];
  time: number;
  onSeek: (seconds: number) => void;
  onSave: (value: Bookmark[]) => Promise<void> | void;
}) {
  const [drafts, setDrafts] = useState(bookmarks);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const draftsRef = useRef(drafts);

  useEffect(() => {
    const currentIds = draftsRef.current.map((item) => item.id).join();
    const nextIds = bookmarks.map((item) => item.id).join();
    if (currentIds !== nextIds) {
      draftsRef.current = bookmarks;
      setDrafts(bookmarks);
    }
  }, [bookmarks]);
  useEffect(() => { draftsRef.current = drafts; }, [drafts]);

  const persist = async (next: Bookmark[]) => {
    draftsRef.current = next;
    setDrafts(next);
    setBusy(true);
    setError("");
    try {
      await onSave(next);
    } catch (reason) {
      setError(errorMessage(reason, "Could not save bookmarks."));
    } finally {
      setBusy(false);
    }
  };
  const patch = (id: string, values: Partial<Bookmark>) => {
    const next = draftsRef.current.map((bookmark) => bookmark.id === id ? { ...bookmark, ...values } : bookmark);
    draftsRef.current = next;
    setDrafts(next);
  };

  return (
    <section className="review-notes">
      <div className="section-heading">
        <h3>Bookmarks</h3>
        <button type="button" disabled={busy} onClick={() => void persist([...drafts, emptyBookmark(time)])}>
          Add at {formatTime(time)}
        </button>
      </div>
      {error && <ActionableError
        compact
        title="Could not save bookmarks"
        message={error}
        primaryAction={{ label: "Retry save", onClick: () => void persist(drafts), disabled: busy }}
      />}
      {!drafts.length && <p className="muted">Mark a frame, add a note or tag, and optionally store an in/out clip range.</p>}
      <ul>
        {drafts.map((bookmark) => (
          <li key={bookmark.id} className="bookmark-card">
            <div className="bookmark-card__row">
              <button type="button" onClick={() => onSeek(bookmark.seconds)}>{formatTime(bookmark.seconds)}</button>
              <input
                aria-label="Bookmark label"
                value={bookmark.label}
                placeholder="Label"
                onChange={(event) => patch(bookmark.id, { label: event.target.value })}
                onBlur={() => void persist(draftsRef.current)}
              />
              <button type="button" aria-label={`Delete ${bookmark.label || "bookmark"}`} onClick={() => void persist(drafts.filter((item) => item.id !== bookmark.id))}>×</button>
            </div>
            <textarea
              aria-label="Bookmark note"
              value={bookmark.note}
              placeholder="Note"
              rows={2}
              onChange={(event) => patch(bookmark.id, { note: event.target.value })}
              onBlur={() => void persist(draftsRef.current)}
            />
            <input
              aria-label="Bookmark tags"
              value={bookmark.tags.join(", ")}
              placeholder="tags, comma separated"
              onChange={(event) => patch(bookmark.id, { tags: parseTags(event.target.value) })}
              onBlur={() => void persist(draftsRef.current)}
            />
            <div className="bookmark-card__clip">
              <button type="button" onClick={() => void persist(drafts.map((item) => item.id === bookmark.id
                ? { ...item, clip: { start_seconds: time, end_seconds: Math.max(time, item.clip?.end_seconds ?? time) } }
                : item))}
              >Mark in</button>
              <button type="button" onClick={() => void persist(drafts.map((item) => item.id === bookmark.id
                ? { ...item, clip: { start_seconds: Math.min(time, item.clip?.start_seconds ?? time), end_seconds: time } }
                : item))}
              >Mark out</button>
              <span>
                {bookmark.clip
                  ? `${formatTime(bookmark.clip.start_seconds)}–${formatTime(bookmark.clip.end_seconds)}`
                  : "No clip range"}
              </span>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
