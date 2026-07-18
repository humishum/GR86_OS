import { useEffect, useState } from "react";
import { api } from "../api";
import type { MediaEntry } from "../types";

export function ImportPanel({ onCreated }: { onCreated: (id: string) => void }) {
  const [media, setMedia] = useState<MediaEntry[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.media().then(setMedia).catch((reason) => setError(reason.message)); }, []);
  const toggle = (path: string) => setSelected((current) => current.includes(path) ? current.filter((item) => item !== path) : [...current, path]);
  const move = (index: number, direction: number) => setSelected((current) => {
    const target = index + direction;
    if (target < 0 || target >= current.length) return current;
    const copy = [...current];
    [copy[index], copy[target]] = [copy[target], copy[index]];
    return copy;
  });
  const submit = async () => {
    setBusy(true); setError("");
    try { const result = await api.import(selected, name || undefined); onCreated(result.session_id); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Import failed"); }
    finally { setBusy(false); }
  };
  return <main className="import-screen">
    <div className="wordmark"><span>GR86</span> / RACE REVIEW</div>
    <section className="import-card">
      <p className="eyebrow">NEW SESSION</p><h1>Choose GoPro chapters</h1>
      <p className="muted">Select chapters in recording order. Sources stay exactly where they are.</p>
      <label className="field">Session name<input value={name} onChange={(event) => setName(event.target.value)} placeholder="Track day" /></label>
      <div className="media-list">
        {media.map((item) => <label key={item.path} className="media-file">
          <input type="checkbox" checked={selected.includes(item.path)} onChange={() => toggle(item.path)} />
          <span><strong>{item.name}</strong><small>{(item.size_bytes / 1e9).toFixed(2)} GB</small></span>
        </label>)}
        {!media.length && !error && <p className="empty">No MP4 files found in the configured media roots.</p>}
      </div>
      {!!selected.length && <ol className="chapter-order">{selected.map((path, index) => <li key={path}>
        <span>{index + 1}</span><strong>{path.split("/").pop()}</strong>
        <button onClick={() => move(index, -1)} disabled={index === 0}>↑</button><button onClick={() => move(index, 1)} disabled={index === selected.length - 1}>↓</button>
      </li>)}</ol>}
      {error && <p className="error">{error}</p>}
      <button className="primary" disabled={!selected.length || busy} onClick={submit}>{busy ? "Preparing…" : "Import session"}</button>
    </section>
  </main>;
}
