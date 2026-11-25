import { useMemo, useState } from "react";
import type { Asset, Capabilities, CatalogModel, Job, Presets } from "../api";
import { AssetPicker, Button, Card, Drawer, EstimatePanel, Field, JobList, JobResult, PageHeader, Tabs } from "../components/ui";
import { useApi, useJob, useJobs, useSubmit } from "../state";
import { AssetDetail } from "./AssetLibrary";
import { ModelInfo } from "./ImageStudio";

interface Scene {
  prompt: string;
  duration_s: number;
  camera: string;
  caption: string;
}

const emptyScene = (): Scene => ({ prompt: "", duration_s: 3, camera: "dolly-in", caption: "" });
const isRenderJob = (j: Job) =>
  j.type.startsWith("video.") || j.type.startsWith("process.") || j.type.startsWith("motion.") || j.type.startsWith("render3d.") ||
  (j.type === "workflow.run" && String(j.params.workflow_id ?? "").startsWith("videos/"));

export default function VideoStudio() {
  const [mode, setMode] = useState<"clip" | "storyboard">("clip");
  const caps = useApi<Capabilities>("/api/system/capabilities");
  const presets = useApi<Presets>("/api/presets");
  const models = useApi<{ catalog: CatalogModel[] }>("/api/models");
  const submit = useSubmit();
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useJob(jobId);
  const queue = useJobs(isRenderJob);
  const [detail, setDetail] = useState<Asset | null>(null);

  const [prompt, setPrompt] = useState("");
  const [model, setModel] = useState("");
  const [provider, setProvider] = useState("comfyui");
  const [duration, setDuration] = useState(3);
  const [aspect, setAspect] = useState("16:9");
  const [fps, setFps] = useState("");
  const [camera, setCamera] = useState("dolly-in");
  const [image, setImage] = useState<string | null>(null);

  const noVideo = caps.data ? !caps.data.ai_video : false;
  const videoModels = useMemo(() => (models.data?.catalog ?? []).filter((m) => m.type === "video"), [models.data]);
  const cameraMoves = presets.data?.camera_moves ?? {};

  const params = useMemo(() => {
    const p: Record<string, unknown> = { prompt: prompt || "…", provider, duration_s: duration, aspect_ratio: aspect, camera_move: camera };
    if (model && provider !== "mock") p.model = model;
    if (fps) p.fps = Number(fps);
    if (image) p.image = image;
    return p;
  }, [prompt, provider, duration, aspect, camera, model, fps, image]);

  const generate = async (e: React.FormEvent) => {
    e.preventDefault();
    const j = await submit(image ? "/api/videos/image_to_video" : "/api/videos/generate", { ...params, prompt });
    if (j) setJobId(j.id);
  };

  const kenBurns = async () => {
    const inputs: Record<string, unknown> = { aspect_ratio: aspect, duration_s: Math.max(2, duration) };
    if (image) inputs.images = [image];
    else inputs.prompt = prompt;
    if (provider === "mock") inputs.image_provider = "mock";
    const j = await submit("/api/workflows/videos/kenburns-slideshow/run", { inputs });
    if (j) setJobId(j.id);
  };

  // storyboard
  const [scenes, setScenes] = useState<Scene[]>([emptyScene(), emptyScene()]);
  const [sbStyle, setSbStyle] = useState("cinematic");
  const [sbAspect, setSbAspect] = useState("16:9");
  const [transition, setTransition] = useState("fade");
  const [music, setMusic] = useState<string | null>(null);
  const [subtitles, setSubtitles] = useState(true);
  const [title, setTitle] = useState("");
  const [sbProvider, setSbProvider] = useState("");

  const updateScene = (i: number, patch: Partial<Scene>) => setScenes((s) => s.map((sc, k) => (k === i ? { ...sc, ...patch } : sc)));
  const moveScene = (i: number, d: number) =>
    setScenes((s) => {
      const next = [...s];
      const j = i + d;
      if (j < 0 || j >= next.length) return s;
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });

  const runStoryboard = async (e: React.FormEvent) => {
    e.preventDefault();
    const inputs: Record<string, unknown> = {
      scenes: scenes.filter((s) => s.prompt.trim()).map((s) => ({ ...s, caption: s.caption || undefined })),
      style: sbStyle,
      aspect_ratio: sbAspect,
      transition,
      subtitles,
    };
    if (music) inputs.music = music;
    if (title) inputs.title = title;
    if (sbProvider === "mock") {
      inputs.image_provider = "mock";
      inputs.video_provider = "mock";
    }
    const j = await submit("/api/workflows/videos/storyboard-to-video/run", { inputs });
    if (j) setJobId(j.id);
  };

  return (
    <div className="page">
      <PageHeader title="Video Studio" description="Text-to-Video, Image-to-Video und Storyboards – mit automatischem Fallback ohne GPU." />
      {noVideo && (
        <div className="note note-warn" role="status">
          <strong>Keine GPU-Videogenerierung verfügbar</strong> (Profil {caps.data?.profile}). Wan-Modelle benötigen eine GPU. Alternative: das{" "}
          <em>Ken-Burns-Video</em> erzeugt aus Standbildern Kamerafahrten mit Übergängen – läuft auch auf der CPU. Storyboards fallen automatisch darauf zurück.
        </div>
      )}
      <Tabs
        value={mode}
        onChange={setMode}
        tabs={[
          { id: "clip", label: "Einzelner Clip" },
          { id: "storyboard", label: "Storyboard" },
        ]}
      />
      <div className="studio">
        <div className="studio-main">
          {mode === "clip" ? (
            <Card title={image ? "Bild zu Video" : "Text zu Video"}>
              <form className="form" onSubmit={generate}>
                <Field label="Beschreibung / Bewegung" wide>
                  {(id) => <textarea id={id} className="input" rows={3} required value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="z. B. ein Fuchs läuft durch verschneiten Wald, Morgenlicht" />}
                </Field>
                <div className="field-wide">
                  <AssetPicker kind="image" value={image} onChange={setImage} label="Startbild (optional → Image-to-Video)" />
                </div>
                <Field label="Provider">
                  {(id) => (
                    <select id={id} className="input" value={provider} onChange={(e) => setProvider(e.target.value)}>
                      <option value="comfyui">ComfyUI (lokal)</option>
                      <option value="mock">Mock – Testmodus (keine KI)</option>
                    </select>
                  )}
                </Field>
                <Field label="Kamera">
                  {(id) => (
                    <select id={id} className="input" value={camera} onChange={(e) => setCamera(e.target.value)}>
                      {Object.keys(cameraMoves).map((c) => (
                        <option key={c} value={c}>
                          {c}
                        </option>
                      ))}
                    </select>
                  )}
                </Field>
                <Field label="Modell" wide>
                  {(id) => (
                    <>
                      <select id={id} className="input" value={model} onChange={(e) => setModel(e.target.value)} disabled={provider === "mock"}>
                        <option value="">Automatisch (nach Hardware)</option>
                        {videoModels.map((m) => (
                          <option key={m.id} value={m.id}>
                            {m.name}
                            {m.installed === false ? " – nicht installiert" : ""}
                            {!m.fits_hardware ? " – Hardware zu schwach" : ""}
                          </option>
                        ))}
                      </select>
                      {provider !== "mock" && <ModelInfo model={videoModels.find((m) => m.id === model)} />}
                    </>
                  )}
                </Field>
                <Field label={`Dauer: ${duration} s`} hint="Wan erzeugt 2–5 s pro Clip; längere Videos über Storyboards">
                  {(id) => <input id={id} type="range" min={1} max={8} step={0.5} value={duration} onChange={(e) => setDuration(Number(e.target.value))} />}
                </Field>
                <Field label="Seitenverhältnis">
                  {(id) => (
                    <select id={id} className="input" value={aspect} onChange={(e) => setAspect(e.target.value)}>
                      {["16:9", "9:16", "1:1"].map((a) => (
                        <option key={a}>{a}</option>
                      ))}
                    </select>
                  )}
                </Field>
                <Field label="FPS" hint="leer = Modellstandard (16/24)">
                  {(id) => <input id={id} className="input" type="number" min={1} max={60} value={fps} onChange={(e) => setFps(e.target.value)} />}
                </Field>
                <div className="form-actions">
                  <Button variant="primary" type="submit" disabled={!prompt.trim() || (noVideo && provider !== "mock")}>
                    Video generieren
                  </Button>
                  <Button onClick={() => void kenBurns()} disabled={!prompt.trim() && !image}>
                    Ken-Burns-Video (CPU)
                  </Button>
                </div>
              </form>
            </Card>
          ) : (
            <Card title="Storyboard" subtitle="Szene für Szene: Referenzbild → Animation → Schnitt mit Übergängen, Musik und Untertiteln.">
              <form className="form" onSubmit={runStoryboard}>
                <ol className="scenes field-wide">
                  {scenes.map((s, i) => (
                    <li key={i} className="scene">
                      <div className="scene-head">
                        <strong>Szene {i + 1}</strong>
                        <div className="row gap-xs">
                          <button type="button" className="icon-btn" aria-label="Nach oben" onClick={() => moveScene(i, -1)} disabled={i === 0}>
                            ↑
                          </button>
                          <button type="button" className="icon-btn" aria-label="Nach unten" onClick={() => moveScene(i, 1)} disabled={i === scenes.length - 1}>
                            ↓
                          </button>
                          <button type="button" className="icon-btn" aria-label="Szene entfernen" onClick={() => setScenes((sc) => sc.filter((_, k) => k !== i))} disabled={scenes.length === 1}>
                            ✕
                          </button>
                        </div>
                      </div>
                      <textarea className="input" rows={2} aria-label={`Szene ${i + 1} Beschreibung`} placeholder="Was passiert in dieser Szene?" value={s.prompt} onChange={(e) => updateScene(i, { prompt: e.target.value })} />
                      <div className="scene-grid">
                        <label>
                          Dauer (s)
                          <input className="input" type="number" min={1} max={10} step={0.5} value={s.duration_s} onChange={(e) => updateScene(i, { duration_s: Number(e.target.value) })} />
                        </label>
                        <label>
                          Kamera
                          <select className="input" value={s.camera} onChange={(e) => updateScene(i, { camera: e.target.value })}>
                            {Object.keys(cameraMoves).map((c) => (
                              <option key={c}>{c}</option>
                            ))}
                          </select>
                        </label>
                        <label className="span-2">
                          Untertitel
                          <input className="input" value={s.caption} onChange={(e) => updateScene(i, { caption: e.target.value })} placeholder="optional" />
                        </label>
                      </div>
                    </li>
                  ))}
                </ol>
                <div className="field-wide">
                  <Button size="s" onClick={() => setScenes((s) => [...s, emptyScene()])}>
                    + Szene hinzufügen
                  </Button>
                </div>
                <Field label="Stil">
                  {(id) => (
                    <select id={id} className="input" value={sbStyle} onChange={(e) => setSbStyle(e.target.value)}>
                      {["cinematic", "photorealistic", "product", "illustration", "anime", "3d-render"].map((s) => (
                        <option key={s}>{s}</option>
                      ))}
                    </select>
                  )}
                </Field>
                <Field label="Format">
                  {(id) => (
                    <select id={id} className="input" value={sbAspect} onChange={(e) => setSbAspect(e.target.value)}>
                      {["16:9", "9:16", "1:1"].map((a) => (
                        <option key={a}>{a}</option>
                      ))}
                    </select>
                  )}
                </Field>
                <Field label="Übergang">
                  {(id) => (
                    <select id={id} className="input" value={transition} onChange={(e) => setTransition(e.target.value)}>
                      {["none", "fade", "dissolve", "wipeleft", "slideleft", "fadeblack", "circleopen", "smoothleft"].map((t) => (
                        <option key={t}>{t}</option>
                      ))}
                    </select>
                  )}
                </Field>
                <Field label="Provider">
                  {(id) => (
                    <select id={id} className="input" value={sbProvider} onChange={(e) => setSbProvider(e.target.value)}>
                      <option value="">Standard (ComfyUI)</option>
                      <option value="mock">Mock – Testmodus</option>
                    </select>
                  )}
                </Field>
                <Field label="Titel / Dateiname">{(id) => <input id={id} className="input" value={title} onChange={(e) => setTitle(e.target.value)} />}</Field>
                <label className="check">
                  <input type="checkbox" checked={subtitles} onChange={(e) => setSubtitles(e.target.checked)} /> Untertitel einbrennen
                </label>
                <div className="field-wide">
                  <AssetPicker kind="audio" value={music} onChange={setMusic} label="Musik (optional)" />
                </div>
                <div className="form-actions">
                  <Button variant="primary" type="submit" disabled={!scenes.some((s) => s.prompt.trim())}>
                    Storyboard rendern
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
          {mode === "clip" && <EstimatePanel type={image ? "video.image_to_video" : "video.generate"} params={params} />}
          <Card title="Render-Queue" subtitle="Video-, Schnitt- und Render-Jobs">
            <JobList jobs={queue} limit={12} onSelect={(j) => setJobId(j.id)} empty="Keine Video-Jobs." />
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
