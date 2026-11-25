import type { CalculateMetadataFunction } from "remotion";

/** Props shared by every AI Creative Studio composition (passed with --props=props.json). */
export type BaseProps = {
  width?: number;
  height?: number;
  fps?: number;
  durationInSeconds?: number;
  background?: string;
  textColor?: string;
  accent?: string;
  fontFamily?: string;
};

export const FONT_STACK = "Inter, 'Inter Display', 'DejaVu Sans', 'Segoe UI', Arial, sans-serif";

export const metadataFromProps =
  <T extends BaseProps>(defaults: { width: number; height: number; fps: number; seconds: number }): CalculateMetadataFunction<T> =>
  ({ props }) => {
    const fps = props.fps ?? defaults.fps;
    return {
      width: props.width ?? defaults.width,
      height: props.height ?? defaults.height,
      fps,
      durationInFrames: Math.max(1, Math.round((props.durationInSeconds ?? defaults.seconds) * fps)),
    };
  };

/** Asset references are either http(s) URLs or files copied into public/ by the backend. */
export const resolveSrc = (src: string, staticFile: (p: string) => string) =>
  /^https?:\/\//.test(src) ? src : staticFile(src);
