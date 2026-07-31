import type { components, paths } from "./generated/api-types";

type Schema<Name extends keyof components["schemas"]> = components["schemas"][Name];

export type ApiPaths = paths;
export type SourceFingerprint = Schema<"SourceFingerprint">;
export type ChapterManifest = Schema<"ChapterManifest">;
export type TrackConfig = Schema<"TrackConfig">;
export type DisplayUnits = Schema<"DisplayUnits">;
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
  };
  artifacts: Record<string, string>;
  warnings: string[];
};
export type JobStatus = Schema<"JobStatus">;
export type LapSummary = Schema<"LapSummary">;
export type CornerSummary = Schema<"CornerSummary">;
export type TelemetryWindow = Schema<"TelemetryWindow">;
export type MediaEntry = Schema<"MediaEntry">;
