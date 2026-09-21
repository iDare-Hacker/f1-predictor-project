/**
 * F1 Live Race Visualizer — app.js
 * Polls the public OpenF1 API (https://api.openf1.org) and renders:
 *  - Live leaderboard with positions, gaps, tyres, DRS
 *  - SVG track map with driver GPS dots
 *  - Telemetry panel (speed, gear, throttle, brake, DRS)
 *  - Race control feed (flags, messages)
 *  - Pit stop events
 */

'use strict';

// ─────────────────────────────────────────────
//  CONFIG
// ─────────────────────────────────────────────
const API_BASE = 'https://api.openf1.org/v1';

const POLL_RATES = {
  session:      60_000,
  drivers:      60_000,
  position:     15_000,
  laps:         20_000,
  carData:      10_000,
  raceControl:  20_000,
  pit:          30_000,
  location:     15_000,
};

const TYRE_MAP = {
  SOFT:    { code: 'S', cls: 'tyre-badge--S' },
  MEDIUM:  { code: 'M', cls: 'tyre-badge--M' },
  HARD:    { code: 'H', cls: 'tyre-badge--H' },
  INTER:   { code: 'I', cls: 'tyre-badge--I' },
  WET:     { code: 'W', cls: 'tyre-badge--W' },
  UNKNOWN: { code: '?', cls: '' },
};

// ─────────────────────────────────────────────
//  OPENF1 API CLIENT
// ─────────────────────────────────────────────
class OpenF1Client {
  constructor(base = API_BASE) {
    this.base = base;
    this._cache = {};
  }

  async fetch(endpoint, params = {}) {
    const url = new URL(`${this.base}/${endpoint}`);
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null) url.searchParams.set(k, v);
    });
    const key = url.toString();

    const resp = await fetch(url.toString(), {
      headers: { 'Accept': 'application/json' },
    });
    if (!resp.ok) throw new Error(`OpenF1 ${resp.status}: ${url}`);
    const data = await resp.json();
    this._cache[key] = data;
    return data;
  }

  // Latest session
  async getLatestSession() {
    const data = await this.fetch('sessions', { session_key: 'latest' });
    return data[0] ?? null;
  }

  // All drivers for a session
  async getDrivers(sessionKey) {
    return this.fetch('drivers', { session_key: sessionKey });
  }

  // Latest positions for all drivers
  async getPositions(sessionKey) {
    const data = await this.fetch('position', { session_key: sessionKey });
    // Group by driver_number → latest entry per driver
    const map = {};
    data.forEach(p => {
      const dn = p.driver_number;
      if (!map[dn] || new Date(p.date) > new Date(map[dn].date)) {
        map[dn] = p;
      }
    });
    return Object.values(map).sort((a, b) => a.position - b.position);
  }

  // Latest lap data (includes tyre, lap time)
  async getLaps(sessionKey) {
    const data = await this.fetch('laps', { session_key: sessionKey });
    const map = {};
    data.forEach(l => {
      const dn = l.driver_number;
      if (!map[dn] || l.lap_number > map[dn].lap_number) {
        map[dn] = l;
      }
    });
    return map; // keyed by driver_number
  }

  // Car data (speed, gear, throttle, brake, DRS) for a specific driver
  async getCarData(sessionKey, driverNumber) {
    const data = await this.fetch('car_data', {
      session_key: sessionKey,
      driver_number: driverNumber,
    });
    // Return most recent entry
    return data.length ? data[data.length - 1] : null;
  }

  // Race control messages
  async getRaceControl(sessionKey) {
    return this.fetch('race_control', { session_key: sessionKey });
  }

  // Pit events
  async getPit(sessionKey) {
    return this.fetch('pit', { session_key: sessionKey });
  }

  // Latest GPS locations (for track map) - limited to specific drivers to avoid API overload
  async getLocations(sessionKey, driverNumbers) {
    const map = {};
    for (const dn of driverNumbers) {
      try {
        const data = await this.fetch('location', { session_key: sessionKey, driver_number: dn });
        if (data.length > 0) {
          map[dn] = data[data.length - 1]; // Keep only the latest point for this driver
        }
      } catch (e) {
        console.warn(`Could not fetch location for driver ${dn}`, e.message);
      }
    }
    return map; // keyed by driver_number
  }
}

// ─────────────────────────────────────────────
//  POLLING MANAGER
// ─────────────────────────────────────────────
class PollingManager {
  constructor() {
    this._timers = {};
    this._running = false;
  }

  register(name, fn, interval) {
    this._timers[name] = { fn, interval, handle: null };
  }

  start() {
    this._running = true;
    Object.entries(this._timers).forEach(([name, cfg]) => {
      cfg.fn(); // immediate first call
      cfg.handle = setInterval(cfg.fn, cfg.interval);
    });
  }

  stop() {
    this._running = false;
    Object.values(this._timers).forEach(cfg => {
      if (cfg.handle) clearInterval(cfg.handle);
    });
  }
}

// ─────────────────────────────────────────────
//  FORMAT UTILITIES
// ─────────────────────────────────────────────
function fmtLapTime(seconds) {
  if (seconds == null || isNaN(seconds)) return '–:–––';
  const m = Math.floor(seconds / 60);
  const s = (seconds % 60).toFixed(3).padStart(6, '0');
  return `${m}:${s}`;
}

function fmtGap(seconds, isLeader) {
  if (isLeader) return 'LEADER';
  if (seconds == null || isNaN(seconds)) return '–';
  if (seconds >= 60) {
    const laps = Math.floor(seconds / 90); // rough lap estimate
    return `+${laps} LAP${laps > 1 ? 'S' : ''}`;
  }
  return `+${seconds.toFixed(3)}`;
}

function fmtTime(isoStr) {
  if (!isoStr) return '';
  const d = new Date(isoStr);
  return d.toLocaleTimeString('en-GB', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function hexToRgb(hex) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgb(${r},${g},${b})`;
}

function getTyreBadge(compound) {
  const key = (compound ?? 'UNKNOWN').toUpperCase();
  const t = TYRE_MAP[key] ?? TYRE_MAP.UNKNOWN;
  return `<span class="tyre-badge ${t.cls}">${t.code}</span>`;
}

function getFlagClass(flag) {
  const f = (flag ?? '').toUpperCase().replace(/\s/g, '_');
  return `rc-message--flag-${f}`;
}

function drsActive(value) {
  // OpenF1: 10=available, 12=enabled, 14=enabled
  return value === 10 || value === 12 || value === 14;
}

// ─────────────────────────────────────────────
//  LEADERBOARD RENDERER
// ─────────────────────────────────────────────
class LeaderboardRenderer {
  constructor(container) {
    this.el = container;
    this._prevPositions = {}; // driver_number → position
  }

  render(positions, lapsMap, driversMap) {
    if (!positions || positions.length === 0) {
      this.el.innerHTML = this._skeleton(8);
      return;
    }

    const leaderLap = lapsMap[positions[0]?.driver_number]?.lap_number ?? 0;
    const rows = positions.map((pos, idx) => {
      const dn    = pos.driver_number;
      const drv   = driversMap[dn] ?? {};
      const lap   = lapsMap[dn] ?? {};

      const abbr  = drv.name_acronym ?? `#${dn}`;
      const full  = drv.full_name ?? '';
      const color = drv.team_colour ? `#${drv.team_colour}` : '#888';
      const tyre  = getTyreBadge(lap.compound);
      const isLdr = idx === 0;
      const gap   = fmtGap(pos.position === 1 ? 0 : null, isLdr);
      const lt    = fmtLapTime(lap.lap_duration);

      // Position delta
      const prev = this._prevPositions[dn];
      let deltaEl = '<span class="pos-delta pos-delta--same"></span>';
      if (prev != null && prev !== pos.position) {
        deltaEl = pos.position < prev
          ? '<span class="pos-delta pos-delta--up"></span>'
          : '<span class="pos-delta pos-delta--down"></span>';
      }
      this._prevPositions[dn] = pos.position;

      // Status
      let statusBadges = '';
      if (lap.pit_out_time) statusBadges += '<span class="status-badge status-badge--pit">PIT</span>';

      // Flash class
      let flashClass = '';
      if (prev != null && pos.position < prev) flashClass = 'flash-gained';
      if (prev != null && pos.position > prev) flashClass = 'flash-lost';

      return `
        <div class="driver-row ${flashClass}" data-driver="${dn}" onclick="app.selectDriver(${dn})">
          <span class="driver-pos ${isLdr ? 'driver-pos--leader' : ''}">${pos.position}</span>
          ${deltaEl}
          <div class="driver-identity">
            <div class="team-bar" style="background:${color}"></div>
          </div>
          <div class="driver-info">
            <span class="driver-abbr">${abbr}</span>
            <span class="driver-name-full dim">${full}</span>
          </div>
          <div class="driver-stats">
            <div style="display:flex;gap:4px;align-items:center;justify-content:flex-end">
              ${tyre}
              <span class="driver-gap">${gap}</span>
            </div>
            <span class="driver-lap-time">${lt}</span>
            ${statusBadges}
          </div>
        </div>`;
    });

    this.el.innerHTML = `<div class="leaderboard">${rows.join('')}</div>`;
  }

  _skeleton(n) {
    return Array.from({ length: n }, () =>
      `<div class="skeleton skeleton-row"></div>`
    ).join('');
  }
}

// ─────────────────────────────────────────────
//  TRACK MAP RENDERER
// ─────────────────────────────────────────────
class TrackMapRenderer {
  constructor(svgEl) {
    this.svg = svgEl;
    this._trackBuilt = false;
    this._trackPoints = []; // [{x, y}]
    this._viewBox = { minX: 0, minY: 0, w: 1000, h: 600 };
  }

  // Collect track outline from location data of a single driver's full trail
  async buildTrack(sessionKey) {
    if (this._trackBuilt) return;

    try {
      // Fetch a full trail for a driver to draw the track shape
      // (Using driver 1 as a reliable baseline for most sessions)
      const resp = await fetch(`https://api.openf1.org/v1/location?session_key=${sessionKey}&driver_number=1`);
      if (!resp.ok) return;
      const rawPts = await resp.json();
      
      // Filter out invalid (0,0) points which happen when the car is stationary/off
      // Downsample by taking every 10th point to prevent SVG rendering lag
      const pts = rawPts.filter((p, i) => i % 10 === 0 && (p.x !== 0 && p.y !== 0) && (p.x != null && p.y != null));

      if (pts.length < 10) return;

      const xs = pts.map(p => p.x);
      const ys = pts.map(p => -p.y); // OpenF1 Y is inverted

      const pad = 800; // Extra padding for track edges to shrink map size
      const minX = Math.min(...xs) - pad;
      const minY = Math.min(...ys) - pad;
      const w = Math.max(...xs) - minX + (pad * 2);
      const h = Math.max(...ys) - minY + (pad * 2);
      
      // Save it so renderDrivers can use it to scale things correctly
      this._viewBox = { minX, minY, w, h };
      
      // Keep viewBox fixed based on the track dimensions
      this.svg.setAttribute('viewBox', `${minX} ${minY} ${w} ${h}`);
      this.svg.setAttribute('width', '100%');
      this.svg.setAttribute('height', '100%');

      // Draw the track path
      const polyline = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
      const pointsString = pts.map(p => `${p.x},${-p.y}`).join(' ');
      polyline.setAttribute('points', pointsString);
      polyline.setAttribute('fill', 'none');
      polyline.setAttribute('stroke', 'rgba(255, 255, 255, 0.15)');
      polyline.setAttribute('stroke-width', `${Math.max(w * 0.015, 50)}`); // Dynamic track line thickness
      polyline.setAttribute('stroke-linejoin', 'round');
      polyline.setAttribute('stroke-linecap', 'round');
      
      // Prepend so it goes under the driver dots
      this.svg.prepend(polyline);

      this._trackBuilt = true;
    } catch (e) {
      console.warn("Could not build track outline", e);
    }
  }

  _project(x, y) {
    return { x, y: -y }; // OpenF1 y is inverted vs SVG
  }

  renderDrivers(locationsMap, driversMap, selectedDriver) {
    if (Object.keys(locationsMap).length === 0) return;

    // Remove old driver dots and placeholder
    const oldDots = this.svg.querySelectorAll('.driver-dot, .driver-label-bg, .driver-label, text');
    oldDots.forEach(el => el.remove());

    // Calculate dynamic sizes based on the track viewBox so it looks good on any circuit
    const vbWidth = this._viewBox?.w || 10000; // Fallback to 10000 if not built
    const dotR = vbWidth * 0.017;
    const dotSelR = vbWidth * 0.025;
    const strokeW = vbWidth * 0.0023;
    const labelW = vbWidth * 0.06;
    const labelH = vbWidth * 0.028;
    const labelRx = vbWidth * 0.005;
    const fontSize = vbWidth * 0.02;

    // Draw driver dots
    Object.entries(locationsMap).forEach(([dn, loc]) => {
      const drv   = driversMap[parseInt(dn)] ?? {};
      const color = drv.team_colour ? `#${drv.team_colour}` : '#888888';
      const abbr  = drv.name_acronym ?? `#${dn}`;
      const cx    = loc.x ?? 0;
      const cy    = -(loc.y ?? 0);
      const r     = parseInt(dn) === selectedDriver ? dotSelR : dotR;
      const isSel = parseInt(dn) === selectedDriver;

      const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      circle.setAttribute('cx', cx);
      circle.setAttribute('cy', cy);
      circle.style.r = `${r}px`; // Bypass CSS cache
      circle.setAttribute('fill', color);
      circle.setAttribute('class', 'driver-dot');
      circle.setAttribute('stroke', isSel ? '#fff' : 'rgba(0,0,0,0.5)');
      circle.style.strokeWidth = `${strokeW}px`;
      circle.style.cursor = 'pointer';
      circle.onclick = () => window.app?.selectDriver(parseInt(dn));
      this.svg.appendChild(circle);

      // Label
      const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      rect.setAttribute('x', cx - (labelW / 2));
      rect.setAttribute('y', cy - r - labelH - (vbWidth * 0.005));
      rect.setAttribute('width', labelW);
      rect.setAttribute('height', labelH);
      rect.style.rx = `${labelRx}px`;
      rect.style.ry = `${labelRx}px`;
      rect.setAttribute('class', 'driver-label-bg');
      this.svg.appendChild(rect);

      const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      text.setAttribute('x', cx);
      text.setAttribute('y', cy - r - (labelH / 2) + (fontSize * 0.3));
      text.setAttribute('class', 'driver-label');
      text.style.fontSize = `${fontSize}px`; // Bypass CSS cache
      text.setAttribute('fill', '#fff');
      text.textContent = abbr;
      this.svg.appendChild(text);
    });
  }
}

// ─────────────────────────────────────────────
//  TELEMETRY RENDERER
// ─────────────────────────────────────────────
class TelemetryRenderer {
  constructor(container) {
    this.el = container;
  }

  render(carData, driverInfo) {
    if (!carData) {
      this.el.innerHTML = `<div class="error-state"><span class="error-state__icon">📡</span><p class="error-state__body">Select a driver to view telemetry</p></div>`;
      return;
    }

    const speed    = Math.round(carData.speed ?? 0);
    const gear     = carData.n_gear ?? carData.gear ?? 0;
    const throttle = Math.round(carData.throttle ?? 0);
    const brake    = Math.round(carData.brake ?? 0);
    const drs      = drsActive(carData.drs ?? 0);
    const rpm      = Math.round(carData.rpm ?? 0);

    const throttlePct = Math.min(100, throttle);
    const brakePct    = Math.min(100, brake);
    const ersPct      = 0; // not in public API

    const name = driverInfo?.name_acronym ?? '–';
    const color = driverInfo?.team_colour ? `#${driverInfo.team_colour}` : '#E10600';

    this.el.innerHTML = `
      <div class="driver-selector" id="driver-chips"></div>
      <div style="padding:var(--gap-sm) var(--gap-md); display:flex; align-items:center; gap:var(--gap-sm); border-bottom:1px solid var(--glass-border);">
        <div class="team-bar" style="background:${color};height:20px;"></div>
        <span class="driver-abbr" style="color:${color};">${name}</span>
        <span class="dim" style="font-size:0.75rem">${driverInfo?.full_name ?? ''}</span>
      </div>
      <div class="telemetry-grid">
        <div class="telemetry-card telemetry-card--speed">
          <div class="telemetry-card__value">${speed}</div>
          <div class="telemetry-card__unit">km/h</div>
        </div>
        <div class="telemetry-card telemetry-card--gear">
          <div class="telemetry-card__value">${gear}</div>
          <div class="telemetry-card__unit">Gear</div>
        </div>
        <div class="telemetry-card telemetry-card--rpm">
          <div class="telemetry-card__value">${(rpm / 1000).toFixed(1)}k</div>
          <div class="telemetry-card__unit">RPM</div>
        </div>
        <div class="bar-card" style="grid-column: span 1;">
          <div class="bar-label"><span>Throttle</span><span>${throttlePct}%</span></div>
          <div class="bar-track"><div class="bar-fill bar-fill--throttle" style="width:${throttlePct}%"></div></div>
          <div class="bar-label" style="margin-top:6px"><span>Brake</span><span>${brakePct}%</span></div>
          <div class="bar-track"><div class="bar-fill bar-fill--brake" style="width:${brakePct}%"></div></div>
        </div>
        <div class="drs-indicator">
          <div class="drs-light ${drs ? 'drs-light--active' : ''}"></div>
          <span class="drs-label">DRS</span>
        </div>
      </div>`;
  }
}

// ─────────────────────────────────────────────
//  RACE CONTROL RENDERER
// ─────────────────────────────────────────────
class RaceControlRenderer {
  constructor(container) {
    this.el = container;
    this._seenMessages = new Set();
  }

  render(messages) {
    if (!messages || messages.length === 0) {
      if (this.el.children.length === 0) {
        this.el.innerHTML = `<div class="error-state" style="padding:var(--gap-lg)"><span class="error-state__icon">📻</span><p class="error-state__body">Waiting for race control messages…</p></div>`;
      }
      return;
    }

    // Show newest 40 messages, reversed (newest at top)
    const sorted = [...messages].sort((a, b) => new Date(b.date) - new Date(a.date)).slice(0, 40);

    // Only re-render if something changed
    const ids = sorted.map(m => m.date).join('|');
    if (this._lastIds === ids) return;
    this._lastIds = ids;

    const items = sorted.map(msg => {
      const flag   = (msg.flag ?? '').toUpperCase();
      const flagCls = getFlagClass(msg.flag);
      const time   = fmtTime(msg.date);
      const text   = msg.message ?? '';
      const category = msg.category ?? '';

      let flagBadge = '';
      if (flag && flag !== 'NONE') {
        const badgeColors = {
          GREEN: 'var(--f1-green)', YELLOW: 'var(--f1-yellow)', RED: 'var(--f1-red)',
          CHEQUERED: '#fff', 'SAFETY CAR': 'var(--f1-yellow)', VSC: 'var(--f1-blue)',
        };
        const c = badgeColors[flag] ?? 'var(--f1-grey-light)';
        flagBadge = `<span class="rc-message__flag" style="background:rgba(0,0,0,0.3);color:${c};border:1px solid ${c}">${flag}</span><br>`;
      }

      return `
        <div class="rc-message ${flagCls}">
          <div class="rc-message__time">${time} · ${category}</div>
          ${flagBadge}
          <div class="rc-message__text">${text}</div>
        </div>`;
    });

    this.el.innerHTML = items.join('');
  }
}

// ─────────────────────────────────────────────
//  SESSION / HERO RENDERER
// ─────────────────────────────────────────────
class SessionRenderer {
  constructor() {
    this.roundEl   = document.getElementById('hero-round');
    this.nameEl    = document.getElementById('hero-name');
    this.circuitEl = document.getElementById('hero-circuit');
    this.lapEl     = document.getElementById('hero-lap');
    this.sessionEl = document.getElementById('hero-session-type');
    this.flagEl    = document.getElementById('hero-flag');
    this.statusEl  = document.getElementById('status-text');
  }

  render(session, positions) {
    if (!session) return;
    if (this.roundEl)   this.roundEl.textContent   = `Round ${session.meeting_key ?? '–'} · ${session.year ?? ''}`;
    if (this.nameEl)    this.nameEl.textContent     = session.meeting_name ?? session.location ?? 'F1 Race';
    if (this.circuitEl) this.circuitEl.textContent  = `📍 ${session.location ?? ''}, ${session.country_name ?? ''}`;
    if (this.sessionEl) this.sessionEl.textContent  = session.session_name ?? '';
    if (this.statusEl)  this.statusEl.textContent   = `Last updated: ${new Date().toLocaleTimeString('en-GB')}`;
  }

  setLap(lap, totalLaps) {
    if (this.lapEl && lap) {
      this.lapEl.textContent = `${lap}${totalLaps ? ` / ${totalLaps}` : ''}`;
    }
  }

  setFlag(flagStr) {
    if (!this.flagEl) return;
    const f = (flagStr ?? 'GREEN').toUpperCase();
    const labels = {
      GREEN: '🟢 Green', YELLOW: '🟡 Yellow', RED: '🔴 Red Flag',
      'SAFETY CAR': '🟡 Safety Car', VSC: '🔵 VSC', CHEQUERED: '🏁 Chequered',
    };
    const clsMap = {
      GREEN: 'track-flag--green', YELLOW: 'track-flag--yellow', RED: 'track-flag--red',
      'SAFETY CAR': 'track-flag--sc', VSC: 'track-flag--vsc', CHEQUERED: 'track-flag--green',
    };
    this.flagEl.textContent = labels[f] ?? f;
    this.flagEl.className   = `track-flag ${clsMap[f] ?? 'track-flag--green'}`;
  }
}

// ─────────────────────────────────────────────
//  TOAST NOTIFICATIONS
// ─────────────────────────────────────────────
class ToastManager {
  constructor(container) {
    this.el = container;
  }

  show(title, body, type = 'error', duration = 5000) {
    const t = document.createElement('div');
    t.className = `toast toast--${type}`;
    t.innerHTML = `<div class="toast__title">${title}</div><div class="toast__body">${body}</div>`;
    this.el.appendChild(t);
    setTimeout(() => t.remove(), duration);
  }
}

// ─────────────────────────────────────────────
//  DRIVER CHIP SELECTOR (for telemetry)
// ─────────────────────────────────────────────
function renderDriverChips(driversMap, positions, selectedDriver, onSelect) {
  const container = document.getElementById('telemetry-driver-chips');
  if (!container) return;

  // Order chips by current race position
  const ordered = positions
    .map(p => driversMap[p.driver_number])
    .filter(Boolean);

  container.innerHTML = ordered.map(drv => {
    const color = drv.team_colour ? `#${drv.team_colour}` : '#888';
    const isSel = drv.driver_number === selectedDriver;
    return `
      <div class="driver-chip ${isSel ? 'driver-chip--active' : ''}"
           style="${isSel ? `color:${color};border-color:${color}` : ''}"
           onclick="app.selectDriver(${drv.driver_number})">
        <div class="driver-chip__dot" style="background:${color}"></div>
        ${drv.name_acronym}
      </div>`;
  }).join('');
}

// ─────────────────────────────────────────────
//  MAIN APPLICATION
// ─────────────────────────────────────────────
class F1App {
  constructor() {
    this.client   = new OpenF1Client();
    this.polling  = new PollingManager();
    this.toasts   = new ToastManager(document.getElementById('toast-container'));

    // State
    this.sessionKey     = null;
    this.session        = null;
    this.driversMap     = {}; // driver_number → driver object
    this.positions      = [];
    this.lapsMap        = {};
    this.raceControl    = [];
    this.locationsMap   = {};
    this.selectedDriver = null;
    this.carData        = null;
    this._errorShown    = {};

    // Renderers
    this.leaderboardRenderer = new LeaderboardRenderer(
      document.getElementById('leaderboard-body')
    );
    this.trackMap = new TrackMapRenderer(
      document.getElementById('track-svg')
    );
    this.telemetry = new TelemetryRenderer(
      document.getElementById('telemetry-body')
    );
    this.radioFeed = new RaceControlRenderer(
      document.getElementById('radio-feed-body')
    );
    this.sessionRenderer = new SessionRenderer();
  }

  async init() {
    console.log('[F1App] Starting…');
    await this._loadSession();
    await this._loadDrivers();
    if (this.sessionKey) {
      this._startPolling();
    }
  }

  async _loadSession() {
    try {
      this.session = await this.client.getLatestSession();
      if (!this.session) throw new Error('No session returned');
      this.sessionKey = this.session.session_key;
      console.log('[F1App] Session:', this.session.session_name, this.sessionKey);
      this.sessionRenderer.render(this.session, []);
      document.getElementById('status-badge')?.classList.remove('hidden');
      
      // Build track outline for this session in the background
      this.trackMap.buildTrack(this.sessionKey);
    } catch (e) {
      console.error('[F1App] Session load error:', e);
      this.toasts.show('API Error', 'Could not load session data. Check connection.', 'error');
    }
  }

  async _loadDrivers() {
    if (!this.sessionKey) return;
    try {
      const drivers = await this.client.getDrivers(this.sessionKey);
      this.driversMap = {};
      drivers.forEach(d => { this.driversMap[d.driver_number] = d; });
      console.log('[F1App] Loaded', Object.keys(this.driversMap).length, 'drivers');
    } catch (e) {
      console.error('[F1App] Driver load error:', e);
    }
  }

  _startPolling() {
    // Positions
    this.polling.register('position', async () => {
      try {
        this.positions = await this.client.getPositions(this.sessionKey);
        this.leaderboardRenderer.render(this.positions, this.lapsMap, this.driversMap);
        renderDriverChips(this.driversMap, this.positions, this.selectedDriver,
          dn => this.selectDriver(dn));
      } catch (e) { this._handlePollError('position', e); }
    }, POLL_RATES.position);

    // Laps
    this.polling.register('laps', async () => {
      try {
        this.lapsMap = await this.client.getLaps(this.sessionKey);
        this.leaderboardRenderer.render(this.positions, this.lapsMap, this.driversMap);

        // Update current lap in hero
        const leaderPos = this.positions[0];
        if (leaderPos) {
          const lap = this.lapsMap[leaderPos.driver_number];
          if (lap) this.sessionRenderer.setLap(lap.lap_number);
        }

        // Update track status from latest race control
        const last = this.raceControl[this.raceControl.length - 1];
        if (last?.flag) this.sessionRenderer.setFlag(last.flag);
      } catch (e) { this._handlePollError('laps', e); }
    }, POLL_RATES.laps);

    // Locations (track map) - Fetch only for Top 3 + Selected Driver to respect rate limits
    this.polling.register('location', async () => {
      try {
        let driversToFetch = this.positions.slice(0, 3).map(p => p.driver_number);
        if (this.selectedDriver && !driversToFetch.includes(this.selectedDriver)) {
          driversToFetch.push(this.selectedDriver);
        }
        if (driversToFetch.length === 0) driversToFetch = [1]; // fallback

        this.locationsMap = await this.client.getLocations(this.sessionKey, driversToFetch);
        this.trackMap.renderDrivers(this.locationsMap, this.driversMap, this.selectedDriver);
      } catch (e) { this._handlePollError('location', e); }
    }, POLL_RATES.location);

    // Race control
    this.polling.register('raceControl', async () => {
      try {
        this.raceControl = await this.client.getRaceControl(this.sessionKey);
        this.radioFeed.render(this.raceControl);
        const last = this.raceControl[this.raceControl.length - 1];
        if (last?.flag) this.sessionRenderer.setFlag(last.flag);
      } catch (e) { this._handlePollError('raceControl', e); }
    }, POLL_RATES.raceControl);

    // Car data for selected driver
    this.polling.register('carData', async () => {
      if (!this.selectedDriver) return;
      try {
        this.carData = await this.client.getCarData(this.sessionKey, this.selectedDriver);
        const driverInfo = this.driversMap[this.selectedDriver];
        this.telemetry.render(this.carData, driverInfo);
      } catch (e) { this._handlePollError('carData', e); }
    }, POLL_RATES.carData);

    // Session refresh (occasionally)
    this.polling.register('session', async () => {
      try {
        this.session = await this.client.getLatestSession();
        if (this.session?.session_key !== this.sessionKey) {
          // New session started!
          this.sessionKey = this.session.session_key;
          this.driversMap = {};
          await this._loadDrivers();
          this.toasts.show('New Session', `Session changed: ${this.session.session_name}`, 'success');
        }
        this.sessionRenderer.render(this.session, this.positions);
      } catch (e) { /* silent */ }
    }, POLL_RATES.session);

    this.polling.start();
  }

  selectDriver(driverNumber) {
    this.selectedDriver = driverNumber;
    // Highlight in leaderboard
    document.querySelectorAll('.driver-row').forEach(r => {
      r.classList.toggle('driver-row--selected', parseInt(r.dataset.driver) === driverNumber);
    });
    // Re-render chips
    renderDriverChips(this.driversMap, this.positions, this.selectedDriver,
      dn => this.selectDriver(dn));
    // Immediately fetch car data
    if (this.sessionKey) {
      this.client.getCarData(this.sessionKey, driverNumber).then(data => {
        this.carData = data;
        this.telemetry.render(data, this.driversMap[driverNumber]);
      }).catch(() => {});
    }
    // Update track map highlight
    this.trackMap.renderDrivers(this.locationsMap, this.driversMap, this.selectedDriver);
  }

  _handlePollError(name, err) {
    if (!this._errorShown[name]) {
      console.warn(`[F1App] Poll error (${name}):`, err.message);
      this._errorShown[name] = true;
      setTimeout(() => { delete this._errorShown[name]; }, 30_000);
    }
  }
}

// ─────────────────────────────────────────────
//  BOOTSTRAP
// ─────────────────────────────────────────────
let app;
document.addEventListener('DOMContentLoaded', () => {
  app = new F1App();
  app.init().catch(err => {
    console.error('[F1App] Fatal init error:', err);
  });

  // Expose globally for onclick handlers
  window.app = app;
});
