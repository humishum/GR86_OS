import type { TelemetrySample } from "../telemetry";
import { mph } from "../telemetry";

function Gauge({ label, value, unit, accent }: { label: string; value: string; unit: string; accent?: boolean }) {
  return (
    <div className={`gauge ${accent ? "gauge--accent" : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{unit}</small>
    </div>
  );
}

export function Gauges({ sample, delta }: { sample: TelemetrySample | null; delta: number | null }) {
  return (
    <div className="gauges" aria-label="Live telemetry">
      <Gauge label="SPEED" value={mph(Number(sample?.speed_mps ?? 0)).toFixed(0)} unit="MPH" accent />
      <Gauge label="LONG" value={Number(sample?.longitudinal_g ?? 0).toFixed(2)} unit="G" />
      <Gauge label="LAT" value={Number(sample?.lateral_g ?? 0).toFixed(2)} unit="G" />
      <Gauge label="LAP" value={String(Math.round(Number(sample?.lap_number ?? 0)) || "–")} unit="CURRENT" />
      <Gauge label="DELTA" value={delta == null ? "—" : `${delta >= 0 ? "+" : ""}${delta.toFixed(2)}`} unit="SEC" />
    </div>
  );
}
