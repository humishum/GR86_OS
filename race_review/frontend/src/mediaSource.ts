import type { SessionManifest } from "./types";

export type MediaSourceKind = "source" | "proxy";

export type MediaSourceSelection = {
  kind: MediaSourceKind;
  url: string;
  fallbackUrl: string | null;
};

type CanPlayType = (mediaType: string) => CanPlayTypeResult;

function directMediaType(session: SessionManifest): string | null {
  if (session.chapters.length !== 1) return null;
  const video = (session.chapters[0]?.streams ?? []).find(
    (stream) => stream.codec_type === "video",
  );
  const codec = video?.codec_name?.toLowerCase();
  const tag = video?.codec_tag?.toLowerCase();
  if (codec === "hevc" || codec === "h265" || tag === "hvc1" || tag === "hev1") {
    return 'video/mp4; codecs="hvc1"';
  }
  if (codec === "h264" || codec === "avc" || tag === "avc1") {
    return 'video/mp4; codecs="avc1"';
  }
  return null;
}

export function selectMediaSource(
  sessionId: string,
  session: SessionManifest,
  canPlayType: CanPlayType,
): MediaSourceSelection {
  const proxyUrl = `/api/sessions/${sessionId}/media/proxy`;
  const mediaType = directMediaType(session);
  if (mediaType && canPlayType(mediaType) !== "") {
    return {
      kind: "source",
      url: `/api/sessions/${sessionId}/media/source`,
      fallbackUrl: proxyUrl,
    };
  }
  return { kind: "proxy", url: proxyUrl, fallbackUrl: null };
}
