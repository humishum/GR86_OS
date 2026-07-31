import { useEffect } from "react";
import type { CornerSummary, LapSummary } from "../types";

const SEEK_SECONDS = 5;
const LARGE_SEEK_SECONDS = 30;
const PROXY_FRAME_SECONDS = 1001 / 60000;
const PLAYBACK_RATES = [0.25, 0.5, 1, 1.5, 2];

type Options = {
  video: HTMLVideoElement | null;
  duration: number;
  laps: LapSummary[];
  corners: CornerSummary[];
  onPlaybackRateChange: (rate: number) => void;
};

function isInteractiveTarget(target: EventTarget | null) {
  return target instanceof Element && Boolean(target.closest(
    "button, input, select, textarea, a[href], [contenteditable]:not([contenteditable='false']), [role='textbox'], [role='slider'], [role='spinbutton'], [role='combobox']",
  ));
}

function clampTime(value: number, duration: number) {
  return Math.min(Math.max(value, 0), Math.max(duration, 0));
}

function lapBoundary(laps: LapSummary[], time: number, direction: -1 | 1) {
  const starts = [...new Set(laps.map((lap) => lap.start_seconds))].sort((a, b) => a - b);
  if (direction > 0) return starts.find((start) => start > time + Number.EPSILON);
  return [...starts].reverse().find((start) => start < time - Number.EPSILON);
}

function eventBoundary(corners: CornerSummary[], time: number, direction: -1 | 1) {
  const times = [...new Set(corners.flatMap((corner) => [
    corner.entry_seconds, corner.apex_seconds, corner.exit_seconds,
  ]).filter((value): value is number => value != null && Number.isFinite(value)))]
    .sort((a, b) => a - b);
  if (direction > 0) return times.find((value) => value > time + Number.EPSILON);
  return [...times].reverse().find((value) => value < time - Number.EPSILON);
}

function adjacentRate(current: number, direction: -1 | 1) {
  if (direction > 0) return PLAYBACK_RATES.find((rate) => rate > current) ?? PLAYBACK_RATES.at(-1)!;
  return [...PLAYBACK_RATES].reverse().find((rate) => rate < current) ?? PLAYBACK_RATES[0];
}

export function usePlaybackShortcuts({ video, duration, laps, corners, onPlaybackRateChange }: Options) {
  useEffect(() => {
    if (!video) return;

    const seek = (seconds: number) => {
      video.currentTime = clampTime(seconds, duration);
    };
    const togglePlayback = () => {
      if (video.paused) void video.play().catch(() => undefined);
      else video.pause();
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || isInteractiveTarget(event.target)) return;

      let handled = true;
      if (event.code === "Space") {
        if (!event.repeat) togglePlayback();
      } else if (event.code === "ArrowLeft" || event.code === "ArrowRight") {
        const direction = event.code === "ArrowLeft" ? -1 : 1;
        if (event.shiftKey) {
          const boundary = lapBoundary(laps, video.currentTime, direction);
          seek(boundary ?? video.currentTime + direction * LARGE_SEEK_SECONDS);
        } else {
          seek(video.currentTime + direction * SEEK_SECONDS);
        }
      } else if ((event.code === "Comma" || event.code === "Period") && event.shiftKey) {
        const direction = event.code === "Comma" ? -1 : 1;
        const rate = adjacentRate(video.playbackRate, direction);
        video.playbackRate = rate;
        onPlaybackRateChange(rate);
      } else if (event.code === "Comma" || event.code === "Period") {
        video.pause();
        seek(video.currentTime + (event.code === "Comma" ? -1 : 1) * PROXY_FRAME_SECONDS);
      } else if (event.code === "BracketLeft" || event.code === "BracketRight") {
        const direction = event.code === "BracketLeft" ? -1 : 1;
        const boundary = lapBoundary(laps, video.currentTime, direction);
        if (boundary != null) seek(boundary);
      } else if (event.code === "Semicolon" || event.code === "Quote") {
        const direction = event.code === "Semicolon" ? -1 : 1;
        const boundary = eventBoundary(corners, video.currentTime, direction);
        if (boundary != null) seek(boundary);
      } else {
        handled = false;
      }

      if (handled) event.preventDefault();
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [corners, duration, laps, onPlaybackRateChange, video]);
}
