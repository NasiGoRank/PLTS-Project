import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { getEnergySeries, getRevenueSeries } from "./chart_data.js";
import "./styles.css";

const TABS = ["Overview", "Energy", "Revenue"];
const OPENFREEMAP_STYLE = "https://tiles.openfreemap.org/styles/liberty";
const AUTH_STORAGE_KEY = "plts-monitoring.supabase-session";
const UI_STATE_STORAGE_KEY = "plts-monitoring.ui-state";

function apiBase() {
  const configuredApiBase = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");
  return configuredApiBase || (import.meta.env.DEV ? "http://localhost:8000" : "");
}

function authConfig() {
  return {
    url: (import.meta.env.VITE_SUPABASE_URL || "").replace(/\/$/, ""),
    key: import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY || "",
  };
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 10_000) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } catch (err) {
    if (err?.name === "AbortError") throw new Error(`Request timed out after ${Math.round(timeoutMs / 1000)}s`);
    throw err;
  } finally {
    window.clearTimeout(timer);
  }
}

function normalizeSession(payload) {
  if (!payload?.access_token || !payload?.refresh_token) return null;
  const expiresAt = payload.expires_at || Math.floor(Date.now() / 1000) + Number(payload.expires_in || 3600);
  return {
    access_token: payload.access_token,
    refresh_token: payload.refresh_token,
    expires_at: expiresAt,
    user: payload.user || null,
  };
}

function readStoredSession() {
  try {
    return normalizeSession(JSON.parse(window.localStorage.getItem(AUTH_STORAGE_KEY) || "null"));
  } catch {
    return null;
  }
}

function storeSession(session) {
  if (!session) {
    window.localStorage.removeItem(AUTH_STORAGE_KEY);
    return;
  }
  window.localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(session));
}

function readUiState() {
  try {
    const stored = JSON.parse(window.localStorage.getItem(UI_STATE_STORAGE_KEY) || "{}");
    return {
      activeTab: TABS.includes(stored.activeTab) ? stored.activeTab : "Overview",
      selectedId: typeof stored.selectedId === "string" ? stored.selectedId : null,
    };
  } catch {
    return { activeTab: "Overview", selectedId: null };
  }
}

function writeUiState(updates) {
  try {
    window.localStorage.setItem(UI_STATE_STORAGE_KEY, JSON.stringify({
      ...readUiState(),
      ...updates,
    }));
  } catch {
    // Ignore storage failures; the dashboard should keep working.
  }
}

async function authRequest(path, body) {
  const { url, key } = authConfig();
  if (!url || !key) throw new Error("Supabase Auth is not configured");
  const response = await fetchWithTimeout(`${url}${path}`, {
    method: "POST",
    headers: {
      apikey: key,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error_description || payload.msg || payload.message || `Supabase Auth returned ${response.status}`);
  }
  return payload;
}

async function signInWithPassword(email, password) {
  const payload = await authRequest("/auth/v1/token?grant_type=password", { email, password });
  const session = normalizeSession(payload);
  if (!session) throw new Error("Supabase Auth did not return a usable session");
  storeSession(session);
  return session;
}

async function refreshAuthSession(session) {
  if (!session?.refresh_token) return null;
  const payload = await authRequest("/auth/v1/token?grant_type=refresh_token", {
    refresh_token: session.refresh_token,
  });
  const nextSession = normalizeSession(payload);
  storeSession(nextSession);
  return nextSession;
}

function useAuthSession() {
  const [session, setSession] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const boot = async () => {
      const stored = readStoredSession();
      if (!stored) {
        if (!cancelled) setLoading(false);
        return;
      }
      const expiresSoon = Number(stored.expires_at || 0) * 1000 < Date.now() + 60_000;
      try {
        const usableSession = expiresSoon ? await refreshAuthSession(stored) : stored;
        if (!cancelled) {
          setSession(usableSession);
          setError(null);
        }
      } catch (err) {
        storeSession(null);
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    boot();
    return () => {
      cancelled = true;
    };
  }, []);

  const signIn = useCallback(async (email, password) => {
    setError(null);
    const nextSession = await signInWithPassword(email, password);
    setSession(nextSession);
    return nextSession;
  }, []);

  const signOut = useCallback(() => {
    storeSession(null);
    setSession(null);
    setError(null);
  }, []);

  return { session, loading, error, signIn, signOut };
}

function formatNumber(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(Number(value));
}

function money(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "Tidak tersedia";
  return new Intl.NumberFormat("id-ID", {
    style: "currency",
    currency: "IDR",
    maximumFractionDigits: 0,
  }).format(Number(value));
}

function compactMoney(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  if (Math.abs(number) >= 1_000_000_000) return `${formatNumber(number / 1_000_000_000, 2)}B`;
  if (Math.abs(number) >= 1_000_000) return `${formatNumber(number / 1_000_000, 2)}M`;
  if (Math.abs(number) >= 1_000) return `${formatNumber(number / 1_000, 1)}K`;
  return formatNumber(number, 0);
}

function userDisplayName(user) {
  const rawName = user?.user_metadata?.name || user?.user_metadata?.full_name || user?.email || "operator";
  return String(rawName).includes("@") ? String(rawName).split("@")[0] : String(rawName);
}

function toMwh(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number / 1000 : null;
}

function useMonitoringData(session, onUnauthorized) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const base = apiBase();
    const pollInterval = Math.max(15_000, Number(import.meta.env.VITE_POLL_INTERVAL_MS || 60_000));

    if (!base) {
      setError("VITE_API_URL is not configured for this deployment");
      return undefined;
    }

    const endpoint = `${base}/api/current`;
    const accessToken = session?.access_token;

    if (!accessToken) {
      setData(null);
      setError(null);
      return undefined;
    }

    const load = async () => {
      try {
        const response = await fetchWithTimeout(`${endpoint}?ts=${Date.now()}`, {
          cache: "no-store",
          headers: {
            Authorization: `Bearer ${accessToken}`,
          },
        }, 12_000);
        if (response.status === 401) {
          onUnauthorized?.();
          throw new Error("Session expired. Please sign in again.");
        }
        if (!response.ok) throw new Error(`Monitoring API returned ${response.status}`);
        const json = await response.json();
        if (!cancelled) {
          setData(json);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      }
    };

    load();
    const timer = window.setInterval(load, pollInterval);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [session?.access_token, onUnauthorized]);

  return { data, error };
}

function App() {
  const auth = useAuthSession();
  const [welcomeSessionId, setWelcomeSessionId] = useState(null);

  const handleSignIn = useCallback(async (email, password) => {
    const nextSession = await auth.signIn(email, password);
    setWelcomeSessionId(nextSession.user?.id || nextSession.user?.email || String(Date.now()));
    return nextSession;
  }, [auth]);

  const handleSignOut = useCallback(() => {
    setWelcomeSessionId(null);
    auth.signOut();
  }, [auth]);

  if (auth.loading) return <Shell><LoadingScreen /></Shell>;
  if (!auth.session) return <Shell><LoginPage onSignIn={handleSignIn} initialError={auth.error} /></Shell>;

  return (
    <Dashboard
      session={auth.session}
      onSignOut={handleSignOut}
      showWelcome={Boolean(welcomeSessionId)}
      onWelcomeClose={() => setWelcomeSessionId(null)}
    />
  );
}

function Dashboard({ session, onSignOut, showWelcome, onWelcomeClose }) {
  const { data, error } = useMonitoringData(session, onSignOut);
  const [activeTab, setActiveTab] = useState(() => readUiState().activeTab);
  const [selectedId, setSelectedId] = useState(() => readUiState().selectedId);
  const [sitesOpen, setSitesOpen] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [welcomeClosing, setWelcomeClosing] = useState(false);

  const sites = useMemo(() => {
    if (!data?.by_site) return [];
    return Object.entries(data.by_site).map(([key, site]) => ({ key, ...site }));
  }, [data]);

  const locations = useMemo(() => {
    return sites.flatMap((site) => (site.stations || []).map((station) => ({
      ...station,
      source: site.platform,
      site,
      uid: `${site.platform}-${station.station_id}`,
    })));
  }, [sites]);

  useEffect(() => {
    if (!locations.length) return;
    if (!selectedId || !locations.some((location) => location.uid === selectedId)) {
      const fallbackId = locations[0].uid;
      setSelectedId(fallbackId);
      writeUiState({ selectedId: fallbackId });
    }
  }, [locations, selectedId]);

  const selected = locations.find((location) => location.uid === selectedId) || locations[0];
  const fleet = useMemo(() => buildFleet(sites, locations), [sites, locations]);
  const selectSite = useCallback((uid) => {
    setSelectedId(uid);
    writeUiState({ selectedId: uid });
    setSitesOpen(false);
    setMobileMenuOpen(false);
  }, []);
  const selectTab = useCallback((tab) => {
    setActiveTab(tab);
    writeUiState({ activeTab: tab });
    setMobileMenuOpen(false);
  }, []);

  const closeWelcome = useCallback(() => {
    setWelcomeClosing(true);
    window.setTimeout(onWelcomeClose, 280);
  }, [onWelcomeClose]);

  useEffect(() => {
    if (!showWelcome) return undefined;
    setWelcomeClosing(false);
    const timer = window.setTimeout(closeWelcome, 4200);
    return () => window.clearTimeout(timer);
  }, [showWelcome, closeWelcome]);

  if (error && !data) return <Shell><StateCard title="Unable to load data" message={error} /></Shell>;
  if (!data) return <Shell><LoadingScreen /></Shell>;

  return (
    <Shell>
      <TopNav
        activeTab={activeTab}
        onSelectTab={selectTab}
        updatedAt={data.updated_at}
        userEmail={session.user?.email}
        onSignOut={onSignOut}
        sitesOpen={sitesOpen}
        setSitesOpen={setSitesOpen}
        mobileMenuOpen={mobileMenuOpen}
        setMobileMenuOpen={setMobileMenuOpen}
      />
      <SitesPanel open={sitesOpen} locations={locations} selectedId={selected?.uid} onClose={() => setSitesOpen(false)} onSelect={selectSite} />
      <MobileNavPanel open={mobileMenuOpen} activeTab={activeTab} onClose={() => setMobileMenuOpen(false)} onSelectTab={selectTab} />
      <main className="workspace">
        <HeroPanel fleet={fleet} selected={selected} />
        {activeTab === "Overview" && (
          <OverviewTab
            fleet={fleet}
            selected={selected}
            locations={locations}
            onSelect={selectSite}
          />
        )}
        {activeTab === "Energy" && <EnergyTab location={selected} fleet={fleet} />}
        {activeTab === "Revenue" && <RevenueTab location={selected} fleet={fleet} />}
      </main>
      {showWelcome && <WelcomeModal user={session.user} closing={welcomeClosing} onClose={closeWelcome} />}
    </Shell>
  );
}

function WelcomeModal({ user, closing, onClose }) {
  return (
    <section className={`welcome-toast surface ${closing ? "closing" : ""}`} role="status" aria-live="polite">
      <button type="button" aria-label="Dismiss welcome message" onClick={onClose}>×</button>
      <span className="eyebrow">Access granted</span>
      <h2>Welcome, {userDisplayName(user)}</h2>
      <p>Dashboard session is active.</p>
    </section>
  );
}

function LoginPage({ onSignIn, initialError }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(initialError || null);
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await onSignIn(email.trim(), password);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="login-page">
      <section className="login-card surface spotlight-card">
        <span className="eyebrow">Restricted console</span>
        <h1>Sign in to PLTS Monitor</h1>
        <p>Put your Email and Password below.</p>
        <form className="login-form" onSubmit={submit}>
          <label>
            <span>Email</span>
            <input
              type="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </label>
          <label>
            <span>Password</span>
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </label>
          {error && <div className="login-error">{error}</div>}
          <button type="submit" disabled={submitting}>
            {submitting ? "Signing in..." : "Sign in"}
          </button>
        </form>
      </section>
    </main>
  );
}

function buildFleet(sites, locations) {
  const overview = sites.map((site) => site.overview || {});
  return {
    stations: locations.length,
    platforms: sites.length,
    offline: locations.filter((item) => item.status === "offline").length,
    capacity: overview.reduce((sum, item) => sum + (Number(item.capacity_kwp) || 0), 0),
    current: overview.reduce((sum, item) => sum + (Number(item.current_power_kw) || 0), 0),
    daily: overview.reduce((sum, item) => sum + (Number(item.daily_energy_kwh) || 0), 0),
    monthly: overview.reduce((sum, item) => sum + (Number(item.monthly_energy_kwh) || 0), 0),
    yearly: overview.reduce((sum, item) => sum + (Number(item.yearly_energy_kwh) || 0), 0),
    total: overview.reduce((sum, item) => sum + (Number(item.cumulative_energy_kwh) || 0), 0),
    monthlyIncome: overview.reduce((sum, item) => sum + (Number(item.monthly_income) || 0), 0),
    yearlyIncome: overview.reduce((sum, item) => sum + (Number(item.yearly_income) || 0), 0),
    totalIncome: overview.reduce((sum, item) => sum + (Number(item.cumulative_income) || 0), 0),
  };
}

function Shell({ children }) {
  return (
    <div className="app-shell">
      <div className="ambient ambient-a" />
      <div className="ambient ambient-b" />
      <div className="ambient ambient-c" />
      <div className="noise-layer" />
      <div className="grid-layer" />
      <div className="app-frame">{children}</div>
    </div>
  );
}

function TopNav({ activeTab, onSelectTab, updatedAt, userEmail, onSignOut, sitesOpen, setSitesOpen, mobileMenuOpen, setMobileMenuOpen }) {
  const updated = updatedAt ? new Date(updatedAt).toLocaleString("en-GB", { hour12: false }) : "-";
  return (
    <nav className="top-nav surface">
      <button
        type="button"
        className="site-trigger"
        aria-label="Open PLTS sites panel"
        aria-expanded={sitesOpen}
        onClick={() => setSitesOpen(!sitesOpen)}
      >
        <SolarIcon />
        <span>Sites</span>
      </button>
      <div className="brand">
        <span className="status-dot" />
        <div>
          <strong>PLTS Monitor</strong>
          <span>Huawei + Kehua</span>
        </div>
      </div>
      <div className="nav-tabs" role="tablist" aria-label="Monitoring sections">
        {TABS.map((tab) => (
          <button
            key={tab}
            type="button"
            role="tab"
            aria-selected={activeTab === tab}
            className={activeTab === tab ? "active" : ""}
            onClick={() => onSelectTab(tab)}
          >
            {tab}
          </button>
        ))}
      </div>
      <div className="sync-pill">
        <span>Last sync</span>
        <strong>{updated}</strong>
      </div>
      <button type="button" className="logout-button" title={userEmail || "Signed in"} onClick={onSignOut}>
        Sign out
      </button>
      <button
        type="button"
        className="mobile-menu-trigger"
        aria-label="Open navigation menu"
        aria-expanded={mobileMenuOpen}
        onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
      >
        <span />
        <span />
      </button>
    </nav>
  );
}

function SolarIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 10.5h14" />
      <path d="M6.5 6.5h11l1.5 9h-14z" />
      <path d="M8.5 6.5l-.8 9" />
      <path d="M15.5 6.5l.8 9" />
      <path d="M12 6.5v9" />
      <path d="M4 18.5h16" />
    </svg>
  );
}

function SitesPanel({ open, locations, selectedId, onClose, onSelect }) {
  return (
    <>
      <button type="button" className={`panel-backdrop ${open ? "open" : ""}`} aria-label="Close sites panel" tabIndex={open ? 0 : -1} onClick={onClose} />
      <aside className={`sites-panel surface ${open ? "open" : ""}`} aria-hidden={!open} inert={open ? undefined : true}>
        <div className="slide-panel-head">
          <div>
            <span className="eyebrow">PLTS selector</span>
            <h2>Sites</h2>
          </div>
          <button type="button" className="panel-close" onClick={onClose}>Close</button>
        </div>
        <SitePanelList locations={locations} selectedId={selectedId} onSelect={onSelect} />
      </aside>
    </>
  );
}

function MobileNavPanel({ open, activeTab, onClose, onSelectTab }) {
  return (
    <>
      <button type="button" className={`panel-backdrop ${open ? "open" : ""}`} aria-label="Close navigation menu" tabIndex={open ? 0 : -1} onClick={onClose} />
      <aside className={`mobile-nav-panel surface ${open ? "open" : ""}`} aria-hidden={!open} inert={open ? undefined : true}>
        <div className="slide-panel-head">
          <div>
            <span className="eyebrow">Menu</span>
            <h2>Navigation</h2>
          </div>
          <button type="button" className="panel-close" onClick={onClose}>Close</button>
        </div>
        <div className="mobile-nav-actions">
          {TABS.map((tab) => (
            <button key={tab} type="button" className={activeTab === tab ? "active" : ""} onClick={() => onSelectTab(tab)}>{tab}</button>
          ))}
        </div>
      </aside>
    </>
  );
}

function SitePanelList({ locations, selectedId, onSelect }) {
  return (
    <div className="site-panel-list">
      {locations.map((location) => (
        <button key={location.uid} type="button" className={`site-panel-card ${selectedId === location.uid ? "active" : ""}`} onClick={() => onSelect(location.uid)}>
          <div className="site-panel-card-head">
            <span className={`status-dot ${location.status !== "normal" ? "muted" : ""}`} />
            <div>
              <strong>{location.name}</strong>
              <em>{location.source} · {location.station_id}</em>
            </div>
            <span className={`status-badge ${location.status === "normal" ? "online" : "offline"}`}>{location.status === "normal" ? "Online" : "Offline"}</span>
          </div>
          <div className="site-panel-metrics">
            <span><b>{formatNumber(location.capacity_kwp)}</b> kWp</span>
            <span><b>{formatNumber(location.current_power_kw)}</b> kW</span>
            <span><b>{formatNumber(location.monthly_energy_kwh, 0)}</b> kWh/bln</span>
          </div>
        </button>
      ))}
    </div>
  );
}

function HeroPanel({ fleet, selected }) {
  return (
    <header className="hero-grid">
      <section className="hero-copy surface spotlight-card">
        <p className="eyebrow">Unified production console</p>
        <h1>
          Monitoring PLTS
        </h1>
        <p className="hero-text">
          Integrated monitoring for Huawei FusionSolar and Kehua.
        </p>
        <div className="fleet-strip" aria-label="Fleet summary">
          <MiniMetric label="Sites" value={fleet.stations} />
          <MiniMetric label="Capacity" value={formatNumber(fleet.capacity)} unit="kWp" />
          <MiniMetric label="Now" value={formatNumber(fleet.current)} unit="kW" />
          <MiniMetric label="Month" value={formatNumber(fleet.monthly, 0)} unit="kWh" />
          <MiniMetric label="Revenue" value={compactMoney(fleet.totalIncome)} unit="IDR" accent />
        </div>
      </section>
      <section className="hero-terminal surface">
        <div className="terminal-head">
          <span>Selected site</span>
          <strong>{selected?.source || "-"}</strong>
        </div>
        <h2>{selected?.name || "No station selected"}</h2>
        <SelectedSiteMap key={selected?.uid || "empty"} location={selected} />
        <div className="terminal-stats">
          <TerminalStat label="Power" value={formatNumber(selected?.current_power_kw)} unit="kW" />
          <TerminalStat label="Month" value={formatNumber(selected?.monthly_energy_kwh, 0)} unit="kWh" />
          <TerminalStat label="Total" value={formatNumber(selected?.cumulative_energy_kwh, 0)} unit="kWh" />
          <TerminalStat label="Revenue" value={compactMoney(selected?.cumulative_income)} unit="IDR" />
        </div>
      </section>
    </header>
  );
}

function SelectedSiteMap({ location }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const latitude = Number(location?.latitude);
  const longitude = Number(location?.longitude);
  const hasCoordinates = Number.isFinite(latitude) && Number.isFinite(longitude);

  useEffect(() => {
    if (!containerRef.current || !hasCoordinates) return undefined;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: OPENFREEMAP_STYLE,
      center: [longitude, latitude],
      zoom: 16,
      attributionControl: true,
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

    const markerButton = document.createElement("button");
    markerButton.type = "button";
    markerButton.className = `station-map-marker selected ${location.status === "normal" ? "online" : "offline"}`;
    markerButton.setAttribute("aria-label", `${location.name} exact location`);
    markerButton.title = location.name;

    const popup = new maplibregl.Popup({ offset: 18, closeButton: false })
      .setDOMContent(stationPopup(location));
    new maplibregl.Marker({ element: markerButton, anchor: "center" })
      .setLngLat([longitude, latitude])
      .setPopup(popup)
      .addTo(map);
    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, [hasCoordinates, latitude, location, longitude]);

  if (!hasCoordinates) {
    return <div className="selected-map-empty">Coordinates unavailable for this station.</div>;
  }

  return (
    <div className="selected-map-wrap">
      <div ref={containerRef} className="selected-site-map" aria-label={`Map showing ${location.name}`} />
      <a
        className="selected-map-link"
        href={`https://www.openstreetmap.org/?mlat=${latitude}&mlon=${longitude}#map=18/${latitude}/${longitude}`}
        target="_blank"
        rel="noreferrer"
      >
        {latitude.toFixed(6)}, {longitude.toFixed(6)} ↗
      </a>
    </div>
  );
}

function OverviewTab({ fleet, selected, locations, onSelect }) {
  return (
    <Panel title="Overview" subtitle="Fleet performance snapshot">
      <div className="metric-grid four">
        <MetricCard label="Daily energy" value={formatNumber(fleet.daily)} unit="kWh" />
        <MetricCard label="Monthly energy" value={formatNumber(fleet.monthly, 0)} unit="kWh" />
        <MetricCard label="Yearly energy" value={formatNumber(fleet.yearly, 0)} unit="kWh" />
        <MetricCard label="Total revenue" value={money(fleet.totalIncome)} unit="IDR" accent />
      </div>
      <TimeSeriesCard series={{
        available: locations.some((item) => Number.isFinite(Number(item.daily_energy_kwh))),
        labels: locations.map((item) => item.name),
        values: locations.map((item) => item.daily_energy_kwh),
        unit: "kWh",
        kind: "bar",
        title: "Today's energy by site",
        caption: "A like-for-like comparison of energy generated today",
        reason: "Daily site totals are unavailable.",
      }} />
      <div className="content-split">
        <InfoCard title="Selected location">
          <LocationFacts location={selected} />
        </InfoCard>
        <InfoCard title="Fleet register">
          <div className="fleet-map-summary">
            <DataLine label="Total sites" value={fleet.stations} />
            <DataLine label="Platforms" value={fleet.platforms} />
            <DataLine label="Offline" value={fleet.offline} />
            <DataLine label="Current power" value={`${formatNumber(fleet.current)} kW`} />
          </div>
          <FleetMap locations={locations} selectedId={selected?.uid} onSelect={onSelect} />
        </InfoCard>
      </div>
    </Panel>
  );
}

function SitesTab({ locations, selectedId, onSelect }) {
  return (
    <Panel title="Sites" subtitle="Available PLTS locations and live status">
      <div className="site-status-list surface-inset">
        {locations.map((location) => (
          <button key={location.uid} type="button" onClick={() => onSelect(location.uid)} className={`site-status-row ${selectedId === location.uid ? "active" : ""}`}>
            <div className="site-status-name">
              <span className={`status-dot ${location.status !== "normal" ? "muted" : ""}`} />
              <div>
                <strong>{location.name}</strong>
                <em>{location.source} · {location.station_id}</em>
              </div>
            </div>
            <span className={`status-badge ${location.status === "normal" ? "online" : "offline"}`}>{location.status === "normal" ? "Online" : "Offline"}</span>
            <span>{formatNumber(location.capacity_kwp)} kWp</span>
            <span>{formatNumber(location.monthly_energy_kwh, 0)} kWh/bln</span>
          </button>
        ))}
      </div>
    </Panel>
  );
}

function validCoordinate(value) {
  return Number.isFinite(Number(value));
}

function stationPopup(location) {
  const wrapper = document.createElement("div");
  wrapper.className = "station-popup";

  const label = document.createElement("span");
  label.textContent = `${location.source} · ${location.status || "unknown"}`;

  const title = document.createElement("strong");
  title.textContent = location.name || "PLTS station";

  const detail = document.createElement("p");
  detail.textContent = `${formatNumber(location.capacity_kwp)} kWp · ${formatNumber(location.current_power_kw)} kW`;

  const address = document.createElement("p");
  address.textContent = location.address || "Address unavailable";

  wrapper.append(label, title, detail, address);
  return wrapper;
}

function FleetMap({ locations, selectedId, onSelect }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const markersRef = useRef(new Map());
  const fittedRef = useRef(false);
  const [mapError, setMapError] = useState(null);

  const mappedLocations = useMemo(() => locations.filter((location) => (
    validCoordinate(location.latitude) && validCoordinate(location.longitude)
  )), [locations]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return undefined;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: OPENFREEMAP_STYLE,
      center: [106.91, -6.13],
      zoom: 11,
      attributionControl: true,
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.on("load", () => setMapError(null));
    map.on("error", (event) => {
      if (event?.error) setMapError("The map background could not be loaded. Station coordinates remain available from the monitoring data.");
    });
    mapRef.current = map;

    return () => {
      markersRef.current.clear();
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    markersRef.current.forEach((marker) => marker.remove());
    markersRef.current.clear();

    const bounds = new maplibregl.LngLatBounds();
    mappedLocations.forEach((location) => {
      const longitude = Number(location.longitude);
      const latitude = Number(location.latitude);
      const markerButton = document.createElement("button");
      markerButton.type = "button";
      markerButton.className = `station-map-marker ${location.status === "normal" ? "online" : "offline"}`;
      markerButton.setAttribute("aria-label", `Select ${location.name} on map`);
      markerButton.title = location.name;
      markerButton.addEventListener("click", () => onSelect(location.uid));

      const popup = new maplibregl.Popup({ offset: 18, closeButton: false })
        .setDOMContent(stationPopup(location));
      const marker = new maplibregl.Marker({ element: markerButton, anchor: "center" })
        .setLngLat([longitude, latitude])
        .setPopup(popup)
        .addTo(map);

      markersRef.current.set(location.uid, marker);
      bounds.extend([longitude, latitude]);
    });

    if (!fittedRef.current && !bounds.isEmpty()) {
      map.fitBounds(bounds, { padding: 72, maxZoom: 14, duration: 0 });
      fittedRef.current = true;
    }
  }, [mappedLocations, onSelect]);

  useEffect(() => {
    markersRef.current.forEach((marker, uid) => {
      marker.getElement().classList.toggle("selected", uid === selectedId);
    });
  }, [mappedLocations, selectedId]);

  if (!mappedLocations.length) {
    return <EmptyState message="No valid station coordinates are available." />;
  }

  return (
    <>
      <section className="map-stage fleet-map-stage surface-inset" aria-label="Interactive map of all PLTS stations">
        <div ref={containerRef} className="station-map" />
        {mapError && <div className="map-error" role="status">{mapError}</div>}
        <div className="map-key" aria-hidden="true">
          <span><i className="online" /> Online</span>
          <span><i className="offline" /> Offline</span>
        </div>
      </section>
      {mappedLocations.length < locations.length && (
        <p className="map-note">{locations.length - mappedLocations.length} station(s) were omitted because their coordinates are missing.</p>
      )}
    </>
  );
}

function EnergyTab({ location, fleet }) {
  const [period, setPeriod] = useState("today");
  const energy = energyMetrics(location);
  const series = getEnergySeries(location, period);
  return (
    <Panel title="Energy" subtitle="Production history for the selected location">
      <div className="metric-grid four">
        <MetricCard label="Today" value={formatNumber(energy.daily)} unit="kWh" sub={`${formatNumber(toMwh(energy.daily), 3)} MWh`} />
        <MetricCard label="This month" value={formatNumber(energy.monthly)} unit="kWh" sub={`${formatNumber(toMwh(energy.monthly), 3)} MWh`} />
        <MetricCard label="This year" value={formatNumber(energy.yearly)} unit="kWh" sub={`${formatNumber(toMwh(energy.yearly), 3)} MWh`} />
        <MetricCard label="Lifetime" value={formatNumber(energy.total)} unit="kWh" sub={`${formatNumber(toMwh(energy.total), 3)} MWh`} accent />
      </div>
      <TimeSeriesCard
        series={series}
        locationName={location?.name}
        action={(
          <>
            <PeriodControl
              label="Energy chart period"
              options={[["today", "Today"], ["month", "Month"], ["year", "Year"]]}
              value={period}
              onChange={setPeriod}
            />
          </>
        )}
      />
      <div className="content-split">
        <InfoCard title="Selected site totals">
          <div className="facts-grid">
            <DataLine label="Daily MWh" value={`${formatNumber(toMwh(energy.daily), 3)} MWh`} />
            <DataLine label="Monthly MWh" value={`${formatNumber(toMwh(energy.monthly), 3)} MWh`} />
            <DataLine label="Yearly MWh" value={`${formatNumber(toMwh(energy.yearly), 3)} MWh`} />
            <DataLine label="Total MWh" value={`${formatNumber(toMwh(energy.total), 3)} MWh`} />
          </div>
        </InfoCard>
        <InfoCard title="Fleet reference">
          <div className="facts-grid">
            <DataLine label="Fleet today" value={`${formatNumber(fleet.daily)} kWh`} />
            <DataLine label="Fleet month" value={`${formatNumber(fleet.monthly)} kWh`} />
            <DataLine label="Fleet year" value={`${formatNumber(fleet.yearly)} kWh`} />
            <DataLine label="Fleet lifetime" value={`${formatNumber(fleet.total)} kWh`} />
          </div>
        </InfoCard>
      </div>
    </Panel>
  );
}

function RevenueTab({ location, fleet }) {
  const [period, setPeriod] = useState("year");
  const revenue = revenueMetrics(location);
  const series = getRevenueSeries(location, period);
  const currency = location?.income_currency || (location?.source === "huawei" ? "IDR" : "Currency");
  return (
    <Panel title="Revenue" subtitle="Vendor-reported revenue for the selected location">
      <div className="metric-grid four">
        <MetricCard label="Today" value={formatRevenue(revenue.daily, currency)} unit={currency} />
        <MetricCard label="This month" value={formatRevenue(revenue.monthly, currency)} unit={currency} />
        <MetricCard label="This year" value={formatRevenue(revenue.yearly, currency)} unit={currency} />
        <MetricCard label="Lifetime" value={formatRevenue(revenue.total, currency)} unit={currency} accent />
      </div>
      <TimeSeriesCard
        series={series}
        locationName={location?.name}
        moneyMode
        action={(
          <>
            <PeriodControl
              label="Revenue chart period"
              options={[["month", "Month"], ["year", "Year"], ["lifetime", "Lifetime"]]}
              value={period}
              onChange={setPeriod}
            />
          </>
        )}
      />
      <div className="content-split">
        <InfoCard title="Selected site revenue">
          <div className="facts-grid">
            <DataLine label="Currency" value={currency} />
            <DataLine label="Today" value={formatRevenue(revenue.daily, currency)} />
            <DataLine label="This year" value={formatRevenue(revenue.yearly, currency)} />
            <DataLine label="Lifetime" value={formatRevenue(revenue.total, currency)} />
          </div>
        </InfoCard>
        <InfoCard title="Fleet revenue reference">
          <div className="facts-grid">
            <DataLine label="Fleet month" value={money(fleet.monthlyIncome)} />
            <DataLine label="Fleet year" value={money(fleet.yearlyIncome)} />
            <DataLine label="Fleet total" value={money(fleet.totalIncome)} />
            <DataLine label="Selected platform" value={location?.source || "-"} />
          </div>
        </InfoCard>
      </div>
    </Panel>
  );
}

function formatRevenue(value, currency) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "Tidak tersedia";
  if (currency === "IDR") return money(value);
  return `${currency} ${formatNumber(value, 0)}`;
}

function PeriodControl({ label, options, value, onChange }) {
  return (
    <div className="period-control" role="group" aria-label={label}>
      {options.map(([key, text]) => (
        <button
          key={key}
          type="button"
          className={value === key ? "active" : ""}
          aria-pressed={value === key}
          onClick={() => onChange(key)}
        >
          {text}
        </button>
      ))}
    </div>
  );
}

function TimeSeriesCard({ series, locationName, moneyMode = false, action = null }) {
  return (
    <section className="chart-card chart-card-large surface-inset time-series-card">
      <div className="chart-card-head">
        <div>
          <h3>{series.title}</h3>
          <p>{[locationName, series.caption].filter(Boolean).join(" · ")}</p>
        </div>
        <div className="chart-card-actions">
          {action}
          <span className="chart-unit">{series.unit}</span>
        </div>
      </div>
      {series.available
        ? <TimeSeriesChart series={series} moneyMode={moneyMode} />
        : <SeriesEmptyState reason={series.reason} />}
    </section>
  );
}

function SeriesEmptyState({ reason }) {
  return (
    <div className="series-empty" role="status">
      <strong>Historical series unavailable</strong>
      <p>{reason}</p>
      <span>Summary totals above remain valid.</span>
    </div>
  );
}

function TimeSeriesChart({ series, moneyMode }) {
  const gradientId = React.useId();
  const chartWrapRef = useRef(null);
  const [hoverPoint, setHoverPoint] = useState(null);
  const values = series.values.map((value) => Number.isFinite(Number(value)) ? Number(value) : null);
  const valid = values.filter((value) => value !== null);
  const max = Math.max(...valid, 1);
  const axisValue = (value) => moneyMode ? compactMoney(value) : formatNumber(value, value < 10 ? 1 : 0);
  const tooltipValue = (value) => moneyMode ? formatRevenue(value, series.unit) : `${formatNumber(value, value < 10 ? 2 : 1)} ${series.unit}`;
  const yTicks = Array.from({ length: 5 }, (_, index) => ({
    value: max - (max * index) / 4,
    top: 12 + index * 18,
  }));
  const coords = values.map((value, index) => ({
    value,
    label: series.labels[index],
    x: 3 + (index / Math.max(values.length - 1, 1)) * 94,
    y: value === null ? null : 84 - (value / max) * 72,
  }));
  const tickIndexes = [...new Set(Array.from({ length: Math.min(6, coords.length) }, (_, index) => (
    Math.round(index * (coords.length - 1) / Math.max(Math.min(6, coords.length) - 1, 1))
  )))];
  const barWidth = Math.min(7, 72 / Math.max(coords.length, 1));
  const latest = [...coords].reverse().find((point) => point.value !== null);
  const showHoverPoint = (event, point) => {
    if (!chartWrapRef.current || point.value === null) return;
    const bounds = chartWrapRef.current.getBoundingClientRect();
    const x = event.clientX - bounds.left;
    const y = event.clientY - bounds.top;
    setHoverPoint({
      label: point.label,
      value: tooltipValue(point.value),
      x: Math.min(Math.max(x, 92), Math.max(bounds.width - 92, 92)),
      y: Math.min(Math.max(y - 14, 22), Math.max(bounds.height - 70, 22)),
    });
  };

  return (
    <div>
      <div className="time-series-wrap" ref={chartWrapRef} onMouseLeave={() => setHoverPoint(null)}>
        <svg viewBox="0 0 100 100" className="time-series-chart" preserveAspectRatio="none" role="img" aria-label={`${series.title}, ${series.unit}`}>
            <defs>
              <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
              <stop stopColor="#8b94ff" />
              <stop offset="1" stopColor="#5E6AD2" />
            </linearGradient>
            </defs>
          {yTicks.map((tick) => <line key={tick.top} x1="3" x2="98" y1={tick.top} y2={tick.top} className="chart-grid-line" />)}
          <line x1="3" x2="98" y1="84" y2="84" className="chart-axis-line" />
          {coords.map((point, index) => point.y !== null && (
            <rect
              key={`${point.label}-${index}`}
              className="chart-hover-bar"
              x={point.x - barWidth / 2}
              y={point.y}
              width={barWidth}
              height={84 - point.y}
              rx="1"
              fill={`url(#${gradientId})`}
              onMouseEnter={(event) => showHoverPoint(event, point)}
              onMouseMove={(event) => showHoverPoint(event, point)}
            />
          ))}
        </svg>
        <div className="time-axis-y" aria-hidden="true">
          {yTicks.map((tick) => <span key={tick.top} style={{ top: `${tick.top}%` }}>{axisValue(tick.value)}</span>)}
        </div>
        <div className="time-axis-x" aria-hidden="true">
          {tickIndexes.map((index) => <span key={index} style={{ left: `${coords[index].x}%` }}>{coords[index].label}</span>)}
        </div>
        {hoverPoint && (
          <div className="chart-hover-tooltip" style={{ left: `${hoverPoint.x}px`, top: `${hoverPoint.y}px` }}>
            <strong>{hoverPoint.label}</strong>
            <span>{hoverPoint.value}</span>
          </div>
        )}
      </div>
      <div className="series-summary">
        <DataLine label="Records" value={`${valid.length} / ${values.length}`} />
        <DataLine label="Highest" value={`${axisValue(max)} ${series.unit}`} />
        <DataLine label="Latest" value={latest ? `${axisValue(latest.value)} ${series.unit}` : "-"} />
      </div>
    </div>
  );
}

function Panel({ title, subtitle, children }) {
  return (
    <article className="panel surface spotlight-card">
      <div className="panel-title">
        <p className="eyebrow">{subtitle}</p>
        <h2>{title}</h2>
      </div>
      {children}
    </article>
  );
}

function MetricCard({ label, value, unit, sub, accent }) {
  return (
    <section className={`metric-card ${accent ? "accent" : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <em>{unit}</em>
      {sub && <small>{sub}</small>}
    </section>
  );
}

function MiniMetric({ label, value, unit, accent }) {
  return (
    <div className={`mini-metric ${accent ? "accent" : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {unit && <em>{unit}</em>}
    </div>
  );
}

function TerminalStat({ label, value, unit }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
      <em>{unit}</em>
    </div>
  );
}

function InfoCard({ title, children }) {
  return (
    <section className="info-card surface-inset">
      <h3>{title}</h3>
      {children}
    </section>
  );
}

function ChartCard({ title, caption, points, moneyMode, large }) {
  return (
    <section className={`chart-card surface-inset ${large ? "chart-card-large" : ""}`}>
      <div className="chart-card-head">
        <div>
          <h3>{title}</h3>
          {caption && <p>{caption}</p>}
        </div>
        <span>{moneyMode ? "IDR" : "kWh"}</span>
      </div>
      <LineChart points={points} moneyMode={moneyMode} large={large} />
    </section>
  );
}

function LineChart({ points, moneyMode, large }) {
  const gradientId = React.useId();
  const areaId = React.useId();
  const valid = points.map(([, value]) => Number(value)).filter((value) => Number.isFinite(value));
  const max = Math.max(...valid, 1);
  const min = Math.min(...valid, 0);
  const range = Math.max(max - min, 1);
  const coords = points.map(([, value], index) => {
    const x = 1 + (index / Math.max(points.length - 1, 1)) * 96;
    const numeric = Number(value);
    const safe = Number.isFinite(numeric) ? numeric : min;
    const y = 82 - ((safe - min) / range) * 68;
    return { x, y };
  });
  const axisValue = (value) => moneyMode ? compactMoney(value) : formatNumber(value, 0);
  const yTicks = Array.from({ length: 5 }, (_, index) => ({
    value: max - (range * index) / 4,
    top: 14 + index * 17,
  }));
  const path = coords.map((point) => `${point.x},${point.y}`).join(" ");
  const areaPath = `${coords.map((point) => `${point.x},${point.y}`).join(" ")} ${coords.at(-1)?.x || 97},88 ${coords[0]?.x || 1},88`;
  return (
    <div>
      <div className={`line-chart-wrap ${large ? "large" : ""}`}>
        <svg viewBox="0 0 100 100" className={`line-chart ${large ? "large" : ""}`} preserveAspectRatio="none">
          <defs>
            <linearGradient id={gradientId} x1="0" x2="1" y1="0" y2="0">
              <stop stopColor="#8b94ff" />
              <stop offset="1" stopColor="#5E6AD2" />
            </linearGradient>
            <linearGradient id={areaId} x1="0" x2="0" y1="0" y2="1">
              <stop stopColor="rgba(94,106,210,.32)" />
              <stop offset="1" stopColor="rgba(94,106,210,0)" />
            </linearGradient>
          </defs>
          {yTicks.map((tick) => <line key={tick.top} x1="1" x2="100" y1={tick.top} y2={tick.top} className="chart-grid-line" />)}
          <line x1="1" x2="100" y1="88" y2="88" className="chart-axis-line" />
          <line x1="1" x2="1" y1="10" y2="88" className="chart-axis-line" />
          <polygon points={areaPath} fill={`url(#${areaId})`} />
          <polyline points={path} fill="none" stroke={`url(#${gradientId})`} strokeWidth={large ? "4.5" : "3.5"} strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
        </svg>
        <div className="axis-y" aria-hidden="true">
          {yTicks.map((tick) => <span key={tick.top} style={{ top: `${tick.top}%` }}>{axisValue(tick.value)}</span>)}
        </div>
        <div className="axis-x" aria-hidden="true">
          {coords.map((point, index) => <span key={index} style={{ left: `${point.x}%` }}>{String(index + 1).padStart(2, "0")}</span>)}
        </div>
      </div>
      <div className="chart-legend">
        {points.map(([label, value]) => (
          <div key={label}>
            <span>{label}</span>
            <strong>{moneyMode ? money(value) : formatNumber(value)}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

function LocationFacts({ location }) {
  if (!location) return <EmptyState message="Belum ada lokasi di data monitoring." />;
  return (
    <div className="facts-grid">
      <DataLine label="Station" value={location.name} />
      <DataLine label="Platform" value={location.source} />
      <DataLine label="Status" value={location.status || "unknown"} />
      <DataLine label="Capacity" value={`${formatNumber(location.capacity_kwp)} kWp`} />
      <DataLine label="Power" value={`${formatNumber(location.current_power_kw)} kW`} />
      <DataLine label="Station ID" value={location.station_id} />
      <DataLine label="Address" value={location.address || "Alamat belum tersedia"} wide />
    </div>
  );
}

function SiteTable({ locations }) {
  return (
    <div className="site-table surface-inset">
      {locations.map((location) => (
        <div key={location.uid}>
          <span>{location.name}</span>
          <span>{location.source}</span>
          <span>{formatNumber(location.monthly_energy_kwh, 0)} kWh</span>
          <span>{money(location.cumulative_income)}</span>
        </div>
      ))}
    </div>
  );
}

function DataLine({ label, value, wide }) {
  return (
    <div className={wide ? "wide" : ""}>
      <span>{label}</span>
      <strong>{value || "-"}</strong>
    </div>
  );
}

function EmptyState({ message }) {
  return <div className="empty-state">{message}</div>;
}

function LoadingScreen() {
  return (
    <div className="loading-screen" role="status" aria-label="Loading">
      <span className="state-spinner" aria-hidden="true" />
    </div>
  );
}

function StateCard({ title, message }) {
  return (
    <div className="state-card surface" role="status">
      <p className="eyebrow">{title}</p>
      <h1>{message}</h1>
    </div>
  );
}

function energyMetrics(location) {
  return {
    daily: location?.daily_energy_kwh,
    monthly: location?.monthly_energy_kwh,
    yearly: location?.yearly_energy_kwh,
    total: location?.cumulative_energy_kwh,
  };
}

function revenueMetrics(location) {
  const values = {
    daily: location?.daily_income,
    monthly: location?.monthly_income,
    yearly: location?.yearly_income,
    total: location?.cumulative_income,
  };
  return {
    ...values,
    hasAny: Object.values(values).some((value) => value !== null && value !== undefined && !Number.isNaN(Number(value))),
  };
}

createRoot(document.getElementById("root")).render(<App />);
