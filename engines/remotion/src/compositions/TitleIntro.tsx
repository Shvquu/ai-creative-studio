import { AbsoluteFill, Easing, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { BaseProps, FONT_STACK, resolveSrc } from "./shared";

export type TitleIntroProps = BaseProps & {
  title: string;
  subtitle?: string;
  logo?: string;
};

export const TitleIntro: React.FC<TitleIntroProps> = ({
  title,
  subtitle,
  logo,
  background = "#0F172A",
  textColor = "#F8FAFC",
  accent = "#38BDF8",
  fontFamily = FONT_STACK,
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames, width, height } = useVideoConfig();
  const unit = Math.min(width, height) / 100;
  const words = title.split(" ");
  const outStart = durationInFrames - Math.round(0.6 * fps);

  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(circle at ${interpolate(frame, [0, durationInFrames], [30, 70])}% 40%, ${accent}33 0%, ${background} 60%)`,
        backgroundColor: background,
        justifyContent: "center",
        alignItems: "center",
        fontFamily,
        opacity: interpolate(frame, [outStart, durationInFrames], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
      }}
    >
      {logo ? (
        <Img
          src={resolveSrc(logo, staticFile)}
          style={{
            width: unit * 18,
            height: unit * 18,
            objectFit: "contain",
            marginBottom: unit * 4,
            scale: spring({ frame, fps, config: { damping: 14 } }),
          }}
        />
      ) : null}
      <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: unit * 2.2, maxWidth: width * 0.86 }}>
        {words.map((word, i) => (
          <span
            key={i}
            style={{
              color: textColor,
              fontSize: unit * 11,
              fontWeight: 800,
              letterSpacing: -unit * 0.2,
              opacity: interpolate(frame, [6 + i * 4, 18 + i * 4], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
              translate: `0px ${interpolate(
                spring({ frame: frame - 6 - i * 4, fps, config: { damping: 200 } }),
                [0, 1],
                [unit * 6, 0],
              )}px`,
            }}
          >
            {word}
          </span>
        ))}
      </div>
      <div
        style={{
          height: unit * 0.8,
          marginTop: unit * 3,
          backgroundColor: accent,
          borderRadius: unit,
          width: interpolate(frame, [10, 40], [0, unit * 22], {
            extrapolateLeft: "clamp",
            extrapolateRight: "clamp",
            easing: Easing.bezier(0.16, 1, 0.3, 1),
          }),
        }}
      />
      {subtitle ? (
        <div
          style={{
            marginTop: unit * 3,
            color: textColor,
            fontSize: unit * 4.2,
            fontWeight: 400,
            opacity: interpolate(frame, [30, 50], [0, 0.85], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
            textAlign: "center",
            maxWidth: width * 0.8,
          }}
        >
          {subtitle}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
