import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { BaseProps, FONT_STACK } from "./shared";

export type LowerThirdProps = BaseProps & {
  name: string;
  role?: string;
  transparent?: boolean;
};

export const LowerThird: React.FC<LowerThirdProps> = ({
  name,
  role,
  transparent = true,
  background = "#00000000",
  textColor = "#FFFFFF",
  accent = "#F97316",
  fontFamily = FONT_STACK,
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames, height } = useVideoConfig();
  const unit = height / 100;
  const ease = Easing.bezier(0.16, 1, 0.3, 1);
  const outStart = durationInFrames - 18;
  const slide = interpolate(frame, [0, 18, outStart, durationInFrames], [-110, 0, 0, -110], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: ease,
  });

  return (
    <AbsoluteFill style={{ backgroundColor: transparent ? "transparent" : background, fontFamily }}>
      <div style={{ position: "absolute", left: unit * 6, bottom: unit * 12, translate: `${slide}% 0px` }}>
        <div style={{ display: "flex", alignItems: "stretch" }}>
          <div style={{ width: unit * 1.1, backgroundColor: accent }} />
          <div style={{ backgroundColor: "rgba(15,23,42,0.88)", padding: `${unit * 1.6}px ${unit * 3}px` }}>
            <div style={{ color: textColor, fontSize: unit * 5.2, fontWeight: 800 }}>{name}</div>
            {role ? (
              <div
                style={{
                  color: accent,
                  fontSize: unit * 3,
                  fontWeight: 600,
                  marginTop: unit * 0.4,
                  opacity: interpolate(frame, [12, 26], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }),
                }}
              >
                {role}
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
