import type { ChapterManifest, CornerSummary, LapSummary } from "../types";
import { formatTime } from "../telemetry";

type Props = {
  time: number;
  duration: number;
  chapters: ChapterManifest[];
  laps: LapSummary[];
  corners: CornerSummary[];
  onSeek: (seconds: number) => void;
};

export function Scrubber({ time, duration, chapters, laps, corners, onSeek }: Props) {
  const percent = duration ? (time / duration) * 100 : 0;
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
        {corners.map((corner) => {
          const lap = laps.find((item) => item.complete && !item.excluded);
          const lapLength = Math.max(...corners.map((item) => item.end_distance_m), 1);
          const cornerTime = lap ? lap.start_seconds + (corner.apex_distance_m / lapLength) * lap.lap_time_seconds : 0;
          return <i key={corner.corner_id} className="marker marker--corner" style={{ left: `${(cornerTime / duration) * 100}%` }} title={corner.name} />;
        })}
      </div>
      <span>{formatTime(duration)}</span>
    </div>
  );
}
