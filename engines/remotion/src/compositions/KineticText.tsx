import { AbsoluteFill, Sequence, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { BaseProps, FONT_STACK } from "./shared";

export type KineticTextProps = BaseProps & {
  phrases: string[];
};

const Phrase: React.FC<{ text: string; color: string; accent: string; index: number; frames: number }> = ({ text, color, accent, index, frames }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const unit = Math.min(width, height) / 100;
  const pop = spring({ frame, fps, config: { damping: 11, mass: 0.6 } });
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", padding: unit * 6 }}>
      <div
        style={{
          color: index % 2 === 0 ? color : accent,
          fontSize: unit * (text.length > 18 ? 9 : 13),
          fontWeight: 900,
          textAlign: "center",
          lineHeight: 1.0,
          scale: interpolate(pop, [0, 1], [0.6, 1]),
          rotate: `${interpolate(pop, [0, 1], [index % 2 === 0 ? -6 : 6, 0])}deg`,
          opacity: interpolate(frame, [frames - 6, frames], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
        }}
      >
        {text}
      </div>
    </AbsoluteFill>
  );
};

export const KineticText: React.FC<KineticTextProps> = ({
  phrases,
  background = "#0B0B0F",
  textColor = "#FFFFFF",
  accent = "#22D3EE",
  fontFamily = FONT_STACK,
}) => {
  const { durationInFrames } = useVideoConfig();
  const per = Math.max(6, Math.floor(durationInFrames / Math.max(1, phrases.length)));
  return (
    <AbsoluteFill style={{ backgroundColor: background, fontFamily }}>
      {phrases.map((p, i) => (
        <Sequence key={i} from={i * per} durationInFrames={per}>
          <Phrase text={p} color={textColor} accent={accent} index={i} frames={per} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
