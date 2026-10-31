import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { api } from "../api";
import type { Calibration, CornerSummary, DisplayUnits, SessionManifest, TrackConfig } from "../types";
import { ActionableError, errorMessage } from "./ActionableError";
import { UnitSelector } from "./UnitSelector";

export function EditPanel({ session, corners, onSaved, showDiagnostics, onShowDiagnosticsChange }: { session: SessionManifest; corners: CornerSummary[]; onSaved: () => void; showDiagnostics: boolean; onShowDiagnosticsChange: (show: boolean) => void }) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const wasOpen = useRef(false);
  const headingId = useId();
  const [track, setTrack] = useState<TrackConfig>(session.edits.track);
  const [calibration, setCalibration] = useState<Calibration>(session.edits.calibration);
  const [displayUnits, setDisplayUnits] = useState<DisplayUnits>(session.edits.display_units);
  const [cornerValues, setCornerValues] = useState(() => Object.fromEntries(corners.map((corner) => [corner.corner_id, {
    name: corner.name, start_distance_m: corner.start_distance_m,
    apex_distance_m: corner.apex_distance_m, end_distance_m: corner.end_distance_m,
  }])));
  const [cornerActions, setCornerActions] = useState<Array<Record<string, unknown>>>([]);
  const [mergeIds, setMergeIds] = useState<string[]>([]);
  const [tileUrl, setTileUrl] = useState(() => localStorage.getItem("race-review-map-tiles") ?? "");
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState("");
  useEffect(() => {
    if (open) {
      wasOpen.current = true;
      const handle = requestAnimationFrame(() => closeButton.current?.focus());
      return () => cancelAnimationFrame(handle);
    }
    if (wasOpen.current) {
      wasOpen.current = false;
      trigger.current?.focus();
    }
  }, [open]);
  const close = () => setOpen(false);
  const dialogKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = [...(dialog.current?.querySelectorAll<HTMLElement>(
      'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [href], [tabindex]:not([tabindex="-1"])',
    ) ?? [])].filter((element) => !element.hidden);
    if (!focusable.length) {
      event.preventDefault();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };
  const coordinate = (end: "a" | "b", axis: "east_m" | "north_m", value: number) => setTrack((current) => ({
    ...current,
    [`start_finish_${end}`]: { ...(current[`start_finish_${end}`] ?? { east_m: 0, north_m: 0 }), [axis]: value },
  }));
  const save = async () => {
    setBusy(true); setSaveError("");
    const edits = corners.filter((corner) => {
      const value = cornerValues[corner.corner_id];
      return value && (value.name !== corner.name || value.start_distance_m !== corner.start_distance_m || value.apex_distance_m !== corner.apex_distance_m || value.end_distance_m !== corner.end_distance_m);
    }).map((corner) => ({ action: "update", corner_id: corner.corner_id, ...cornerValues[corner.corner_id] }));
    try {
      await api.saveTrack(session.session_id, track);
      await api.saveCalibration(session.session_id, calibration);
      await api.saveDisplayUnits(session.session_id, displayUnits);
      if (edits.length || cornerActions.length) await api.saveCorners(session.session_id, [...edits, ...cornerActions]);
      localStorage.setItem("race-review-units", JSON.stringify(displayUnits));
      if (tileUrl) localStorage.setItem("race-review-map-tiles", tileUrl);
      else localStorage.removeItem("race-review-map-tiles");
      close(); onSaved();
    } catch (reason) {
      setSaveError(errorMessage(reason, "Could not save analysis changes."));
    } finally { setBusy(false); }
  };
  return <>
    <button ref={trigger} className="icon-button" onClick={() => setOpen(true)} aria-label="Edit analysis">TUNE</button>
    {open && <div className="drawer-backdrop" onClick={close}><aside
      ref={dialog}
      className="edit-drawer"
      role="dialog"
      aria-modal="true"
      aria-labelledby={headingId}
      onClick={(event) => event.stopPropagation()}
      onKeyDown={dialogKeyDown}
    >
      <div className="section-heading"><h2 id={headingId}>Analysis setup</h2><button ref={closeButton} className="icon-button" onClick={close}>CLOSE</button></div>
      <p className="muted">Stored calculations remain SI. Overrides are deterministic and survive reprocessing.</p>
      <h3>Display units</h3>
      <UnitSelector value={displayUnits} onChange={setDisplayUnits} />
      <h3>Diagnostics</h3>
      <label className="check-field"><input type="checkbox" checked={showDiagnostics} onChange={(event) => onShowDiagnosticsChange(event.target.checked)} /> Show synchronization diagnostics</label>
      <label className="field">Optional MapLibre raster tile template<input value={tileUrl} onChange={(event) => setTileUrl(event.target.value)} placeholder="https://…/{z}/{x}/{y}.png" /></label>
      <h3>Start / finish line</h3>
      {(["a", "b"] as const).map((end) => <div className="coordinate-row" key={end}><b>{end.toUpperCase()}</b>
        <label>East <input type="number" step="0.1" value={track[`start_finish_${end}`]?.east_m ?? 0} onChange={(event) => coordinate(end, "east_m", Number(event.target.value))} /></label>
        <label>North <input type="number" step="0.1" value={track[`start_finish_${end}`]?.north_m ?? 0} onChange={(event) => coordinate(end, "north_m", Number(event.target.value))} /></label>
      </div>)}
      <label className="field">Crossing direction<select value={track.crossing_direction} onChange={(event) => setTrack({ ...track, crossing_direction: Number(event.target.value) as -1 | 1 })}><option value={1}>Forward</option><option value={-1}>Reverse</option></select></label>
      <label className="check-field"><input type="checkbox" checked={track.exclude_out_lap} onChange={(event) => setTrack({ ...track, exclude_out_lap: event.target.checked })} /> Exclude partial out lap</label>
      <label className="check-field"><input type="checkbox" checked={track.exclude_in_lap} onChange={(event) => setTrack({ ...track, exclude_in_lap: event.target.checked })} /> Exclude partial in lap</label>
      <h3>Camera axes <small>{Math.round(calibration.confidence * 100)}% confidence</small></h3>
      <div className="coordinate-row"><label>Forward<select value={calibration.transform.forward_axis} onChange={(event) => setCalibration({ ...calibration, transform: { ...calibration.transform, forward_axis: event.target.value as "x" | "y" | "z" } })}><option>x</option><option>y</option><option>z</option></select></label>
        <label>Sign<select value={calibration.transform.forward_sign} onChange={(event) => setCalibration({ ...calibration, transform: { ...calibration.transform, forward_sign: Number(event.target.value) as -1 | 1 } })}><option value={1}>+</option><option value={-1}>−</option></select></label></div>
      <div className="coordinate-row"><label>Lateral<select value={calibration.transform.lateral_axis} onChange={(event) => setCalibration({ ...calibration, transform: { ...calibration.transform, lateral_axis: event.target.value as "x" | "y" | "z" } })}><option>x</option><option>y</option><option>z</option></select></label>
        <label>Sign<select value={calibration.transform.lateral_sign} onChange={(event) => setCalibration({ ...calibration, transform: { ...calibration.transform, lateral_sign: Number(event.target.value) as -1 | 1 } })}><option value={1}>+</option><option value={-1}>−</option></select></label></div>
      <h3>Corner names</h3>
      {corners.map((corner) => <div className="corner-editor" key={corner.corner_id}>
        <label className="corner-editor__select"><input type="checkbox" checked={mergeIds.includes(corner.corner_id)} onChange={() => setMergeIds((current) => current.includes(corner.corner_id) ? current.filter((id) => id !== corner.corner_id) : [...current, corner.corner_id])} />{corner.corner_id}</label>
        <input aria-label={`${corner.name} name`} value={cornerValues[corner.corner_id]?.name ?? corner.name} onChange={(event) => setCornerValues({ ...cornerValues, [corner.corner_id]: { ...cornerValues[corner.corner_id], name: event.target.value } })} />
        <div>{(["start_distance_m", "apex_distance_m", "end_distance_m"] as const).map((field) => <label key={field}>{field.split("_")[0]}<input type="number" step="1" value={cornerValues[corner.corner_id]?.[field] ?? corner[field]} onChange={(event) => setCornerValues({ ...cornerValues, [corner.corner_id]: { ...cornerValues[corner.corner_id], [field]: Number(event.target.value) } })} /></label>)}</div>
        <button className="secondary" onClick={() => setCornerActions([...cornerActions, { action: "split", corner_id: corner.corner_id, boundary_distance_m: cornerValues[corner.corner_id]?.apex_distance_m ?? corner.apex_distance_m }])}>Split at apex</button>
      </div>)}
      <button className="secondary" disabled={mergeIds.length < 2} onClick={() => { setCornerActions([...cornerActions, { action: "merge", corner_ids: mergeIds, merged_id: `merged-${mergeIds.join("-")}` }]); setMergeIds([]); }}>Merge selected</button>
      {saveError && <ActionableError
        compact
        title="Could not save analysis changes"
        message={saveError}
        primaryAction={{ label: "Try save again", onClick: () => void save(), disabled: busy }}
      />}
      <button className="primary" disabled={busy} onClick={save}>{busy ? "Reanalyzing…" : "Save and reanalyze"}</button>
    </aside></div>}
  </>;
}
