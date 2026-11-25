import { Composition } from "remotion";
import { KineticText, KineticTextProps } from "./compositions/KineticText";
import { LowerThird, LowerThirdProps } from "./compositions/LowerThird";
import { Outro, OutroProps } from "./compositions/Outro";
import { metadataFromProps } from "./compositions/shared";
import { SocialPost, SocialPostProps } from "./compositions/SocialPost";
import { TitleIntro, TitleIntroProps } from "./compositions/TitleIntro";

/**
 * Compositions used by the AI Creative Studio backend (backend/providers/remotion.py).
 * Size, fps and duration come from props (width, height, fps, durationInSeconds).
 */
export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="TitleIntro"
        component={TitleIntro}
        durationInFrames={120}
        fps={30}
        width={1920}
        height={1080}
        defaultProps={{ title: "AI Creative Studio", subtitle: "Lokal · Open Source · Kostenlos" } as TitleIntroProps}
        calculateMetadata={metadataFromProps<TitleIntroProps>({ width: 1920, height: 1080, fps: 30, seconds: 4 })}
      />
      <Composition
        id="LowerThird"
        component={LowerThird}
        durationInFrames={150}
        fps={30}
        width={1920}
        height={1080}
        defaultProps={{ name: "Alex Beispiel", role: "Creative Director", transparent: false, background: "#334155" } as LowerThirdProps}
        calculateMetadata={metadataFromProps<LowerThirdProps>({ width: 1920, height: 1080, fps: 30, seconds: 5 })}
      />
      <Composition
        id="SocialPost"
        component={SocialPost}
        durationInFrames={180}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{ headline: "Dein Produkt. Neu gedacht.", subline: "Jetzt entdecken", cta: "Mehr erfahren", brandName: "Brand" } as SocialPostProps}
        calculateMetadata={metadataFromProps<SocialPostProps>({ width: 1080, height: 1920, fps: 30, seconds: 6 })}
      />
      <Composition
        id="KineticText"
        component={KineticText}
        durationInFrames={150}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={{ phrases: ["Lokal.", "Kostenlos.", "Kreativ."] } as KineticTextProps}
        calculateMetadata={metadataFromProps<KineticTextProps>({ width: 1080, height: 1920, fps: 30, seconds: 4.5 })}
      />
      <Composition
        id="Outro"
        component={Outro}
        durationInFrames={120}
        fps={30}
        width={1920}
        height={1080}
        defaultProps={{ headline: "Danke fürs Zuschauen", cta: "Abonnieren" } as OutroProps}
        calculateMetadata={metadataFromProps<OutroProps>({ width: 1920, height: 1080, fps: 30, seconds: 4 })}
      />
    </>
  );
};
