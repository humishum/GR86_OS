import type { components, paths } from "./generated/api-types";

type Schema<Name extends keyof components["schemas"]> = components["schemas"][Name];

export type ApiPaths = paths;
export type SourceFingerprint = Schema<"SourceFingerprint">;
export type ChapterManifest = Schema<"ChapterManifest">;
export type TrackConfig = Schema<"TrackConfig">;
export type DisplayUnits = Schema<"DisplayUnits">;
export type ClipRange = {
  start_seconds: number;
  end_seconds: number;
};
export type Bookmark = {
  id: string;
  seconds: number;
  label: string;
  note: string;
  tags: string[];
  clip: ClipRange | null;
};
export type DeltaRegion = {
  kind: "gain" | "loss";
  start_distance_m: number;
  end_distance_m: number;
  delta_change_s: number;
  peak_rate_s_per_m: number | null;
};
export type CornerComparison = {
  corner_id: string;
  name: string;
  start_distance_m: number;
  apex_distance_m: number;
  end_distance_m: number;
  time_impact_s: number;
  reference_entry_speed_mps: number | null;
  comparison_entry_speed_mps: number | null;
  reference_apex_speed_mps: number | null;
  comparison_apex_speed_mps: number | null;
  reference_exit_speed_mps: number | null;
  comparison_exit_speed_mps: number | null;
  reference_peak_lateral_g: number | null;
  comparison_peak_lateral_g: number | null;
  reference_braking_distance_m: number | null;
  comparison_braking_distance_m: number | null;
};
export type LapComparison = {
  reference_lap: number;
  comparison_lap: number;
  distance_m: number[];
  reference_time_s: number[];
  comparison_time_s: number[];
  delta_s: number[];
  reference_speed_mps: number[];
  comparison_speed_mps: number[];
  reference_lateral_g?: Array<number | null>;
  comparison_lateral_g?: Array<number | null>;
  reference_longitudinal_g?: Array<number | null>;
  comparison_longitudinal_g?: Array<number | null>;
  regions?: DeltaRegion[];
  corners?: CornerComparison[];
};
export type Calibration = Omit<Schema<"Calibration">, "transform" | "diagnostics"> & {
  transform: Schema<"AxisTransform">;
  diagnostics: Record<string, unknown>;
};
export type SessionManifest = Omit<
  Schema<"SessionManifest">,
  "streams" | "coordinate_origin" | "edits" | "artifacts" | "warnings"
> & {
  streams: Schema<"StreamQualitySummary">[];
  coordinate_origin: Schema<"CoordinateOrigin"> | null;
  edits: {
    track: TrackConfig;
    calibration: Calibration;
    corner_edits: Array<Record<string, unknown>>;
    display_units: DisplayUnits;
    reference_lap: number | null;
    bookmarks: Bookmark[];
  };
  artifacts: Record<string, string>;
  warnings: string[];
};
export type JobStatus = Schema<"JobStatus">;
export type LapSummary = Schema<"LapSummary">;
export type CornerSummary = Schema<"CornerSummary">;
export type TelemetryWindow = Schema<"TelemetryWindow">;
export type MediaEntry = Schema<"MediaEntry">;
