import type { ChapterManifest, CornerSummary, LapSummary } from "../types";
import { formatTime, telemetryNumber, type TelemetrySample } from "../telemetry";

type Props = {
  time: number;
  duration: number;
  chapters: ChapterManifest[];
  laps: LapSummary[];
  corners: CornerSummary[];
  samples: TelemetrySample[];
  onSeek: (seconds: number) => void;
};

function crossingTime(samples: TelemetrySample[], distance: number) {
  for (let index = 1; index < samples.length; index += 1) {
    const beforeDistance = telemetryNumber(samples[index - 1].lap_distance_m);
    const afterDistance = telemetryNumber(samples[index].lap_distance_m);
    const beforeTime = telemetryNumber(samples[index - 1].timestamp);
    const afterTime = telemetryNumber(samples[index].timestamp);
    if (beforeDistance == null || afterDistance == null || beforeTime == null || afterTime == null) continue;
    if ((distance - beforeDistance) * (distance - afterDistance) > 0) continue;
    if (afterDistance === beforeDistance) return beforeTime;
    return beforeTime + ((distance - beforeDistance) / (afterDistance - beforeDistance)) * (afterTime - beforeTime);
  }
  return null;
}

export function Scrubber({ time, duration, chapters, laps, corners, samples, onSeek }: Props) {
  const percent = duration ? (time / duration) * 100 : 0;
  const lapLength = Math.max(...corners.map((corner) => corner.end_distance_m), 1);
  const cornerMarkers = laps
    .flatMap((lap) => {
      const lapSamples = samples.filter((sample) => {
        const sampleTime = telemetryNumber(sample.timestamp);
        return Number(sample.lap_number) === lap.lap_number && sampleTime != null && sampleTime >= lap.start_seconds && sampleTime <= lap.end_seconds;
      });
      return corners.flatMap((corner) => {
        const measuredTime = crossingTime(lapSamples, corner.apex_distance_m);
        if (measuredTime != null) return [{ corner, lap, time: measuredTime }];
        if (!lap.complete) return [];
        return [{ corner, lap, time: lap.start_seconds + (corner.apex_distance_m / lapLength) * lap.lap_time_seconds }];
      });
    });

  return (
    <div className="scrubber">
      <span>{formatTime(time)}</span>
      <div className="scrubber__track">
        <input
          aria-label="Video timeline"
          type="range"
          min={0}
          max={duration || 1}
          step={0.001}
          value={Math.min(time, duration || 1)}
          onChange={(event) => onSeek(Number(event.target.value))}
          style={{ "--progress": `${percent}%` } as React.CSSProperties}
        />
        {chapters.slice(1).map((chapter) => (
          <i key={chapter.index} className="marker marker--chapter" style={{ left: `${(chapter.timeline_start_seconds / duration) * 100}%` }} title={`Chapter ${chapter.index + 1}`} />
        ))}
        {laps.map((lap) => (
          <i key={lap.lap_number} className="marker marker--lap" style={{ left: `${(lap.start_seconds / duration) * 100}%` }} title={`Lap ${lap.lap_number}`} />
        ))}
        {cornerMarkers.map(({ corner, lap, time: cornerTime }) => (
          <i
            key={`${lap.lap_number}-${corner.corner_id}`}
            className="marker marker--corner"
            data-lap-number={lap.lap_number}
            style={{ left: `${(cornerTime / duration) * 100}%` }}
            title={`${corner.name} · Lap ${lap.lap_number}`}
          />
        ))}
      </div>
      <span>{formatTime(duration)}</span>
    </div>
  );
}
