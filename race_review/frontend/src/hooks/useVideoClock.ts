import { useEffect, useState } from "react";

type FrameVideo = HTMLVideoElement & {
  requestVideoFrameCallback?: (callback: (now: number, metadata: { mediaTime: number }) => void) => number;
  cancelVideoFrameCallback?: (handle: number) => void;
};

export function useVideoClock(video: HTMLVideoElement | null) {
  const [time, setTime] = useState(0);

  useEffect(() => {
    if (!video) return;
    const frameVideo = video as FrameVideo;
    let frameHandle = 0;
    let animationHandle = 0;
    let stopped = false;
    const sync = () => setTime(video.currentTime);
    const frame = (_now?: number, metadata?: { mediaTime: number }) => {
      if (stopped) return;
      setTime(metadata?.mediaTime ?? video.currentTime);
      if (frameVideo.requestVideoFrameCallback) frameHandle = frameVideo.requestVideoFrameCallback(frame);
      else animationHandle = requestAnimationFrame(() => frame());
    };
    for (const event of ["loadedmetadata", "timeupdate", "seeking", "seeked"]) {
      video.addEventListener(event, sync);
    }
    frame();
    return () => {
      stopped = true;
      for (const event of ["loadedmetadata", "timeupdate", "seeking", "seeked"]) {
        video.removeEventListener(event, sync);
      }
      if (frameVideo.cancelVideoFrameCallback && frameHandle) frameVideo.cancelVideoFrameCallback(frameHandle);
      if (animationHandle) cancelAnimationFrame(animationHandle);
    };
  }, [video]);
  return time;
}
