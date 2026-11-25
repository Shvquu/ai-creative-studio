import { useMemo, useState } from "react";
import type { Asset, CatalogModel, Job, Presets } from "../api";
import { AssetPicker, Badge, Button, Card, Drawer, EstimatePanel, Field, JobList, JobResult, PageHeader, Tabs } from "../components/ui";
import { useApi, useJob, useJobs, useSubmit } from "../state";
import { AssetDetail } from "./AssetLibrary";

export function ModelInfo({ model }: { model: CatalogModel | undefined }) {
  if (!model) return <small className="muted">Automatische Auswahl nach Hardwareprofil und installierten Modellen.</small>;
  return (
    <div className="model-info">
      <div className="row gap-s wrap">
        {model.installed === true && <Badge tone="ok">installiert</Badge>}
        {model.installed === false && <Badge tone="warn">nicht installiert</Badge>}
        {model.installed === null && <Badge>Status unbekannt (ComfyUI offline)</Badge>}
        <Badge tone={model.fits_hardware ? "ok" : "err"} title={model.hardware_note}>
          {model.fits_hardware ? "passt zur Hardware" : "Hardware zu schwach"}
        </Badge>
        <Badge tone={model.commercial_use === true ? "ok" : model.commercial_use === "restricted" ? "warn" : "err"} title={model.license_note ?? model.license}>
          {model.license}
        </Badge>
        <Badge>{model.size_gb} GB</Badge>
      </div>
      <small className="muted">{model.hardware_note}</small>
      {model.installed === false && (
        <code className="cmd">python scripts/models/download_models.py --model {model.id}</code>
      )}
    </div>
  );
}

type Mode = "generate" | "edit";
type EditOp = "edit" | "upscale" | "remove_background" | "text_overlay";

export default function ImageStudio() {
  const [mode, setMode] = useState<Mode>("generate");
  const presets = useApi<Presets>("/api/presets");
  const models = useApi<{ catalog: CatalogModel[] }>("/api/models");
  const submit = useSubmit();
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useJob(jobId);
  const history = useJobs((j: Job) => j.type.startsWith("image."));
  const [detail, setDetail] = useState<Asset | null>(null);

  // generate form
  const [prompt, setPrompt] = useState("");
  const [negative, setNegative] = useState("");
  const [style, setStyle] = useState("photorealistic");
  const [model, setModel] = useState("");
  const [provider, setProvider] = useState("comfyui");
  const [sizeMode, setSizeMode] = useState<"aspect" | "custom">("aspect");
  const [aspect, setAspect] = useState("1:1");
  const [width, setWidth] = useState(1024);
  const [height, setHeight] = useState(1024);
  const [seed, setSeed] = useState("");
  const [steps, setSteps] = useState("");
  const [cfg, setCfg] = useState("");
  const [batch, setBatch] = useState(1);
  const [project, setProject] = useState("");

  const imageModels = useMemo(() => (models.data?.catalog ?? []).filter((m) => m.type === "image"), [models.data]);
  const selectedModel = imageModels.find((m) => m.id === model);

  const params = useMemo(() => {
    const p: Record<string, unknown> = { prompt: prompt || "…", provider, batch_size: batch };
    if (negative) p.negative_prompt = negative;
    if (style) p.style = style;
    if (model && provider !== "mock") p.model = model;
    if (sizeMode === "aspect") p.aspect_ratio = aspect;
    else {
      p.width = width;
      p.height = height;
    }
    if (seed !== "") p.seed = Number(seed);
    if (steps !== "") p.steps = Number(steps);
    if (cfg !== "") p.cfg = Number(cfg);
    if (project) p.project = project;
    return p;
  }, [prompt, negative, style, model, provider, sizeMode, aspect, width, height, seed, steps, cfg, batch, project]);

  const generate = async (e: React.FormEvent) => {
    e.preventDefault();
    const job = await submit("/api/images/generate", { ...params, prompt });
    if (job) setJobId(job.id);
  };

  // edit form
  const [source, setSource] = useState<string | null>(null);
  const [op, setOp] = useState<EditOp>("edit");
  const [editPrompt, setEditPrompt] = useState("");
  const [strength, setStrength] = useState(0.55);
  const [scale, setScale] = useState(2);
  const [method, setMethod] = useState("auto");
  const [title, setTitle] = useState("");
  const [subtitle, setSubtitle] = useState("");
  const [position, setPosition] = useState("bottom");
  const [accent, setAccent] = useState("#FACC15");
  const [editProvider, setEditProvider] = useState("comfyui");

  const runEdit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!source) return;
    let body: Record<string, unknown> = { source };
    if (op === "edit") body = { ...body, prompt: editPrompt, strength, provider: editProvider };
    if (op === "upscale") body = { ...body, scale, method, provider: editProvider };
    if (op === "text_overlay") body = { ...body, title, subtitle: subtitle || undefined, position, accent };
    const job = await submit(`/api/images/${op}`, body);
    if (job) setJobId(job.id);
  };

  const styles = presets.data?.styles ?? {};
  const aspects = presets.data?.aspect_ratios ?? ["1:1", "16:9", "9:16"];

  return (
    <div className="page">
      <PageHeader title="Image Studio" description="Bilder generieren, variieren und nachbearbeiten – lokal mit ComfyUI." />
      <Tabs
        value={mode}
        onChange={setMode}
        tabs={[
          { id: "generate", label: "Generieren" },
          { id: "edit", label: "Bearbeiten" },
        ]}
      />
      <div className="studio">
        <div className="studio-main">
          {mode === "generate" ? (
            <Card title="Text zu Bild">
              <form className="form" onSubmit={generate}>
                <Field label="Prompt" wide>
                  {(id) => <textarea id={id} className="input" rows={4} required value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="z. B. eine Keramiktasse auf Leinen, Morgenlicht, Nahaufnahme" />}
                </Field>
                <Field label="Negativ-Prompt" wide hint="Wird bei FLUX/Z-Image ignoriert.">
                  {(id) => <input id={id} className="input" value={negative} onChange={(e) => setNegative(e.target.value)} placeholder="unscharf, Text, Wasserzeichen" />}
                </Field>
                <Field label="Stil">
                  {(id) => (
                    <select id={id} className="input" value={style} onChange={(e) => setStyle(e.target.value)}>
                      <option value="">– ohne –</option>
                      {Object.entries(styles).map(([k, v]) => (
                        <option key={k} value={k}>
                          {v}
                        </option>
                      ))}
                    </select>
                  )}
                </Field>
                <Field label="Provider">
                  {(id) => (
                    <select id={id} className="input" value={provider} onChange={(e) => setProvider(e.target.value)}>
                      <option value="comfyui">ComfyUI (lokal)</option>
                      <option value="mock">Mock – Testmodus (keine KI)</option>
                    </select>
                  )}
                </Field>
                <Field label="Modell" wide>
                  {(id) => (
                    <>
                      <select id={id} className="input" value={model} onChange={(e) => setModel(e.target.value)} disabled={provider === "mock"}>
                        <option value="">Automatisch (nach Hardware)</option>
                        {imageModels.map((m) => (
                          <option key={m.id} value={m.id}>
                            {m.name}
                            {m.installed === false ? " – nicht installiert" : ""}
                            {!m.fits_hardware ? " – Hardware zu schwach" : ""}
                          </option>
                        ))}
                      </select>
                      {provider !== "mock" && <ModelInfo model={selectedModel} />}
                    </>
                  )}
                </Field>
                <Field label="Größe">
                  {(id) => (
                    <select id={id} className="input" value={sizeMode} onChange={(e) => setSizeMode(e.target.value as "aspect" | "custom")}>
                      <option value="aspect">Seitenverhältnis</option>
                      <option value="custom">Eigene Auflösung</option>
                    </select>
                  )}
                </Field>
                {sizeMode === "aspect" ? (
                  <Field label="Seitenverhältnis">
                    {(id) => (
                      <select id={id} className="input" value={aspect} onChange={(e) => setAspect(e.target.value)}>
                        {aspects.map((a) => (
                          <option key={a}>{a}</option>
                        ))}
                      </select>
                    )}
                  </Field>
                ) : (
                  <div className="row gap-s">
                    <Field label="Breite">{(id) => <input id={id} className="input" type="number" min={64} max={4096} step={8} value={width} onChange={(e) => setWidth(Number(e.target.value))} />}</Field>
                    <Field label="Höhe">{(id) => <input id={id} className="input" type="number" min={64} max={4096} step={8} value={height} onChange={(e) => setHeight(Number(e.target.value))} />}</Field>
                  </div>
                )}
                <Field label="Seed" hint="leer = zufällig (wird gespeichert)">
                  {(id) => <input id={id} className="input" type="number" min={0} value={seed} onChange={(e) => setSeed(e.target.value)} />}
                </Field>
                <Field label="Steps" hint="leer = Modellstandard">
                  {(id) => <input id={id} className="input" type="number" min={1} max={150} value={steps} onChange={(e) => setSteps(e.target.value)} />}
                </Field>
                <Field label="CFG" hint="leer = Modellstandard">
                  {(id) => <input id={id} className="input" type="number" min={0} max={30} step={0.5} value={cfg} onChange={(e) => setCfg(e.target.value)} />}
                </Field>
                <Field label={`Varianten: ${batch}`}>
                  {(id) => <input id={id} type="range" min={1} max={8} value={batch} onChange={(e) => setBatch(Number(e.target.value))} />}
                </Field>
                <Field label="Projekt (optional)">{(id) => <input id={id} className="input" value={project} onChange={(e) => setProject(e.target.value)} />}</Field>
                <div className="form-actions">
                  <Button variant="primary" type="submit" disabled={!prompt.trim()}>
                    Generieren
                  </Button>
                </div>
              </form>
            </Card>
          ) : (
            <Card title="Bild bearbeiten">
              <form className="form" onSubmit={runEdit}>
                <div className="field-wide">
                  <AssetPicker kind="image" value={source} onChange={setSource} label="Ausgangsbild" />
                </div>
                <Field label="Operation">
                  {(id) => (
                    <select id={id} className="input" value={op} onChange={(e) => setOp(e.target.value as EditOp)}>
                      <option value="edit">Variation (Image-to-Image)</option>
                      <option value="upscale">Hochskalieren</option>
                      <option value="remove_background">Hintergrund entfernen (rembg)</option>
                      <option value="text_overlay">Text-Overlay</option>
                    </select>
                  )}
                </Field>
                {(op === "edit" || op === "upscale") && (
                  <Field label="Provider">
                    {(id) => (
                      <select id={id} className="input" value={editProvider} onChange={(e) => setEditProvider(e.target.value)}>
                        <option value="comfyui">ComfyUI (lokal)</option>
                        <option value="mock">Mock – Testmodus</option>
                      </select>
                    )}
                  </Field>
                )}
                {op === "edit" && (
                  <>
                    <Field label="Gewünschte Änderung" wide>
                      {(id) => <textarea id={id} className="input" rows={3} value={editPrompt} onChange={(e) => setEditPrompt(e.target.value)} />}
                    </Field>
                    <Field label={`Stärke: ${strength.toFixed(2)}`} hint="niedrig = nah am Original">
                      {(id) => <input id={id} type="range" min={0.05} max={1} step={0.05} value={strength} onChange={(e) => setStrength(Number(e.target.value))} />}
                    </Field>
                  </>
                )}
                {op === "upscale" && (
                  <>
                    <Field label="Faktor">
                      {(id) => (
                        <select id={id} className="input" value={scale} onChange={(e) => setScale(Number(e.target.value))}>
                          {[1.5, 2, 3, 4].map((s) => (
                            <option key={s} value={s}>
                              {s}×
                            </option>
                          ))}
                        </select>
                      )}
                    </Field>
                    <Field label="Methode" hint="Automatisch: Real-ESRGAN falls installiert, sonst Lanczos">
                      {(id) => (
                        <select id={id} className="input" value={method} onChange={(e) => setMethod(e.target.value)}>
                          <option value="auto">Automatisch</option>
                          <option value="model">KI-Modell (Real-ESRGAN)</option>
                          <option value="lanczos">Lanczos (ohne KI)</option>
                        </select>
                      )}
                    </Field>
                  </>
                )}
                {op === "text_overlay" && (
                  <>
                    <Field label="Titel">{(id) => <input id={id} className="input" required value={title} onChange={(e) => setTitle(e.target.value)} />}</Field>
                    <Field label="Untertitel">{(id) => <input id={id} className="input" value={subtitle} onChange={(e) => setSubtitle(e.target.value)} />}</Field>
                    <Field label="Position">
                      {(id) => (
                        <select id={id} className="input" value={position} onChange={(e) => setPosition(e.target.value)}>
                          {["bottom", "top", "center", "left", "right"].map((p) => (
                            <option key={p}>{p}</option>
                          ))}
                        </select>
                      )}
                    </Field>
                    <Field label="Akzentfarbe">{(id) => <input id={id} className="input input-color" type="color" value={accent} onChange={(e) => setAccent(e.target.value.toUpperCase())} />}</Field>
                  </>
                )}
                <div className="form-actions">
                  <Button variant="primary" type="submit" disabled={!source || (op === "text_overlay" && !title)}>
                    Ausführen
                  </Button>
                </div>
              </form>
            </Card>
          )}
          {job && (
            <Card title="Ergebnis">
              <JobResult job={job} onAssetClick={setDetail} />
            </Card>
          )}
        </div>
        <aside className="studio-side">
          {mode === "generate" && <EstimatePanel type="image.generate" params={params} />}
          <Card title="Verlauf" subtitle="Bild-Jobs">
            <JobList jobs={history} limit={12} onSelect={(j) => setJobId(j.id)} empty="Noch keine Bild-Jobs." />
          </Card>
        </aside>
      </div>
      {detail && (
        <Drawer title="Asset" onClose={() => setDetail(null)}>
          <AssetDetail assetId={detail.id} onChanged={() => undefined} />
        </Drawer>
      )}
    </div>
  );
}
