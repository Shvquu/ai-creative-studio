import { AbsoluteFill, Easing, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { BaseProps, FONT_STACK, resolveSrc } from "./shared";

export type SocialPostProps = BaseProps & {
  image?: string;
  headline: string;
  subline?: string;
  cta?: string;
  brandName?: string;
};

export const SocialPost: React.FC<SocialPostProps> = ({
  image,
  headline,
  subline,
  cta,
  brandName,
  background = "#111827",
  textColor = "#FFFFFF",
  accent = "#FACC15",
  fontFamily = FONT_STACK,
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames, width, height } = useVideoConfig();
  const unit = Math.min(width, height) / 100;
  const ease = Easing.bezier(0.16, 1, 0.3, 1);
  const enter = (delay: number) => spring({ frame: frame - delay, fps, config: { damping: 200 } });

  return (
    <AbsoluteFill style={{ backgroundColor: background, fontFamily, overflow: "hidden" }}>
      {image ? (
        <Img
          src={resolveSrc(image, staticFile)}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            scale: interpolate(frame, [0, durationInFrames], [1.04, 1.16]),
          }}
        />
      ) : null}
      <AbsoluteFill style={{ background: "linear-gradient(180deg, rgba(0,0,0,0) 35%, rgba(0,0,0,0.78) 100%)" }} />
      <AbsoluteFill style={{ justifyContent: "flex-end", padding: unit * 7, gap: unit * 2.4 }}>
        {brandName ? (
          <div style={{ color: accent, fontSize: unit * 3.6, fontWeight: 700, letterSpacing: unit * 0.3, opacity: enter(4) }}>
            {brandName.toUpperCase()}
          </div>
        ) : null}
        <div
          style={{
            color: textColor,
            fontSize: unit * 8.5,
            fontWeight: 900,
            lineHeight: 1.05,
            translate: `0px ${interpolate(enter(8), [0, 1], [unit * 8, 0])}px`,
            opacity: enter(8),
          }}
        >
          {headline}
        </div>
        {subline ? (
          <div style={{ color: textColor, fontSize: unit * 4.2, opacity: interpolate(frame, [22, 40], [0, 0.9], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: ease }) }}>
            {subline}
          </div>
        ) : null}
        {cta ? (
          <div
            style={{
              alignSelf: "flex-start",
              marginTop: unit * 1.5,
              backgroundColor: accent,
              color: "#111827",
              fontSize: unit * 4,
              fontWeight: 800,
              padding: `${unit * 1.6}px ${unit * 3.4}px`,
              borderRadius: unit * 5,
              scale: spring({ frame: frame - 34, fps, config: { damping: 12 } }),
            }}
          >
            {cta}
          </div>
        ) : null}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
