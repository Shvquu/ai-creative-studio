import { AbsoluteFill, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { BaseProps, FONT_STACK, resolveSrc } from "./shared";

export type OutroProps = BaseProps & {
  headline?: string;
  cta?: string;
  url?: string;
  logo?: string;
};

export const Outro: React.FC<OutroProps> = ({
  headline = "Danke fürs Zuschauen",
  cta,
  url,
  logo,
  background = "#111827",
  textColor = "#F9FAFB",
  accent = "#A78BFA",
  fontFamily = FONT_STACK,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const unit = Math.min(width, height) / 100;
  const s = (d: number) => spring({ frame: frame - d, fps, config: { damping: 200 } });
  return (
    <AbsoluteFill style={{ backgroundColor: background, justifyContent: "center", alignItems: "center", fontFamily, gap: unit * 3 }}>
      {logo ? <Img src={resolveSrc(logo, staticFile)} style={{ width: unit * 16, height: unit * 16, objectFit: "contain", scale: s(0) }} /> : null}
      <div style={{ color: textColor, fontSize: unit * 8, fontWeight: 800, opacity: s(6), translate: `0px ${interpolate(s(6), [0, 1], [unit * 4, 0])}px` }}>
        {headline}
      </div>
      {cta ? (
        <div style={{ color: background, backgroundColor: accent, fontSize: unit * 4, fontWeight: 700, padding: `${unit * 1.5}px ${unit * 3.5}px`, borderRadius: unit * 4, scale: s(16) }}>
          {cta}
        </div>
      ) : null}
      {url ? <div style={{ color: accent, fontSize: unit * 3.4, opacity: s(24) }}>{url}</div> : null}
    </AbsoluteFill>
  );
};
