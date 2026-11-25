import { useCallback, useEffect, useState } from "react";
import { CostDialog, ToastStack } from "./components/ui";
import AssetLibrary from "./pages/AssetLibrary";
import BrandStudio from "./pages/BrandStudio";
import Dashboard from "./pages/Dashboard";
import ImageStudio from "./pages/ImageStudio";
import Settings from "./pages/Settings";
import VideoStudio from "./pages/VideoStudio";
import WorkflowStudio from "./pages/WorkflowStudio";
import { CostProvider, JobsProvider, ToastProvider, useJobs, useJobsContext } from "./state";

const ROUTES = [
  { id: "dashboard", label: "Dashboard", short: "Start", icon: "◧" },
  { id: "images", label: "Image Studio", short: "Bild", icon: "▣" },
  { id: "videos", label: "Video Studio", short: "Video", icon: "▶" },
  { id: "brand", label: "Brand Studio", short: "Brand", icon: "◆" },
  { id: "workflows", label: "Workflows", short: "Flows", icon: "⇉" },
  { id: "assets", label: "Asset Library", short: "Assets", icon: "▦" },
  { id: "settings", label: "Settings", short: "Setup", icon: "⚙" },
] as const;

type Route = (typeof ROUTES)[number]["id"];
const THEME_KEY = "acs-theme";

function readRoute(): Route {
  const id = window.location.hash.replace(/^#\/?/, "").split("?")[0];
  return (ROUTES.find((r) => r.id === id)?.id ?? "dashboard") as Route;
}

function readTheme(): "dark" | "light" {
  try {
    const t = localStorage.getItem(THEME_KEY);
    if (t === "light" || t === "dark") return t;
  } catch {
    /* storage unavailable */
  }
  return "dark";
}

function LiveIndicator() {
  const { live } = useJobsContext();
  const active = useJobs((j) => j.status === "running" || j.status === "queued" || j.status === "retrying");
  return (
    <div className="live">
      <span className={`live-dot ${live}`} aria-hidden />
      <span className="small">{live === "sse" ? "Live" : live === "polling" ? "Polling" : "Verbinde …"}</span>
      {active.length > 0 && <span className="live-count" title="aktive Jobs">{active.length}</span>}
    </div>
  );
}

function Shell() {
  const [route, setRoute] = useState<Route>(readRoute);
  const [theme, setThemeState] = useState<"dark" | "light">(readTheme);

  useEffect(() => {
    const onHash = () => setRoute(readRoute());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const setTheme = useCallback((t: "dark" | "light") => {
    setThemeState(t);
    try {
      localStorage.setItem(THEME_KEY, t);
    } catch {
      /* ignore */
    }
  }, []);

  const navigate = useCallback((r: string) => {
    window.location.hash = `#/${r}`;
  }, []);

  useEffect(() => {
    const label = ROUTES.find((r) => r.id === route)?.label ?? "";
    document.title = `${label} · AI Creative Studio`;
    window.scrollTo(0, 0);
  }, [route]);

  return (
    <div className="app">
      <a className="skip" href="#main">
        Zum Inhalt springen
      </a>
      <nav className="sidebar" aria-label="Hauptnavigation">
        <div className="brand">
          <img src="/favicon.svg" alt="" width={28} height={28} />
          <span>
            AI Creative <strong>Studio</strong>
          </span>
        </div>
        <ul>
          {ROUTES.map((r) => (
            <li key={r.id}>
              <a href={`#/${r.id}`} className={route === r.id ? "active" : ""} aria-current={route === r.id ? "page" : undefined}>
                <span className="nav-icon" aria-hidden>
                  {r.icon}
                </span>
                <span className="nav-label">{r.label}</span>
                <span className="nav-short" aria-hidden>
                  {r.short}
                </span>
              </a>
            </li>
          ))}
        </ul>
        <div className="sidebar-foot">
          <LiveIndicator />
          <button type="button" className="icon-btn" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} aria-label="Farbschema wechseln" title="Farbschema wechseln">
            {theme === "dark" ? "☀" : "☾"}
          </button>
        </div>
      </nav>
      <main id="main" className="main">
        {route === "dashboard" && <Dashboard navigate={navigate} />}
        {route === "images" && <ImageStudio />}
        {route === "videos" && <VideoStudio />}
        {route === "brand" && <BrandStudio />}
        {route === "workflows" && <WorkflowStudio />}
        {route === "assets" && <AssetLibrary />}
        {route === "settings" && <Settings theme={theme} setTheme={setTheme} />}
      </main>
      <CostDialog />
      <ToastStack />
    </div>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <CostProvider>
        <JobsProvider>
          <Shell />
        </JobsProvider>
      </CostProvider>
    </ToastProvider>
  );
}
