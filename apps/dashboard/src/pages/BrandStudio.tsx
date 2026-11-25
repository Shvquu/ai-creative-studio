import { useState } from "react";
import { fileUrl, type Asset } from "../api";
import { AssetGrid, Badge, Button, Card, Drawer, Empty, Field, JobResult, PageHeader, Spinner } from "../components/ui";
import { useApi, useJob, useSubmit } from "../state";
import { AssetDetail } from "./AssetLibrary";

interface PaletteColor {
  hex: string;
  contrast_white: number;
  contrast_black: number;
  text_color: string;
  wcag_aa_text: boolean;
}

interface Pairing {
  id: string;
  heading: string;
  body: string;
  mood: string[];
  license: string;
}

const splitList = (s: string) =>
  s
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);

export default function BrandStudio() {
  const submit = useSubmit();
  // brief
  const [name, setName] = useState("");
  const [industry, setIndustry] = useState("");
  const [tagline, setTagline] = useState("");
  const [audience, setAudience] = useState("");
  const [positioning, setPositioning] = useState("");
  const [values, setValues] = useState("");
  const [voice, setVoice] = useState("");
  const [baseColor, setBaseColor] = useState("#2563EB");
  const [harmony, setHarmony] = useState("analogous");
  const [logoStyle, setLogoStyle] = useState("logo-flat");
  const [concepts, setConcepts] = useState(4);
  const [symbol, setSymbol] = useState("");
  const [imagery, setImagery] = useState("");
  const [provider, setProvider] = useState("");
  const [kitJobId, setKitJobId] = useState<string | null>(null);
  const kitJob = useJob(kitJobId);

  // palette tool
  const [palBase, setPalBase] = useState("#0EA5E9");
  const [palHarmony, setPalHarmony] = useState("complementary");
  const [palJobId, setPalJobId] = useState<string | null>(null);
  const palJob = useJob(palJobId);
  const colors = (palJob?.result?.colors as PaletteColor[] | undefined) ?? [];

  // typography
  const [keywords, setKeywords] = useState("modern tech");
  const typo = useApi<{ suggestions: Pairing[] }>(`/api/brand/typography?keywords=${encodeURIComponent(keywords)}`, [], 0);

  const brandAssets = useApi<{ assets: Asset[] }>("/api/assets?tags=brand&limit=24", [kitJob?.status]);
  const guides = useApi<{ assets: Asset[] }>("/api/assets?tags=guidelines&kind=document&limit=12", [kitJob?.status]);
  const [detail, setDetail] = useState<string | null>(null);

  const runKit = async (e: React.FormEvent) => {
    e.preventDefault();
    const inputs: Record<string, unknown> = {
      brand_name: name,
      industry,
      base_color: baseColor,
      harmony,
      logo_style: logoStyle,
      logo_concepts: concepts,
      brand_values: splitList(values),
      voice: splitList(voice),
    };
    if (tagline) inputs.tagline = tagline;
    if (audience) inputs.audience = audience;
    if (positioning) inputs.positioning = positioning;
    if (symbol) inputs.logo_symbol = symbol;
    if (imagery) inputs.imagery_prompt = imagery;
    if (provider) inputs.image_provider = provider;
    const job = await submit("/api/workflows/branding/brand-kit/run", { inputs, project: name });
    if (job) setKitJobId(job.id);
  };

  const runPalette = async () => {
    const job = await submit("/api/images/palette", { base_color: palBase, harmony: palHarmony, count: 5 });
    if (job) setPalJobId(job.id);
  };

  return (
    <div className="page">
      <PageHeader title="Brand Studio" description="Markenidentität: Brief, Farbpalette, Typografie, Logo-Konzepte und Brand Guidelines." />
      <div className="studio">
        <div className="studio-main">
          <Card title="Brand Brief → Brand Kit" subtitle="Erzeugt Palette, Typografie, Logo-Konzepte, Bildsprache, Social-Post und Guidelines (HTML + Markdown).">
            <form className="form" onSubmit={runKit}>
              <Field label="Markenname">{(id) => <input id={id} className="input" required value={name} onChange={(e) => setName(e.target.value)} />}</Field>
              <Field label="Branche / Angebot">{(id) => <input id={id} className="input" required value={industry} onChange={(e) => setIndustry(e.target.value)} placeholder="z. B. Specialty-Coffee-Rösterei" />}</Field>
              <Field label="Tagline">{(id) => <input id={id} className="input" value={tagline} onChange={(e) => setTagline(e.target.value)} />}</Field>
              <Field label="Logo-Idee / Symbol">{(id) => <input id={id} className="input" value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder="z. B. stilisierte Kaffeebohne mit Polarlicht" />}</Field>
              <Field label="Zielgruppe" wide>
                {(id) => <textarea id={id} className="input" rows={2} value={audience} onChange={(e) => setAudience(e.target.value)} />}
              </Field>
              <Field label="Positionierung" wide>
                {(id) => <textarea id={id} className="input" rows={2} value={positioning} onChange={(e) => setPositioning(e.target.value)} />}
              </Field>
              <Field label="Werte" hint="Komma-getrennt">
                {(id) => <input id={id} className="input" value={values} onChange={(e) => setValues(e.target.value)} placeholder="ehrlich, handwerklich, warm" />}
              </Field>
              <Field label="Tonalität" hint="Komma-getrennt">
                {(id) => <input id={id} className="input" value={voice} onChange={(e) => setVoice(e.target.value)} placeholder="freundlich, klar" />}
              </Field>
              <Field label="Primärfarbe">{(id) => <input id={id} className="input input-color" type="color" value={baseColor} onChange={(e) => setBaseColor(e.target.value.toUpperCase())} />}</Field>
              <Field label="Farbharmonie">
                {(id) => (
                  <select id={id} className="input" value={harmony} onChange={(e) => setHarmony(e.target.value)}>
                    {["analogous", "complementary", "triadic", "split", "monochrome"].map((h) => (
                      <option key={h}>{h}</option>
                    ))}
                  </select>
                )}
              </Field>
              <Field label="Logo-Stil">
                {(id) => (
                  <select id={id} className="input" value={logoStyle} onChange={(e) => setLogoStyle(e.target.value)}>
                    <option value="logo-flat">flach / vektorartig</option>
                    <option value="logo-3d">3D / glänzend</option>
                  </select>
                )}
              </Field>
              <Field label={`Logo-Konzepte: ${concepts}`}>{(id) => <input id={id} type="range" min={1} max={8} value={concepts} onChange={(e) => setConcepts(Number(e.target.value))} />}</Field>
              <Field label="Bildsprache (Prompt, optional)" wide>
                {(id) => <input id={id} className="input" value={imagery} onChange={(e) => setImagery(e.target.value)} placeholder="z. B. helle Lifestyle-Fotos in einem gemütlichen Café" />}
              </Field>
              <Field label="Provider">
                {(id) => (
                  <select id={id} className="input" value={provider} onChange={(e) => setProvider(e.target.value)}>
                    <option value="">Standard (ComfyUI)</option>
                    <option value="mock">Mock – Testmodus</option>
                  </select>
                )}
              </Field>
              <div className="form-actions">
                <Button variant="primary" type="submit" disabled={!name || !industry}>
                  Brand Kit erstellen
                </Button>
              </div>
            </form>
            {kitJob && <JobResult job={kitJob} onAssetClick={(a) => setDetail(a.id)} />}
          </Card>

          <Card title="Brand-Assets">
            {brandAssets.data ? brandAssets.data.assets.length ? <AssetGrid assets={brandAssets.data.assets} small onSelect={(a) => setDetail(a.id)} /> : <Empty>Noch keine Brand-Assets.</Empty> : <Spinner />}
            {guides.data && guides.data.assets.length > 0 && (
              <div className="mt">
                <h3 className="h3">Brand Guidelines</h3>
                <ul className="links">
                  {guides.data.assets
                    .filter((a) => a.path.endsWith(".html"))
                    .map((a) => (
                      <li key={a.id}>
                        <a href={fileUrl(a.id)} target="_blank" rel="noreferrer">
                          {a.project ?? a.path} – Guidelines öffnen ↗
                        </a>
                      </li>
                    ))}
                </ul>
              </div>
            )}
          </Card>
        </div>

        <aside className="studio-side">
          <Card title="Farbpalette">
            <div className="form compact">
              <Field label="Basisfarbe">{(id) => <input id={id} className="input input-color" type="color" value={palBase} onChange={(e) => setPalBase(e.target.value.toUpperCase())} />}</Field>
              <Field label="Harmonie">
                {(id) => (
                  <select id={id} className="input" value={palHarmony} onChange={(e) => setPalHarmony(e.target.value)}>
                    {["analogous", "complementary", "triadic", "split", "monochrome"].map((h) => (
                      <option key={h}>{h}</option>
                    ))}
                  </select>
                )}
              </Field>
              <Button variant="primary" onClick={() => void runPalette()}>
                Palette erzeugen
              </Button>
            </div>
            {palJob && palJob.status !== "succeeded" && <JobResult job={palJob} />}
            {colors.length > 0 && (
              <div className="swatches">
                {colors.map((c) => (
                  <div key={c.hex} className="swatch" style={{ background: c.hex, color: c.text_color }}>
                    <strong>{c.hex}</strong>
                    <small>
                      W {c.contrast_white} · S {c.contrast_black}
                    </small>
                    <Badge tone={c.wcag_aa_text ? "ok" : "warn"}>{c.wcag_aa_text ? "AA Text" : "nur groß"}</Badge>
                  </div>
                ))}
              </div>
            )}
          </Card>
          <Card title="Typografie" subtitle="Freie Schriften (SIL OFL)">
            <Field label="Stimmung / Stichworte">{(id) => <input id={id} className="input" value={keywords} onChange={(e) => setKeywords(e.target.value)} />}</Field>
            {typo.data ? (
              <ul className="pairings">
                {typo.data.suggestions.map((p) => (
                  <li key={p.id}>
                    <span className="pair-head" style={{ fontFamily: `'${p.heading}', var(--font-sans)` }}>
                      {p.heading}
                    </span>
                    <span className="muted small">
                      + {p.body} · {p.mood.join(", ")}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <Spinner />
            )}
          </Card>
        </aside>
      </div>
      {detail && (
        <Drawer title="Asset" onClose={() => setDetail(null)}>
          <AssetDetail assetId={detail} onChanged={() => brandAssets.reload()} />
        </Drawer>
      )}
    </div>
  );
}
