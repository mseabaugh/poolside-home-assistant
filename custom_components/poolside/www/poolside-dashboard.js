/** Daily-use Poolside dashboard with a separate live diagnostics view. */
class PoolsideDashboard extends HTMLElement {
  getGridOptions() {
    return { columns: 12, min_columns: 6, min_rows: 4 };
  }

  setConfig(config) {
    if (!config || typeof config.mode_entity !== "string") {
      throw new Error("poolside-dashboard requires mode_entity");
    }
    this.config = config;
    const root = this.shadowRoot || this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        :host { display:block; }
        ha-card { padding:18px; }
        h2, h3 { margin:0; }
        h2 { font-size:1.2rem; }
        h3 { font-size:1rem; }
        ha-icon { color:var(--state-icon-color); }
        .poolside-icon { width:24px; height:24px; flex:0 0 24px; object-fit:contain; }
        .mode .poolside-icon { width:22px; height:22px; margin-right:7px; vertical-align:middle; }
        .header { display:flex; align-items:center; gap:10px; }
        .subtitle, .hint { margin:5px 0 0; color:var(--secondary-text-color); font-size:.86rem; }
        .mode-rail { display:flex; gap:4px; margin:18px 0; padding:4px; background:var(--secondary-background-color); border-radius:26px; }
        button { font:inherit; cursor:pointer; }
        .mode { flex:1; border:0; border-radius:22px; padding:10px 12px; color:var(--primary-text-color); background:transparent; }
        .mode.active { color:var(--text-primary-color); background:var(--primary-color); font-weight:600; }
        .overview { display:grid; grid-template-columns:repeat(auto-fit,minmax(135px,1fr)); gap:9px; }
        .live-gauge-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(145px,1fr)); gap:12px; margin-top:14px; }
        .stat { min-height:74px; padding:12px; border:1px solid var(--divider-color); border-radius:12px; background:var(--card-background-color); }
        .stat.water-temperature-cool { background:color-mix(in srgb, #90caf9 28%, var(--card-background-color)); }
        .stat.water-temperature-warm { background:color-mix(in srgb, #ffcc80 32%, var(--card-background-color)); }
        .stat.water-temperature-hot { background:color-mix(in srgb, #ef9a9a 34%, var(--card-background-color)); }
        .stat-label { display:flex; gap:6px; align-items:center; color:var(--secondary-text-color); font-size:.76rem; }
        .stat-value { display:block; margin-top:8px; font-size:1.12rem; font-weight:600; }
        .stat-value.temperature-with-air { white-space:pre-line; line-height:1.45; }
        .section { border-top:1px solid var(--divider-color); margin-top:18px; padding-top:15px; }
        .section-head { display:flex; align-items:center; justify-content:space-between; margin-bottom:10px; }
        .home-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); gap:12px; margin-top:14px; }
        .panel { border:1px solid var(--divider-color); border-radius:12px; padding:12px; }
        .panel-title { display:flex; align-items:center; gap:8px; font-weight:600; margin-bottom:7px; }
        .panel .row + .row { border-top:1px solid var(--divider-color); }
        .row { display:flex; align-items:center; justify-content:space-between; gap:10px; min-height:45px; }
        .label { display:flex; min-width:0; align-items:center; gap:8px; }
        .label span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .actions { display:flex; align-items:center; justify-content:flex-end; gap:8px; min-width:0; }
        ha-switch.toggle { flex:0 0 auto; }
        ha-slider.slider { width:104px; --ha-slider-track-color:var(--divider-color); --ha-slider-track-color-active:var(--primary-color); --ha-slider-thumb-color:var(--primary-color); }
        ha-slider.native-light-slider { display:block; width:100%; --ha-slider-track-color:var(--divider-color); --ha-slider-track-color-active:var(--primary-color); --ha-slider-thumb-color:var(--primary-color); }
        .value { min-width:44px; color:var(--secondary-text-color); font-size:.82rem; text-align:right; }
        .color { width:30px; height:28px; padding:0; border:1px solid var(--divider-color); border-radius:7px; background:transparent; }
        .color-presets { display:flex; gap:6px; flex-wrap:wrap; justify-content:flex-end; }
        .color-preset { width:25px; height:25px; min-width:25px; padding:0; border:2px solid var(--divider-color); border-radius:50%; }
        .color-preset[aria-pressed="true"] { outline:2px solid var(--primary-color); outline-offset:2px; }
        .effect { max-width:105px; border:1px solid var(--divider-color); border-radius:7px; padding:4px; color:var(--primary-text-color); background:var(--card-background-color); }
        .features { display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:8px; }
        .metric-list { margin:0; padding:0; list-style:none; }
        .metric-list li { display:flex; justify-content:space-between; gap:12px; padding:9px 0; border-top:1px solid var(--divider-color); }
        .metric-list li:first-child { border-top:0; }
        .metric-list strong { text-align:right; }
        .schedule-time { color:var(--secondary-text-color); font-size:.86rem; margin-top:5px; }
        .feature { border:1px solid var(--divider-color); border-radius:12px; padding:10px; }
        .feature.active { background:color-mix(in srgb, #ff9800 16%, var(--card-background-color)); border-color:color-mix(in srgb, #ff9800 55%, var(--divider-color)); }
        .heater { background:color-mix(in srgb, var(--heater-temp-color, #2196f3) 18%, var(--card-background-color)); border-color:color-mix(in srgb, var(--heater-temp-color, #2196f3) 48%, var(--divider-color)); }
        .heater.active { background:color-mix(in srgb, var(--heater-temp-color, #2196f3) 30%, var(--card-background-color)); border-color:color-mix(in srgb, var(--heater-temp-color, #2196f3) 72%, var(--divider-color)); }
        .feature-title { display:flex; align-items:center; gap:8px; min-width:0; font-weight:600; }
        .feature-title span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .feature-rate { display:flex; align-items:center; gap:8px; margin-top:10px; }
        .feature-rate .slider { flex:1; width:auto; }
        .route-select { min-width:130px; border:1px solid var(--divider-color); border-radius:8px; padding:7px; color:var(--primary-text-color); background:var(--card-background-color); }
        .light-tiles { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:9px; }
        .light-tile { border:1px solid var(--divider-color); border-radius:12px; padding:10px; text-align:center; }
        .heater-temperature-stepper { display:grid; grid-template-columns:38px 1fr 38px; gap:7px; align-items:center; margin-top:10px; }
        .heater-temperature-stepper button { height:35px; border:1px solid var(--divider-color); border-radius:9px; color:var(--primary-text-color); background:var(--card-background-color); font-size:21px; cursor:pointer; }
        ha-textfield.heater-temperature-input { width:100%; --md-filled-text-field-container-color:var(--card-background-color); }
        .light-tile .color-presets { justify-content:center; margin-top:9px; }
        .light-tile .toggle { margin:9px auto 0; }
        .history { min-height:104px; margin-top:10px; display:grid; grid-template-columns:repeat(auto-fit,minmax(135px,1fr)); gap:8px; }
        .history-chart { border:1px solid var(--divider-color); border-radius:10px; padding:8px; }
        .history-chart svg { width:100%; height:62px; overflow:visible; }
        .history-chart polyline { fill:none; stroke:var(--primary-color); stroke-width:2.5; stroke-linejoin:round; stroke-linecap:round; }
        .history-chart polyline.series-1 { stroke:#ff9800; }
        .history-chart polyline.series-2 { stroke:#7e57c2; }
        .history-chart polyline.series-3 { stroke:#26a69a; }
        .series-key { display:inline-block; width:8px; height:8px; margin-right:3px; border-radius:50%; background:var(--primary-color); }
        .series-key.series-1 { background:#ff9800; }
        .series-key.series-2 { background:#7e57c2; }
        .series-key.series-3 { background:#26a69a; }
        .history-chart small { color:var(--secondary-text-color); }
        .empty { padding:18px; text-align:center; color:var(--secondary-text-color); border:1px dashed var(--divider-color); border-radius:12px; }
        details { border-top:1px solid var(--divider-color); margin-top:18px; padding-top:14px; }
        summary { cursor:pointer; font-weight:600; }
        .gauge-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(145px,1fr)); gap:12px; margin-top:14px; }
        .gauge { padding:10px; border:1px solid var(--divider-color); border-radius:12px; text-align:center; }
        .gauge svg { width:112px; height:112px; }
        .gauge .track { fill:none; stroke:var(--divider-color); stroke-width:11; }
        .gauge .progress { fill:none; stroke:var(--primary-color); stroke-width:11; stroke-linecap:round; }
        .gauge.temperature-cool .progress { stroke:#2196f3; }
        .gauge.temperature-warm .progress { stroke:#ff9800; }
        .gauge.temperature-hot .progress { stroke:#f44336; }
        .gauge-value { margin-top:-72px; min-height:63px; display:flex; flex-direction:column; align-items:center; justify-content:center; }
        .gauge-value strong { font-size:1.1rem; }
        .gauge-value small, .gauge-label { color:var(--secondary-text-color); font-size:.74rem; }
        .diagnostics { margin-top:14px; }
        .diagnostic-row { display:flex; justify-content:space-between; gap:12px; padding:8px 0; border-top:1px solid var(--divider-color); font-size:.88rem; }
        .diagnostic-row span:last-child { color:var(--secondary-text-color); text-align:right; }
        @media (max-width:560px) { ha-card { padding:14px; } .overview { grid-template-columns:repeat(2,1fr); } .actions { gap:5px; } .slider { width:80px; } .effect { display:none; } }
      </style>
      <ha-card>
        <div class="header"><img class="poolside-icon" src="/poolside/icons/pool.png" alt=""><h2></h2></div>
        <p class="subtitle">Safe controls follow the confirmed Poolside cloud state.</p>
        <div class="mode-rail"></div>
        <div class="overview"></div>
        <div class="live-gauge-grid"></div>
        <section class="trend section"><div class="section-head"><h3>Water and chemistry — 24 hours</h3></div><div class="history" data-history="overview"></div></section>
        <section class="home section"><div class="home-content"></div></section>
        <details class="advanced"><summary>Diagnostics</summary><p class="hint">Live read-only controller telemetry. Physical equipment and valves are never controlled here.</p><div class="gauge-grid"></div><div class="diagnostics"></div></details>
      </ha-card>`;
    this._render();
  }

  set hass(hass) { this._hass = hass; this._render(); }

  _render() {
    if (!this._hass || !this.config) return;
    this.shadowRoot.querySelector("h2").textContent = this.config.name || "Poolside";
    const modeEntity = this._resolveModeEntity();
    const mode = modeEntity ? this._hass.states[modeEntity] : undefined;
    if (!mode) return this._renderUnavailable();

    const discovered = this._discoverEntities(mode);
    const configured = (key, fallback, allowed) => {
      const ids = Array.isArray(this.config[key]) ? this.config[key].filter((id) => this._hass.states[id] && allowed(id)) : [];
      return ids.length ? ids : fallback;
    };
    const safeControl = (id) => ["switch", "light", "number", "fan", "climate", "select"].includes(id.split(".")[0]);
    // A hand-picked diagnostics list is additive.  Replacing discovery here can
    // hide the authoritative Water Thermistor and leave a pump drive temperature
    // as the only temperature available in the overview.
    const configuredDiagnostics = configured("shared_entities", [], (id) => ["sensor", "binary_sensor"].includes(id.split(".")[0]));
    const diagnostics = [...new Set([...discovered.telemetry, ...configuredDiagnostics])];
    const pool = configured("pool_entities", discovered.pool, safeControl);
    const spa = configured("spa_entities", discovered.spa, safeControl);
    const allControls = [...new Set([...pool, ...spa])].filter((id) => this._isDisplayableControl(this._hass.states[id]));
    const selected = String(mode.state || "Off").toLowerCase();
    const activeControls = selected === "pool" ? pool : selected === "spa" ? spa : [];
    const liveLights = allControls.filter((id) => id.startsWith("light.") && !this._unavailable(this._hass.states[id]));
    const running = activeControls.filter((id) => {
      const state = this._hass.states[id];
      return state && !this._unavailable(state) && state.state === "on";
    });
    const homeData = this._discoverHomeData();
    this._renderModes(mode, modeEntity);
    this._renderOverview(mode, allControls, liveLights, diagnostics);
    this._renderHome(mode, activeControls, liveLights, running, homeData.chemistry, homeData.schedules);
    this._renderLiveGauges(diagnostics);
    this._renderAdvanced(diagnostics, homeData.chemistry);
  }

  _renderUnavailable() {
    this.shadowRoot.querySelector(".mode-rail").innerHTML = "";
    this.shadowRoot.querySelector(".overview").innerHTML = '<div class="empty">Poolside is reconnecting. The active-body selector is unavailable.</div>';
    this.shadowRoot.querySelector(".home-content").innerHTML = "";
  }

  _renderModes(mode, modeEntity) {
    const rail = this.shadowRoot.querySelector(".mode-rail");
    rail.innerHTML = "";
    const transition = mode.attributes?.transition_state;
    if (transition) {
      rail.innerHTML = `<div class="empty">Changing flow: ${this._escape(transition)}. Circulation may pause while Poolside moves the valves.</div>`;
      return;
    }
    (Array.isArray(mode.attributes.options) ? mode.attributes.options : ["Off"]).forEach((option) => {
      const button = document.createElement("button");
      button.className = `mode ${option === mode.state ? "active" : ""}`;
      const icon = this._bodyIconPath(option);
      button.innerHTML = `${icon ? `<img class="poolside-icon" src="${icon}" alt="">` : ""}${this._escape(option)}`;
      button.addEventListener("click", () => this._select(option, mode.state, modeEntity));
      rail.appendChild(button);
    });
  }

  _renderOverview(mode, allControls, liveLights, telemetry) {
    const findTelemetry = (patterns, fallback = "—") => {
      const candidates = telemetry.map((id) => this._hass.states[id]).filter((item) => item && !this._unavailable(item));
      const state = patterns.map((pattern) => candidates.find((item) => pattern.test(this._identity(item)))).find(Boolean);
      return state ? this._stateValue(state) : fallback;
    };
    const findControl = (pattern) => allControls.map((id) => this._hass.states[id]).find((item) => item && pattern.test(this._identity(item)));
    const heater = findControl(/heater/);
    const circulation = findControl(/filter|pump|circulation/);
    const features = allControls.map((id) => this._hass.states[id]).filter((item) => item && /(bubbler|blower|cleaner|spill|jets)/.test(this._identity(item)));
    const water = telemetry.map((id) => this._hass.states[id]).find((item) => item && !this._unavailable(item) && /water.*(thermistor|temp)|thermometer.*water/.test(this._identity(item)));
    const air = telemetry.map((id) => this._hass.states[id]).find((item) => item && !this._unavailable(item) && /air.*temp|ambient.*temp|outside.*temp/.test(this._identity(item)));
    const stats = [["mdi:pool", "Mode", mode.state]];
    if (water) {
      const temperature = Number(water.state);
      const temperatureClass = Number.isFinite(temperature) ? temperature <= 75 ? "water-temperature-cool" : temperature >= 90 ? "water-temperature-hot" : "water-temperature-warm" : "";
      const label = air ? `Water ${this._stateValue(water)}\nAir ${this._stateValue(air)}` : `Water ${this._stateValue(water)}`;
      stats.push(["mdi:thermometer-water", "Temperature", label, `${temperatureClass}${air ? " temperature-with-air" : ""}`]);
    }
    const pumpRpms = telemetry.map((id) => this._hass.states[id]).filter((item) => item && !this._unavailable(item) && /pump.*rpm/.test(this._identity(item)));
    pumpRpms.forEach((rpm) => {
      const label = this._telemetryLabel(rpm).replace(/\s+RPM$/i, "");
      const prefix = label.toLowerCase();
      const speed = telemetry.map((id) => this._hass.states[id]).find((item) => item && !this._unavailable(item) && this._telemetryLabel(item).toLowerCase() === `${prefix} actual speed percent`);
      const percentage = speed && Number.isFinite(Number(speed.state)) ? Number(speed.state) : Number(rpm.state) / 34.5;
      const status = Number(rpm.state) > 0 || circulation?.state === "on" ? `${this._formatNumber(percentage)}% · ${this._stateValue(rpm)}` : `Off · ${this._stateValue(rpm)}`;
      stats.push(["mdi:pump", label, status]);
    });
    if (heater && heater.state === "on") stats.push(["mdi:fire", "Heating", "On"]);
    if (liveLights.length) stats.push(["mdi:lightbulb-group", "Lights", `${liveLights.filter((id) => this._hass.states[id]?.state === "on").length}/${liveLights.length}`]);
    if (features.some((item) => item.state === "on")) stats.push(["mdi:water", "Features", `${features.filter((item) => item.state === "on").length} active`]);
    this.shadowRoot.querySelector(".overview").innerHTML = stats.map(([icon, label, value, className = ""]) => `<div class="stat ${className}"><span class="stat-label"><ha-icon icon="${icon}"></ha-icon>${this._escape(label)}</span><span class="stat-value">${this._escape(value)}</span></div>`).join("");
  }

  _renderHome(mode, activeControls, allLights, running, chemistry, schedules) {
    const target = this.shadowRoot.querySelector(".home-content");
    const panels = [];
    const lights = allLights.length && allLights.length <= 3 ? this._individualLights(allLights) : this._allLightsControl(allLights);
    if (lights) panels.push(lights);
    const groups = this._groups(activeControls);
    const heater = this._heaterCard(groups.heating);
    if (heater) panels.push(heater);
    const features = this._featureCards([...groups.circulation, ...groups.features, ...groups.other]);
    if (features) panels.push(`<div class="panel"><div class="panel-title"><img class="poolside-icon" src="/poolside/icons/fountain.png" alt="">Water features</div><div class="features">${features}</div></div>`);
    if (schedules.length) panels.push(`<div class="panel"><div class="panel-title"><ha-icon icon="mdi:calendar-clock"></ha-icon>Schedules</div>${schedules.map((schedule) => `<div class="row"><div><strong>${this._escape(schedule.title)}</strong><div class="schedule-time">${this._escape(schedule.time)}</div></div></div>`).join("")}<p class="hint">Schedules are shown from Poolside. Editing remains in the Poolside app until its conflict-safe schedule write procedure is verified.</p></div>`);
    const resting = String(mode.state).toLowerCase() === "off" ? "Choose Pool or Spa to change the dashboard view. Off asks Poolside to turn off only active water-flow Controls in this connected group; lights and saved settings remain unchanged." : `No Poolside equipment is currently running in ${mode.state}.`;
    target.innerHTML = panels.length ? `<div class="home-grid">${panels.join("")}</div>` : `<div class="empty"><strong>Everything is resting.</strong><br><span class="hint">${this._escape(resting)}</span></div>`;
    this._wireControls(target);
  }

  _individualLights(lightIds) {
    const tiles = lightIds.map((id) => this._lightTile(id)).filter(Boolean);
    return tiles.length ? `<div class="panel"><div class="panel-title"><ha-icon icon="mdi:lightbulb-group"></ha-icon>Lights</div><div class="light-tiles">${tiles.join("")}</div></div>` : "";
  }

  _lightTile(entityId) {
    const state = this._hass.states[entityId];
    if (!this._isDisplayableControl(state)) return "";
    const rgb = Array.isArray(state.attributes.rgb_color) ? state.attributes.rgb_color : [0, 153, 204];
    const color = `#${rgb.map((channel) => Math.max(0, Math.min(255, Number(channel) || 0)).toString(16).padStart(2, "0")).join("")}`;
    const presets = [["Red", "#ff4500"], ["Blue", "#2164f3"], ["Green", "#20d34a"], ["Purple", "#b900f5"], ["White", "#fffefa"], ["Warm", "#ffa45a"]];
    return `<div class="light-tile"><strong>${this._escape(this._controlLabel(state))}</strong><div class="hint">${this._escape(this._status(state))}</div><ha-slider class="native-light-slider" min="0" max="255" step="1" value="${Number(state.attributes.brightness) || 0}" data-entity="${entityId}" aria-label="${this._escape(this._controlLabel(state))} brightness"></ha-slider><div class="color-presets">${presets.map(([name, value]) => `<button class="color-preset light-preset" title="${name}" aria-label="Set ${this._escape(this._controlLabel(state))} ${name}" style="background:${value}" data-entity="${entityId}" data-color="${value}"></button>`).join("")}</div>${this._nativeSwitch(entityId, state.state === "on", this._controlLabel(state))}</div>`;
  }

  _heaterCard(ids) {
    const states = ids.map((id) => this._hass.states[id]).filter((state) => this._isDisplayableControl(state));
    if (!states.length) return "";
    const heaterSwitch = states.find((state) => state.entity_id.startsWith("switch."));
    const climate = states.find((state) => state.entity_id.startsWith("climate."));
    const setpoint = states.find((state) => state.entity_id.startsWith("number."));
    const heater = heaterSwitch || climate;
    if (!heater && !setpoint) return "";
    const on = heaterSwitch ? heaterSwitch.state === "on" : climate?.state === "heat";
    const name = this._controlLabel(climate || heaterSwitch || setpoint);
    const temperatureEntity = climate || setpoint;
    const slider = temperatureEntity ? this._heaterTemperatureInput(temperatureEntity) : "";
    const toggle = heaterSwitch ? this._nativeSwitch(heaterSwitch.entity_id, on, name) : climate ? this._nativeSwitch(climate.entity_id, on, name, `data-climate-next="${on ? "off" : "heat"}"`) : "";
    const temperature = climate ? Number(climate.attributes.target_temperature) : Number(setpoint?.state);
    const temperatureColor = this._temperatureColor(temperature);
    return `<div class="panel heater ${on ? "active" : ""}" style="--heater-temp-color:${temperatureColor}"><div class="panel-title"><ha-icon icon="mdi:fire"></ha-icon>${this._escape(name)}</div><div class="row"><span>${on ? "Heating" : "Off"}</span>${toggle}</div>${slider}</div>`;
  }

  _temperatureColor(value) {
    const ratio = Math.max(0, Math.min(1, ((Number(value) || 32) - 32) / 72));
    const start = [33, 150, 243];
    const end = [244, 67, 54];
    return `rgb(${start.map((channel, index) => Math.round(channel + (end[index] - channel) * ratio)).join(", ")})`;
  }

  _heaterTemperatureInput(state) {
    const climate = state.entity_id.startsWith("climate.");
    const value = climate ? Number(state.attributes.target_temperature) : Number(state.state);
    const min = climate ? Number(state.attributes.min_temp ?? 32) : Number(state.attributes.min ?? 32);
    const max = climate ? Number(state.attributes.max_temp ?? 110) : Number(state.attributes.max ?? 110);
    const entity = this._escape(state.entity_id);
    return `<div class="heater-temperature-stepper"><button class="heater-temperature-minus" data-entity="${entity}" data-domain="${climate ? "climate" : "number"}" aria-label="Decrease temperature">−</button><ha-textfield class="heater-temperature-input" type="number" value="${Number.isFinite(value) ? this._formatNumber(value) : min}" min="${min}" max="${max}" data-entity="${entity}" data-domain="${climate ? "climate" : "number"}" aria-label="${this._escape(this._controlLabel(state))} temperature"></ha-textfield><button class="heater-temperature-plus" data-entity="${entity}" data-domain="${climate ? "climate" : "number"}" aria-label="Increase temperature">+</button></div><span class="value">°F · ${min}–${max} °F</span>`;
  }

  _featureCards(ids) {
    const grouped = new Map();
    const routes = new Map();
    ids.forEach((id) => {
      const state = this._hass.states[id];
      if (!this._isDisplayableControl(state)) return;
      const routeKey = state.attributes?.poolside_route_group;
      if (routeKey) {
        const route = routes.get(routeKey) || [];
        route.push(state);
        routes.set(routeKey, route);
        return;
      }
      const key = this._controlLabel(state).replace(/ power level$/i, "").toLowerCase();
      const item = grouped.get(key) || { states: [], label: this._controlLabel(state).replace(/ power level$/i, "") };
      item.states.push(state);
      grouped.set(key, item);
    });
    const routeCards = [...routes.values()].map((states) => this._routeFeatureCard(states)).filter(Boolean);
    const controlCards = [...grouped.values()].map(({ states, label }) => {
      const toggle = states.find((state) => state.entity_id.startsWith("switch.") || state.entity_id.startsWith("fan."));
      const rate = states.find((state) => state.entity_id.startsWith("number."));
      const fan = states.find((state) => state.entity_id.startsWith("fan."));
      const on = toggle?.entity_id.startsWith("fan.") ? toggle.state === "on" : toggle?.state === "on";
      const action = toggle ? this._nativeSwitch(toggle.entity_id, on, label) : "";
      const rateControl = fan ? this._fanInput(fan) : rate ? this._numberInput(rate, "feature-number") : "";
      const representative = toggle || rate || fan;
      return `<div class="feature ${on ? "active" : ""}"><div class="row"><div class="feature-title">${this._controlIconMarkup(representative, representative.entity_id)}<span>${this._escape(label)}</span></div>${action}</div>${rateControl ? `<div class="feature-rate">${rateControl}</div>` : ""}</div>`;
    });
    return [...routeCards, ...controlCards].join("");
  }

  _routeFeatureCard(states) {
    const master = states.find((state) => state.attributes?.poolside_control_kind === "route_group");
    const selection = states.find((state) => state.entity_id.startsWith("select."));
    if (!master || !selection) return "";
    const selected = String(selection.state || "");
    const rates = states.filter((state) => state.entity_id.startsWith("number.") && state.attributes?.poolside_route_member)
      .filter((state) => selected === "Blend" || this._controlLabel(state).toLowerCase().includes(selected.toLowerCase()));
    const on = master.state === "on";
    const choices = Array.isArray(selection.attributes.options) ? selection.attributes.options : [];
    const options = choices.map((option) => `<option value="${this._escape(option)}" ${option === selected ? "selected" : ""}>${this._escape(option)}</option>`).join("");
    const label = this._controlLabel(master).replace(/ routes?$/i, "");
    return `<div class="feature ${on ? "active" : ""}"><div class="row"><div class="feature-title">${this._controlIconMarkup(master, master.entity_id)}<span>${this._escape(label)}</span></div>${this._nativeSwitch(master.entity_id, on, label)}</div><div class="row"><span class="hint">Route</span><select class="route-select" data-entity="${this._escape(selection.entity_id)}" aria-label="${this._escape(label)} route">${options}</select></div>${rates.map((state) => `<div class="feature-rate"><span class="hint">${this._escape(this._controlLabel(state).replace(/ power level$/i, ""))}</span>${this._numberInput(state, "feature-number")}</div>`).join("")}</div>`;
  }

  _numberInput(state, className) {
    const value = Number(state.state);
    const min = Number(state.attributes.min ?? 0);
    const max = Number(state.attributes.max ?? 100);
    const unit = /power level/i.test(this._controlLabel(state)) ? "%" : state.attributes.unit_of_measurement || "";
    return `<ha-slider class="slider number ${className}" min="${min}" max="${max}" step="${state.attributes.step || 1}" value="${Number.isFinite(value) ? value : min}" data-entity="${state.entity_id}" aria-label="${this._escape(this._controlLabel(state))}"></ha-slider><span class="value">${Number.isFinite(value) ? this._escape(`${this._formatNumber(value)} ${unit}`) : "—"}</span>`;
  }

  _fanInput(state) {
    const percentage = Number(state.attributes.percentage);
    return `<ha-slider class="slider fan-percentage" min="0" max="100" step="1" value="${Number.isFinite(percentage) ? percentage : 0}" data-entity="${state.entity_id}" aria-label="${this._escape(this._controlLabel(state))} speed"></ha-slider><span class="value">${Number.isFinite(percentage) ? this._formatNumber(percentage) : "—"}%</span>`;
  }

  _allLightsControl(lightIds) {
    const states = lightIds.map((id) => this._hass.states[id]).filter(Boolean);
    if (!states.length) return "";
    const allOn = states.every((state) => state.state === "on");
    const active = states.some((state) => state.state === "on");
    const brightest = Math.max(...states.map((state) => Number(state.attributes.brightness) || 0));
    const rgb = states.find((state) => Array.isArray(state.attributes.rgb_color))?.attributes.rgb_color || [0, 153, 204];
    const color = `#${rgb.map((channel) => Math.max(0, Math.min(255, Number(channel) || 0)).toString(16).padStart(2, "0")).join("")}`;
    const ids = this._escape(lightIds.join(","));
    const presets = [["Aqua", "#0099cc"], ["Blue", "#2164f3"], ["Green", "#20b25b"], ["Purple", "#8e44d8"], ["Red", "#df3c3c"], ["White", "#ffffff"]];
    return `<div class="panel all-lights"><div class="panel-title"><ha-icon icon="mdi:lightbulb-group"></ha-icon>All lights</div><div class="row"><div class="label"><span>${states.length} Poolside lights</span></div><div class="actions"><ha-slider class="slider all-lights-brightness" min="1" max="255" step="1" value="${brightest || 255}" data-lights="${ids}" aria-label="All Poolside lights brightness"></ha-slider><input class="color all-lights-color" type="color" value="${color}" data-lights="${ids}" aria-label="All Poolside lights color"><ha-switch class="all-lights-toggle" data-lights="${ids}" aria-label="Toggle all Poolside lights" ${active ? "checked" : ""}></ha-switch></div></div><div class="color-presets" aria-label="All Poolside lights color presets">${presets.map(([name, value]) => `<button class="color-preset all-lights-preset" title="${name}" aria-label="Set all Poolside lights ${name}" aria-pressed="${color.toLowerCase() === value ? "true" : "false"}" style="background:${value}" data-lights="${ids}" data-color="${value}"></button>`).join("")}</div></div>`;
  }

  _renderLiveGauges(telemetry) {
    const states = telemetry.map((id) => this._hass.states[id]).filter((state) => state && this._isUsefulTelemetry(state));
    const gaugeStates = states.filter((state) => {
      const identity = this._identity(state);
      return /pressure|water.*(temperature|thermistor)|ambient.*temperature|air.*temperature|pump.*rpm/.test(identity) && this._isGaugeTelemetry(state);
    });
    this.shadowRoot.querySelector(".live-gauge-grid").innerHTML = gaugeStates.length ? gaugeStates.map((state) => this._gauge(state)).join("") : "";
  }

  _renderAdvanced(telemetry, chemistry = []) {
    const states = telemetry.map((id) => this._hass.states[id]).filter((state) => state && this._isUsefulTelemetry(state));
    const chemistryPanel = chemistry.length ? `<div class="panel"><div class="panel-title"><ha-icon icon="mdi:flask-outline"></ha-icon>Water chemistry</div><ul class="metric-list">${chemistry.map((state) => `<li><span>${this._escape(this._telemetryLabel(state))}</span><strong>${this._escape(this._stateValue(state))}</strong></li>`).join("")}</ul></div>` : "";
    this.shadowRoot.querySelector(".gauge-grid").innerHTML = chemistryPanel;
    this.shadowRoot.querySelector(".diagnostics").innerHTML = states.length ? states.map((state) => `<div class="diagnostic-row"><span>${this._escape(this._telemetryLabel(state))}</span><span>${this._escape(this._stateValue(state))}</span></div>`).join("") : '<p class="hint">No controller telemetry has been reported.</p>';
    this._loadHistory([...this._temperatureStates(), ...this._ambientTemperatureStates(), ...chemistry]);
  }

  _gauge(state) {
    const identity = this._identity(state);
    const value = Number(state.state);
    const [min, max] = state.attributes.min !== undefined && state.attributes.max !== undefined ? [Number(state.attributes.min), Number(state.attributes.max)] : identity.includes("pressure") ? [0, 50] : identity.includes("speedpercent") ? [0, 100] : identity.includes("rpm") ? [0, 3450] : identity.includes("flow") ? [0, 150] : [32, 150];
    const percent = Number.isFinite(value) ? Math.max(0, Math.min(100, ((value - min) / Math.max(1, max - min)) * 100)) : 0;
    const circumference = 282.7;
    const arc = circumference * (5 / 6);
    const progress = arc * (percent / 100);
    const label = this._telemetryLabel(state);
    const unit = this._unitFor(state);
    const displayValue = /pump.*rpm/.test(identity) && Number.isFinite(value) ? `${this._formatNumber(value / 34.5)}%` : Number.isFinite(value) ? this._formatNumber(value) : "—";
    const displayUnit = /pump.*rpm/.test(identity) && Number.isFinite(value) ? `${this._formatNumber(value)} ${unit}` : unit;
    const temperatureClass = /temperature|thermistor/.test(identity) ? value <= 75 ? "temperature-cool" : value >= 90 ? "temperature-hot" : "temperature-warm" : "";
    return `<div class="gauge ${temperatureClass}"><svg viewBox="0 0 112 112" aria-label="${this._escape(label)}"><circle class="track" cx="56" cy="56" r="45" transform="rotate(120 56 56)" stroke-dasharray="${arc} ${circumference - arc}"></circle><circle class="progress" cx="56" cy="56" r="45" transform="rotate(120 56 56)" stroke-dasharray="${progress} ${circumference - progress}"></circle></svg><div class="gauge-value"><strong>${this._escape(displayValue)}</strong><small>${this._escape(displayUnit)}</small></div><div class="gauge-label">${this._escape(label)}</div></div>`;
  }

  _control(entityId) {
    const state = this._hass.states[entityId];
    if (!state) return "";
    const domain = entityId.split(".")[0];
    const name = this._escape(state.attributes.friendly_name || entityId);
    const unavailable = this._unavailable(state);
    const disabled = unavailable ? "disabled" : "";
    const icon = this._iconFor(state, entityId);
    if (domain === "number") {
      const value = Number(state.state);
      const min = Number(state.attributes.min ?? 0);
      const max = Number(state.attributes.max ?? 100);
      return `<div class="row"><div class="label"><ha-icon icon="${icon}"></ha-icon><span>${name}</span></div><div class="actions"><ha-slider class="slider number" min="${min}" max="${max}" step="${state.attributes.step || 1}" value="${Number.isFinite(value) ? value : min}" data-entity="${entityId}" ${disabled}></ha-slider><span class="value">${Number.isFinite(value) ? this._escape(`${value} ${state.attributes.unit_of_measurement || ""}`) : "—"}</span></div></div>`;
    }
    if (domain === "fan") {
      return `<div class="row"><div class="label"><ha-icon icon="${icon}"></ha-icon><span>${name}</span></div><div class="actions">${this._fanInput(state)}${this._nativeSwitch(entityId, state.state === "on", this._controlLabel(state), disabled)}</div></div>`;
    }
    const active = state.state === "on";
    const attrs = state.attributes;
    const isLight = domain === "light";
    const rgb = Array.isArray(attrs.rgb_color) ? attrs.rgb_color : [0, 153, 204];
    const color = `#${rgb.map((channel) => Math.max(0, Math.min(255, Number(channel) || 0)).toString(16).padStart(2, "0")).join("")}`;
    const brightness = isLight ? `<ha-slider class="native-light-slider" min="0" max="255" step="1" value="${Number(attrs.brightness) || 0}" data-entity="${entityId}" aria-label="${name} brightness" ${disabled}></ha-slider>` : "";
    const colorInput = isLight ? `<input class="color light-color" type="color" value="${color}" data-entity="${entityId}" aria-label="${name} color" ${disabled}>` : "";
    return `<div class="row"><div class="label"><ha-icon icon="${icon}"></ha-icon><span>${name}</span></div><div class="actions">${brightness}${colorInput}${this._nativeSwitch(entityId, active, this._controlLabel(state), disabled)}</div></div>`;
  }

  _nativeSwitch(entityId, checked, label, disabled = "") {
    return `<ha-switch class="toggle" data-entity="${entityId}" aria-label="Toggle ${this._escape(label)}" ${checked ? "checked" : ""} ${disabled}></ha-switch>`;
  }

  _wireControls(scope) {
    scope.querySelectorAll("ha-switch.toggle[data-entity]").forEach((button) => button.addEventListener("change", () => {
      const entityId = button.dataset.entity;
      const domain = entityId.split(".")[0];
      if (domain === "climate") return this._hass.callService("climate", "set_hvac_mode", { entity_id: entityId, hvac_mode: button.dataset.climateNext || "off" });
      return this._hass.callService(domain === "light" ? "light" : domain, "toggle", { entity_id: entityId });
    }));
    scope.querySelectorAll(".number").forEach((input) => input.addEventListener("change", () => this._hass.callService("number", "set_value", { entity_id: input.dataset.entity, value: Number(input.value) })));
    scope.querySelectorAll(".fan-percentage").forEach((input) => input.addEventListener("change", () => this._hass.callService("fan", "set_percentage", { entity_id: input.dataset.entity, percentage: Number(input.value) })));
    scope.querySelectorAll(".route-select").forEach((input) => input.addEventListener("change", () => this._hass.callService("select", "select_option", { entity_id: input.dataset.entity, option: input.value })));
    scope.querySelectorAll(".light-brightness").forEach((input) => input.addEventListener("change", () => this._hass.callService("light", "turn_on", { entity_id: input.dataset.entity, brightness: Number(input.value) })));
    scope.querySelectorAll(".native-light-slider").forEach((input) => input.addEventListener("change", () => this._hass.callService("light", "turn_on", { entity_id: input.dataset.entity, brightness: Number(input.value) })));
    const adjustTemperature = (input, delta) => {
      const state = this._hass.states[input.dataset.entity];
      const current = input.value;
      const min = Number(input.min || 32);
      const max = Number(input.max || 110);
      const value = Math.max(min, Math.min(max, Math.round((Number(current) || Number(state?.attributes?.target_temperature ?? state?.state) || 32) + delta)));
      input.value = String(value);
      const service = input.dataset.domain === "climate" ? "climate" : "number";
      const data = service === "climate" ? { entity_id: input.dataset.entity, temperature: value } : { entity_id: input.dataset.entity, value };
      this._hass.callService(service, service === "climate" ? "set_temperature" : "set_value", data);
    };
    scope.querySelectorAll(".heater-temperature-minus").forEach((button) => button.addEventListener("click", () => adjustTemperature(button.parentElement.querySelector(".heater-temperature-input"), -1)));
    scope.querySelectorAll(".heater-temperature-plus").forEach((button) => button.addEventListener("click", () => adjustTemperature(button.parentElement.querySelector(".heater-temperature-input"), 1)));
    scope.querySelectorAll(".heater-temperature-input").forEach((input) => input.addEventListener("change", () => adjustTemperature(input, 0)));
    scope.querySelectorAll(".light-color").forEach((input) => input.addEventListener("change", () => {
      const raw = input.value.slice(1);
      this._hass.callService("light", "turn_on", { entity_id: input.dataset.entity, rgb_color: [0, 2, 4].map((offset) => parseInt(raw.slice(offset, offset + 2), 16)) });
    }));
    scope.querySelectorAll(".light-preset").forEach((button) => button.addEventListener("click", () => {
      const raw = button.dataset.color.slice(1);
      this._hass.callService("light", "turn_on", { entity_id: button.dataset.entity, rgb_color: [0, 2, 4].map((offset) => parseInt(raw.slice(offset, offset + 2), 16)) });
    }));
    scope.querySelectorAll("ha-switch.all-lights-toggle").forEach((button) => button.addEventListener("change", () => {
      const entityIds = this._lightIds(button.dataset.lights);
      const allOn = entityIds.every((id) => this._hass.states[id]?.state === "on");
      this._hass.callService("light", allOn ? "turn_off" : "turn_on", { entity_id: entityIds });
    }));
    scope.querySelectorAll(".all-lights-brightness").forEach((input) => input.addEventListener("change", () => this._hass.callService("light", "turn_on", { entity_id: this._lightIds(input.dataset.lights), brightness: Number(input.value) })));
    scope.querySelectorAll(".all-lights-color, .all-lights-preset").forEach((input) => input.addEventListener(input.classList.contains("all-lights-preset") ? "click" : "change", () => {
      const raw = (input.dataset.color || input.value).slice(1);
      this._hass.callService("light", "turn_on", { entity_id: this._lightIds(input.dataset.lights), rgb_color: [0, 2, 4].map((offset) => parseInt(raw.slice(offset, offset + 2), 16)) });
    }));
  }

  _groups(ids) {
    const groups = { heating: [], circulation: [], lights: [], features: [], other: [] };
    ids.forEach((id) => {
      const identity = this._identity(this._hass.states[id]);
      if (id.startsWith("light.")) groups.lights.push(id);
      else if (/heater|temperature|setpoint/.test(identity)) groups.heating.push(id);
      else if (/filter|pump|circulation/.test(identity)) groups.circulation.push(id);
      else if (/bubbler|blower|cleaner|spill|jets/.test(identity)) groups.features.push(id);
      else groups.other.push(id);
    });
    return groups;
  }

  _discoverEntities(mode) {
    const result = { pool: [], spa: [], telemetry: [] };
    const bodyIds = Object.entries(mode.attributes?.poolside_body_ids || {});
    const bodyId = (label) => bodyIds.find(([option]) => option.toLowerCase() === label)?.[1];
    const poolBodyId = bodyId("pool");
    const spaBodyId = bodyId("spa");
    Object.entries(this._hass.states).forEach(([id, state]) => {
      const name = String(state.attributes.friendly_name || "").toLowerCase();
      const identity = `${name} ${id.toLowerCase()}`;
      const domain = id.split(".")[0];
      const scope = state.attributes?.poolside_body_id;
      const poolside = Boolean(scope) || id.includes("poolside") || /^(pool|spa)\b/.test(name);
      if (!poolside) return;
      if (["switch", "light", "number", "fan", "climate"].includes(domain)) {
        if (scope && scope === poolBodyId) result.pool.push(id);
        else if (scope && scope === spaBodyId) result.spa.push(id);
      }
      if (domain === "select" && state.attributes?.controller_derived) {
        if (scope && scope === poolBodyId) result.pool.push(id);
        else if (scope && scope === spaBodyId) result.spa.push(id);
      }
      if (["sensor", "binary_sensor"].includes(domain) && /(rpm|speed|flow|pressure|temperature|thermometer|ph|chlorine|orp|firmware|version|fault|online)/.test(identity)) result.telemetry.push(id);
    });
    return result;
  }

  _discoverHomeData() {
    const chemistry = [];
    const schedules = [];
    const configuredScheduleIds = Array.isArray(this.config.schedule_entities)
      ? this.config.schedule_entities.filter((id) => id.startsWith("calendar.") && this._hass.states[id])
      : [];
    Object.entries(this._hass.states).forEach(([id, state]) => {
      const identity = this._identity(state);
      const isPoolside = id.includes("poolside") || /^(pool|spa)\b/.test(String(state.attributes.friendly_name || "").toLowerCase());
      if (!isPoolside || this._unavailable(state)) return;
      if (id.startsWith("sensor.") && /(\bph\b|orp|chlorine|salt|alkalinity|calcium|stabilizer|cyanuric|chemical)/.test(identity) && this._isNumericState(state)) chemistry.push(state);
      if (id.startsWith("calendar.") || /schedule|next.*(run|event|schedule)/.test(identity)) {
        const schedule = this._scheduleInfo(state);
        if (schedule) schedules.push(schedule);
      }
    });
    configuredScheduleIds.forEach((id) => {
      const schedule = this._scheduleInfo(this._hass.states[id]);
      if (schedule) schedules.push(schedule);
    });
    return {
      chemistry: chemistry.sort((left, right) => this._telemetryLabel(left).localeCompare(this._telemetryLabel(right))).slice(0, 6),
      schedules: [...new Map(schedules.map((schedule) => [`${schedule.title}|${schedule.at}`, schedule])).values()].sort((left, right) => left.at - right.at).slice(0, 4),
    };
  }

  _scheduleInfo(state) {
    const attrs = state.attributes || {};
    const source = attrs.start_time || attrs.next_event || attrs.next_run || attrs.next_run_time;
    const at = source ? Date.parse(source) : NaN;
    if (!Number.isFinite(at)) return null;
    const title = attrs.message || attrs.summary || attrs.description || this._telemetryLabel(state);
    const date = new Date(at);
    const time = date.toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
    return { title, time, at };
  }

  async _select(option, current, entityId) {
    if (option === current) return;
    if (option.toLowerCase() === "off" && !window.confirm("Turn off active water-flow Controls for this connected group? Poolside will preserve lights, saved set points, schedules, and diagnostics.")) return;
    await this._hass.callService("select", "select_option", { entity_id: entityId, option });
  }

  _resolveModeEntity() {
    if (this._hass.states[this.config.mode_entity]) return this.config.mode_entity;
    return Object.entries(this._hass.states).find(([id, state]) => {
      const options = state?.attributes?.options;
      return id.startsWith("select.")
        && Object.hasOwn(state.attributes || {}, "confirmed_water_flow")
        && Array.isArray(options)
        && options.includes("Off")
        && options.length > 1;
    })?.[0];
  }

  _lightIds(value) { return String(value || "").split(",").filter((id) => id.startsWith("light.") && this._hass.states[id]); }

  _identity(state) { return `${state?.attributes?.friendly_name || ""} ${state?.entity_id || ""}`.toLowerCase(); }
  _unavailable(state) { return !state || ["unavailable", "unknown"].includes(state.state); }
  _status(state) { return this._unavailable(state) ? "Unavailable" : state.state === "on" ? "On" : state.state === "off" ? "Off" : this._stateValue(state); }
  _isNumericState(state) { return Number.isFinite(Number(state?.state)); }
  _isDisplayableControl(state) {
    return Boolean(state && !this._unavailable(state) && state.attributes?.entity_registry_enabled !== false && state.attributes?.disabled !== true);
  }
  _stateValue(state) {
    const raw = this._isNumericState(state) ? this._formatNumber(Number(state.state)) : state.state;
    return `${raw} ${this._unitFor(state)}`.trim();
  }
  _formatNumber(value) { return Number.isInteger(value) ? String(value) : value.toFixed(2).replace(/\.0+$/, "").replace(/(\.\d)0$/, "$1"); }
  _unitFor(state) {
    if (state.attributes.unit_of_measurement) return state.attributes.unit_of_measurement;
    const identity = this._identity(state);
    if (/pressurepsi/.test(identity)) return "psi";
    if (/rpm/.test(identity)) return "rpm";
    if (/speedpercent/.test(identity)) return "%";
    if (/temperaturef|thermistor.*temperature/.test(identity)) return "°F";
    return "";
  }
  _telemetryLabel(state) {
    return String(state.attributes.friendly_name || "Telemetry")
      .replace(/^Poolside\s+/i, "")
      .replace(/([a-z])([A-Z])/g, "$1 $2")
      .replace(/\sF$/, "");
  }
  _controlLabel(state) {
    return String(state?.attributes?.friendly_name || state?.entity_id || "Control")
      .replace(/^Poolside\s+/i, "")
      .replace(/^(Pool|Spa)\s+/i, "")
      .replace(/([a-z])([A-Z])/g, "$1 $2");
  }
  _isUsefulTelemetry(state) {
    const identity = this._identity(state);
    if (/winterized|online/.test(identity)) return false;
    if (/fault/.test(identity)) return !["off", "0", "false"].includes(String(state.state).toLowerCase());
    return /(pressurepsi|pump.*(rpm|speedpercent|temperature)|thermistor.*temperature|flow)/.test(identity);
  }
  _isGaugeTelemetry(state) {
    const identity = this._identity(state);
    return !/winterized|fault|online|desired/.test(identity) && /(pressurepsi|pump.*(rpm|speedpercent|temperature)|thermistor.*temperature|flow)/.test(identity);
  }
  _gaugePriority(state) {
    const identity = this._identity(state);
    if (/pressurepsi/.test(identity)) return 1;
    if (/water.*thermistor/.test(identity)) return 2;
    if (/primary.*pump.*rpm/.test(identity)) return 3;
    if (/feature.*pump.*rpm/.test(identity)) return 4;
    if (/primary.*pump.*drivetemperature/.test(identity)) return 5;
    if (/feature.*pump.*drivetemperature/.test(identity)) return 6;
    if (/thermistor/.test(identity)) return 7;
    return 8;
  }
  _iconFor(state, id) {
    const identity = this._identity(state);
    if (identity.includes("heater")) return "mdi:thermometer-water";
    if (identity.includes("filter")) return "mdi:air-filter";
    if (identity.includes("cleaner")) return "mdi:robot-vacuum";
    if (identity.includes("blower") || identity.includes("pump")) return "mdi:fan";
    if (identity.includes("bubbler") || identity.includes("spill") || identity.includes("jets")) return "mdi:water";
    if (id.startsWith("light.")) return "mdi:lightbulb";
    return id.startsWith("number.") ? "mdi:tune-vertical" : "mdi:toggle-switch-outline";
  }
  _bodyIconPath(value) {
    const identity = String(value || "").toLowerCase();
    if (/spa|hot.?tub/.test(identity)) return "/poolside/icons/spa.png";
    if (/pool/.test(identity)) return "/poolside/icons/pool.png";
    return "";
  }
  _waterFeatureIconPath(state) {
    const identity = this._identity(state);
    if (/bubbler/.test(identity)) return "/poolside/icons/bubbler.png";
    if (/waterfall|spill/.test(identity)) return "/poolside/icons/waterfall.png";
    if (/deck.?jet|stream.?fountain|\bjets?\b/.test(identity)) return "/poolside/icons/deck_jet.png";
    if (/fountain|feature/.test(identity)) return "/poolside/icons/fountain.png";
    return "";
  }
  _controlIconMarkup(state, id) {
    const custom = this._waterFeatureIconPath(state);
    return custom
      ? `<img class="poolside-icon" src="${custom}" alt="">`
      : `<ha-icon icon="${this._iconFor(state, id)}"></ha-icon>`;
  }
  _temperatureStates() {
    return Object.values(this._hass.states).filter((state) => state && !this._unavailable(state) && /water.*(thermistor|temperature)|temperature.*water/.test(this._identity(state)) && this._isNumericState(state));
  }
  _ambientTemperatureStates() {
    return Object.values(this._hass.states).filter((state) => state && !this._unavailable(state) && /air.*temperature|ambient.*temperature|outside.*temperature/.test(this._identity(state)) && this._isNumericState(state));
  }
  async _loadHistory(states) {
    const ids = [...new Set(states.map((state) => state.entity_id))].slice(0, 4);
    if (!ids.length || !this._hass.callApi) return;
    const key = ids.join(",");
    if (this._historyKey === key || this._historyLoading === key) return;
    this._historyLoading = key;
    try {
      const start = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
      const response = await this._hass.callApi("GET", `history/period/${start}?filter_entity_id=${encodeURIComponent(ids.join(","))}&minimal_response`);
      this._historyKey = key;
      this._history = Array.isArray(response) ? response : [];
      this._renderHistory();
    } catch (_error) {
      this._historyKey = key;
      this._history = [];
    } finally {
      this._historyLoading = "";
    }
  }
  _renderHistory() {
    const target = this.shadowRoot.querySelector(".history");
    if (!target || !Array.isArray(this._history)) return;
    const series = this._history.map((rows, index) => {
      const values = (Array.isArray(rows) ? rows : []).map((row) => Number(row.state)).filter(Number.isFinite);
      const state = this._hass.states[rows[0]?.entity_id];
      if (!state || values.length < 2) return null;
      const min = Math.min(...values); const max = Math.max(...values); const range = Math.max(0.01, max - min);
      const points = values.map((value, point) => `${(point / (values.length - 1)) * 100},${58 - ((value - min) / range) * 52}`).join(" ");
      return { index, label: this._telemetryLabel(state), points, range: `${this._formatNumber(min)}–${this._formatNumber(max)} ${this._unitFor(state)}` };
    }).filter(Boolean);
    if (!series.length) {
      target.innerHTML = '<span class="hint">History will appear after Home Assistant records enough readings.</span>';
      return;
    }
    target.innerHTML = `<div class="history-chart"><div class="hint">Water temperature, air temperature, pH, ORP, and chlorine (normalized)</div><svg viewBox="0 0 100 62" preserveAspectRatio="none">${series.map((item) => `<polyline class="series-${item.index}" points="${item.points}"></polyline>`).join("")}</svg><div class="hint">${series.map((item) => `<span style="margin-right:10px"><i class="series-key series-${item.index}"></i>${this._escape(item.label)} ${this._escape(item.range)}</span>`).join("")}</div></div>`;
  }
  _escape(value) { return String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]); }
}

if (!customElements.get("poolside-dashboard")) {
  customElements.define("poolside-dashboard", PoolsideDashboard);
}
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "poolside-dashboard")) {
  window.customCards.push({ type: "poolside-dashboard", name: "Poolside Dashboard", description: "Daily Poolside controls with advanced live telemetry gauges." });
}
