import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { LapSummary } from "../types";
import { formatTime, mph } from "../telemetry";
import { TelemetryChart } from "./TelemetryChart";

export function LapPanel({ sessionId, laps, onSeek }: { sessionId: string; laps: LapSummary[]; onSeek: (value: number) => void }) {
  const completeLaps = useMemo(() => laps.filter((lap) => lap.complete && !lap.excluded), [laps]);
  const [reference, setReference] = useState(completeLaps[0]?.lap_number ?? 1);
  const [comparison, setComparison] = useState(completeLaps[1]?.lap_number ?? 2);
  const [data, setData] = useState<Record<string, number[]> | null>(null);
  useEffect(() => {
    if (reference === comparison || completeLaps.length < 2) return;
    api.comparison(sessionId, reference, comparison).then(setData).catch(() => setData(null));
  }, [sessionId, reference, comparison, completeLaps.length]);
  const chartSeries = useMemo(() => data ? [
    { label: `Lap ${reference} mph`, values: data.reference_speed_mps.map(mph), color: "#f2f5f6" },
    { label: `Lap ${comparison} mph`, values: data.comparison_speed_mps.map(mph), color: "#ff5038" },
  ] : [], [data, reference, comparison]);
  return (
    <section className="lap-panel">
      <div className="section-heading"><h2>Laps</h2><span>{completeLaps.length} complete</span></div>
      <div className="lap-table" role="table">
        {laps.map((lap) => (
          <button key={lap.lap_number} className="lap-row" onClick={() => onSeek(lap.start_seconds)}>
            <strong>{lap.complete ? lap.lap_number : "—"}</strong><span>{formatTime(lap.lap_time_seconds)}{lap.complete ? "" : " partial"}</span>
            <span>{mph(lap.maximum_speed_mps).toFixed(0)} mph</span>
          </button>
        ))}
      </div>
      {completeLaps.length >= 2 && <div className="comparison">
        <div className="comparison__controls">
          <label>Reference <select value={reference} onChange={(event) => setReference(Number(event.target.value))}>{completeLaps.map((lap) => <option key={lap.lap_number}>{lap.lap_number}</option>)}</select></label>
          <label>Compare <select value={comparison} onChange={(event) => setComparison(Number(event.target.value))}>{completeLaps.map((lap) => <option key={lap.lap_number}>{lap.lap_number}</option>)}</select></label>
        </div>
        {data && <><TelemetryChart x={data.distance_m} series={chartSeries} /><TelemetryChart x={data.distance_m} series={[{ label: "Delta s", values: data.delta_s, color: "#ffb238" }]} /></>}
      </div>}
    </section>
  );
}
