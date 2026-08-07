/** Daily-use Poolside dashboard with a separate live diagnostics view. */
class PoolsideDashboard extends HTMLElement {
  setConfig(config) {
    if (!config || typeof config.mode_entity !== "string") {
      throw new Error("poolside-dashboard requires mode_entity");
    }
    this.config = config;
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `
      <style>
        :host { display:block; }
        ha-card { padding:18px; }
        h2, h3 { margin:0; }
        h2 { font-size:1.2rem; }
        h3 { font-size:1rem; }
        ha-icon { color:var(--state-icon-color); }
        .header { display:flex; align-items:center; gap:10px; }
        .subtitle, .hint { margin:5px 0 0; color:var(--secondary-text-color); font-size:.86rem; }
        .mode-rail { display:flex; gap:4px; margin:18px 0; padding:4px; background:var(--secondary-background-color); border-radius:26px; }
        button { font:inherit; cursor:pointer; }
        .mode { flex:1; border:0; border-radius:22px; padding:10px 12px; color:var(--primary-text-color); background:transparent; }
        .mode.active { color:var(--text-primary-color); background:var(--primary-color); font-weight:600; }
        .overview { display:grid; grid-template-columns:repeat(auto-fit,minmax(135px,1fr)); gap:9px; }
        .stat { min-height:74px; padding:12px; border:1px solid var(--divider-color); border-radius:12px; background:var(--card-background-color); }
        .stat-label { display:flex; gap:6px; align-items:center; color:var(--secondary-text-color); font-size:.76rem; }
        .stat-value { display:block; margin-top:8px; font-size:1.12rem; font-weight:600; }
        .section { border-top:1px solid var(--divider-color); margin-top:18px; padding-top:15px; }
        .section-head { display:flex; align-items:center; justify-content:space-between; margin-bottom:10px; }
        .essentials { display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); gap:12px; }
        .panel { border:1px solid var(--divider-color); border-radius:12px; padding:12px; }
        .panel-title { display:flex; align-items:center; gap:8px; font-weight:600; margin-bottom:7px; }
        .panel .row + .row { border-top:1px solid var(--divider-color); }
        .row { display:flex; align-items:center; justify-content:space-between; gap:10px; min-height:45px; }
        .label { display:flex; min-width:0; align-items:center; gap:8px; }
        .label span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .actions { display:flex; align-items:center; justify-content:flex-end; gap:8px; min-width:0; }
        .toggle { flex:0 0 auto; min-width:52px; padding:6px 10px; border:1px solid var(--divider-color); border-radius:18px; background:var(--card-background-color); color:var(--primary-text-color); }
        .toggle.active { color:var(--text-primary-color); border-color:var(--primary-color); background:var(--primary-color); }
        .slider { width:104px; accent-color:var(--primary-color); }
        .value { min-width:44px; color:var(--secondary-text-color); font-size:.82rem; text-align:right; }
        .color { width:30px; height:28px; padding:0; border:1px solid var(--divider-color); border-radius:7px; background:transparent; }
        .effect { max-width:105px; border:1px solid var(--divider-color); border-radius:7px; padding:4px; color:var(--primary-text-color); background:var(--card-background-color); }
        .features { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:8px; }
        .feature { border:1px solid var(--divider-color); border-radius:10px; padding:8px 10px; }
        .empty { padding:18px; text-align:center; color:var(--secondary-text-color); border:1px dashed var(--divider-color); border-radius:12px; }
        details { border-top:1px solid var(--divider-color); margin-top:18px; padding-top:14px; }
        summary { cursor:pointer; font-weight:600; }
        .gauge-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(145px,1fr)); gap:12px; margin-top:14px; }
        .gauge { padding:10px; border:1px solid var(--divider-color); border-radius:12px; text-align:center; }
        .gauge svg { width:112px; height:112px; transform:rotate(-90deg); }
        .gauge .track { fill:none; stroke:var(--divider-color); stroke-width:11; }
        .gauge .progress { fill:none; stroke:var(--primary-color); stroke-width:11; stroke-linecap:round; }
        .gauge-value { margin-top:-72px; min-height:63px; display:flex; flex-direction:column; align-items:center; justify-content:center; }
        .gauge-value strong { font-size:1.1rem; }
        .gauge-value small, .gauge-label { color:var(--secondary-text-color); font-size:.74rem; }
        .diagnostics { margin-top:14px; }
        .diagnostic-row { display:flex; justify-content:space-between; gap:12px; padding:8px 0; border-top:1px solid var(--divider-color); font-size:.88rem; }
        .diagnostic-row span:last-child { color:var(--secondary-text-color); text-align:right; }
        @media (max-width:560px) { ha-card { padding:14px; } .overview { grid-template-columns:repeat(2,1fr); } .actions { gap:5px; } .slider { width:80px; } .effect { display:none; } }
      </style>
      <ha-card>
        <div class="header"><ha-icon icon="mdi:pool"></ha-icon><h2></h2></div>
        <p class="subtitle">Safe controls follow the confirmed Poolside cloud state.</p>
        <div class="mode-rail"></div>
        <div class="overview"></div>
        <section class="daily section"><div class="section-head"><h3>Daily controls</h3></div><div class="daily-content"></div></section>
        <details class="more"><summary>More controls</summary><div class="more-content"></div></details>
        <details class="advanced"><summary>Advanced monitoring</summary><p class="hint">Live read-only controller telemetry. Physical equipment and valves are never controlled here.</p><div class="gauge-grid"></div><div class="diagnostics"></div></details>
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

    const discovered = this._discoverEntities();
    const configured = (key, fallback, allowed) => {
      const ids = Array.isArray(this.config[key]) ? this.config[key].filter((id) => this._hass.states[id] && allowed(id)) : [];
      return ids.length ? ids : fallback;
    };
    const safeControl = (id) => ["switch", "light", "number"].includes(id.split(".")[0]);
    const diagnostics = configured("shared_entities", discovered.telemetry, (id) => ["sensor", "binary_sensor"].includes(id.split(".")[0]));
    const pool = configured("pool_entities", discovered.pool, safeControl);
    const spa = configured("spa_entities", discovered.spa, safeControl);
    const allControls = [...new Set([...pool, ...spa])];
    const selected = String(mode.state || "Off").toLowerCase();
    const activeControls = selected === "pool" ? pool : selected === "spa" ? spa : [];
    this._renderModes(mode, modeEntity);
    this._renderOverview(mode, activeControls, allControls, diagnostics);
    this._renderDaily(mode, activeControls);
    this._renderMore(activeControls);
    this._renderAdvanced(diagnostics);
  }

  _renderUnavailable() {
    this.shadowRoot.querySelector(".mode-rail").innerHTML = "";
    this.shadowRoot.querySelector(".overview").innerHTML = '<div class="empty">Poolside is reconnecting. The active-body selector is unavailable.</div>';
    this.shadowRoot.querySelector(".daily-content").innerHTML = "";
    this.shadowRoot.querySelector(".more-content").innerHTML = "";
  }

  _renderModes(mode, modeEntity) {
    const rail = this.shadowRoot.querySelector(".mode-rail");
    rail.innerHTML = "";
    (Array.isArray(mode.attributes.options) ? mode.attributes.options : ["Off"]).forEach((option) => {
      const button = document.createElement("button");
      button.className = `mode ${option === mode.state ? "active" : ""}`;
      button.textContent = option;
      button.addEventListener("click", () => this._select(option, mode.state, modeEntity));
      rail.appendChild(button);
    });
  }

  _renderOverview(mode, activeControls, allControls, telemetry) {
    const findTelemetry = (patterns, fallback = "—") => {
      const candidates = telemetry.map((id) => this._hass.states[id]).filter((item) => item && !this._unavailable(item));
      const state = patterns.map((pattern) => candidates.find((item) => pattern.test(this._identity(item)))).find(Boolean);
      return state ? this._stateValue(state) : fallback;
    };
    const findControl = (pattern) => allControls.map((id) => this._hass.states[id]).find((item) => item && pattern.test(this._identity(item)));
    const heater = findControl(/heater/);
    const circulation = findControl(/filter|pump|circulation/);
    const lights = allControls.filter((id) => id.startsWith("light.")).map((id) => this._hass.states[id]).filter(Boolean);
    const features = allControls.map((id) => this._hass.states[id]).filter((item) => item && /(bubbler|blower|cleaner|spill|jets)/.test(this._identity(item)));
    const stats = [
      ["mdi:pool", "Mode", mode.state],
      ["mdi:thermometer-water", "Water", findTelemetry([/water.*thermistor/, /water.*temp/, /temperature/])],
      ["mdi:fan", "Circulation", circulation ? this._status(circulation) : findTelemetry([/primary.*pump.*rpm/, /pump.*rpm/, /flow/])],
      ["mdi:fire", "Heating", heater ? this._status(heater) : "—"],
      ["mdi:lightbulb-group", "Lights", `${lights.filter((item) => item.state === "on").length}/${lights.length}`],
      ["mdi:water", "Features", `${features.filter((item) => item.state === "on").length}/${features.length}`],
    ];
    this.shadowRoot.querySelector(".overview").innerHTML = stats.map(([icon, label, value]) => `<div class="stat"><span class="stat-label"><ha-icon icon="${icon}"></ha-icon>${this._escape(label)}</span><span class="stat-value">${this._escape(value)}</span></div>`).join("");
  }

  _renderDaily(mode, controls) {
    const target = this.shadowRoot.querySelector(".daily-content");
    if (String(mode.state).toLowerCase() === "off") {
      target.innerHTML = '<div class="empty"><strong>Select Pool or Spa to control that body.</strong><br><span class="hint">This keeps connected water paths exclusive and lets Poolside coordinate valves safely.</span></div>';
      return;
    }
    const groups = this._groups(controls);
    const panels = [
      ["mdi:fire", "Heating", groups.heating],
      ["mdi:fan", "Circulation", groups.circulation],
      ["mdi:lightbulb-group", "Lighting", groups.lights],
    ].filter(([, , ids]) => ids.length);
    const essentials = panels.map(([icon, title, ids]) => `<div class="panel"><div class="panel-title"><ha-icon icon="${icon}"></ha-icon>${title}</div>${ids.map((id) => this._control(id)).join("")}</div>`).join("");
    const featureRows = groups.features.map((id) => `<div class="feature">${this._control(id)}</div>`).join("");
    target.innerHTML = `<p class="hint">${this._escape(`Controlling ${mode.state}. Changes are confirmed by Poolside before the display updates.`)}</p><div class="essentials">${essentials || '<div class="empty">No daily controls were discovered for this body.</div>'}</div>${featureRows ? `<section class="section"><div class="section-head"><h3>Water features</h3></div><div class="features">${featureRows}</div></section>` : ""}`;
    this._wireControls(target);
  }

  _renderMore(controls) {
    const target = this.shadowRoot.querySelector(".more-content");
    const remaining = this._groups(controls).other;
    target.innerHTML = remaining.length ? remaining.map((id) => this._control(id)).join("") : '<p class="hint">No additional safe controls are available for the selected body.</p>';
    this._wireControls(target);
  }

  _renderAdvanced(telemetry) {
    const states = telemetry.map((id) => this._hass.states[id]).filter((state) => state && this._isUsefulTelemetry(state));
    const gaugeStates = states.filter((state) => this._isGaugeTelemetry(state)).sort((left, right) => this._gaugePriority(left) - this._gaugePriority(right)).slice(0, 6);
    this.shadowRoot.querySelector(".gauge-grid").innerHTML = gaugeStates.length ? gaugeStates.map((state) => this._gauge(state)).join("") : '<div class="empty">No live pressure, RPM, flow, or temperature telemetry is currently available.</div>';
    this.shadowRoot.querySelector(".diagnostics").innerHTML = states.length ? states.map((state) => `<div class="diagnostic-row"><span>${this._escape(state.attributes.friendly_name || "Telemetry")}</span><span>${this._escape(this._stateValue(state))}</span></div>`).join("") : '<p class="hint">No controller telemetry has been reported.</p>';
  }

  _gauge(state) {
    const identity = this._identity(state);
    const value = Number(state.state);
    const [min, max] = state.attributes.min !== undefined && state.attributes.max !== undefined ? [Number(state.attributes.min), Number(state.attributes.max)] : identity.includes("pressure") ? [0, 50] : identity.includes("speedpercent") ? [0, 100] : identity.includes("rpm") ? [0, 3450] : identity.includes("flow") ? [0, 150] : [32, 150];
    const percent = Number.isFinite(value) ? Math.max(0, Math.min(100, ((value - min) / Math.max(1, max - min)) * 100)) : 0;
    const circumference = 282.7;
    const offset = circumference * (1 - percent / 100);
    const label = this._telemetryLabel(state);
    const unit = this._unitFor(state);
    return `<div class="gauge"><svg viewBox="0 0 112 112" aria-label="${this._escape(label)}"><circle class="track" cx="56" cy="56" r="45"></circle><circle class="progress" cx="56" cy="56" r="45" stroke-dasharray="${circumference}" stroke-dashoffset="${offset}"></circle></svg><div class="gauge-value"><strong>${Number.isFinite(value) ? this._escape(value) : "—"}</strong><small>${this._escape(unit)}</small></div><div class="gauge-label">${this._escape(label)}</div></div>`;
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
      return `<div class="row"><div class="label"><ha-icon icon="${icon}"></ha-icon><span>${name}</span></div><div class="actions"><input class="slider number" type="range" min="${min}" max="${max}" step="${state.attributes.step || 1}" value="${Number.isFinite(value) ? value : min}" data-entity="${entityId}" ${disabled}><span class="value">${Number.isFinite(value) ? this._escape(`${value} ${state.attributes.unit_of_measurement || ""}`) : "—"}</span></div></div>`;
    }
    const active = state.state === "on";
    const attrs = state.attributes;
    const isLight = domain === "light";
    const rgb = Array.isArray(attrs.rgb_color) ? attrs.rgb_color : [0, 153, 204];
    const color = `#${rgb.map((channel) => Math.max(0, Math.min(255, Number(channel) || 0)).toString(16).padStart(2, "0")).join("")}`;
    const brightness = isLight ? `<input class="slider light-brightness" type="range" min="0" max="255" step="1" value="${Number(attrs.brightness) || 0}" data-entity="${entityId}" aria-label="${name} brightness" ${disabled}>` : "";
    const colorInput = isLight ? `<input class="color light-color" type="color" value="${color}" data-entity="${entityId}" aria-label="${name} color" ${disabled}>` : "";
    return `<div class="row"><div class="label"><ha-icon icon="${icon}"></ha-icon><span>${name}</span></div><div class="actions">${brightness}${colorInput}<button class="toggle ${active ? "active" : ""}" data-entity="${entityId}" ${disabled}>${unavailable ? "—" : active ? "On" : "Off"}</button></div></div>`;
  }

  _wireControls(scope) {
    scope.querySelectorAll(".toggle").forEach((button) => button.addEventListener("click", () => this._hass.callService(button.dataset.entity.startsWith("light.") ? "light" : "switch", "toggle", { entity_id: button.dataset.entity })));
    scope.querySelectorAll(".number").forEach((input) => input.addEventListener("change", () => this._hass.callService("number", "set_value", { entity_id: input.dataset.entity, value: Number(input.value) })));
    scope.querySelectorAll(".light-brightness").forEach((input) => input.addEventListener("change", () => this._hass.callService("light", "turn_on", { entity_id: input.dataset.entity, brightness: Number(input.value) })));
    scope.querySelectorAll(".light-color").forEach((input) => input.addEventListener("change", () => {
      const raw = input.value.slice(1);
      this._hass.callService("light", "turn_on", { entity_id: input.dataset.entity, rgb_color: [0, 2, 4].map((offset) => parseInt(raw.slice(offset, offset + 2), 16)) });
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

  _discoverEntities() {
    const result = { pool: [], spa: [], telemetry: [] };
    Object.entries(this._hass.states).forEach(([id, state]) => {
      const name = String(state.attributes.friendly_name || "").toLowerCase();
      const identity = `${name} ${id.toLowerCase()}`;
      const domain = id.split(".")[0];
      const poolside = id.includes("poolside") || /^(pool|spa)\b/.test(name);
      if (!poolside) return;
      if (["switch", "light", "number"].includes(domain)) {
        if (identity.includes("pool")) result.pool.push(id);
        else if (identity.includes("spa")) result.spa.push(id);
      }
      if (["sensor", "binary_sensor"].includes(domain) && /(rpm|speed|flow|pressure|temperature|firmware|version|fault|online)/.test(identity)) result.telemetry.push(id);
    });
    return result;
  }

  async _select(option, current, entityId) {
    if (option === current) return;
    if (current && current.toLowerCase() !== "off" && option.toLowerCase() !== "off" && !window.confirm(`Switch from ${current} to ${option}? Poolside will adjust shared valves safely.`)) return;
    await this._hass.callService("select", "select_option", { entity_id: entityId, option });
  }

  _resolveModeEntity() {
    if (this._hass.states[this.config.mode_entity]) return this.config.mode_entity;
    return Object.keys(this._hass.states).find((id) => id.startsWith("select.") && id.includes("active_body"));
  }

  _identity(state) { return `${state?.attributes?.friendly_name || ""} ${state?.entity_id || ""}`.toLowerCase(); }
  _unavailable(state) { return !state || ["unavailable", "unknown"].includes(state.state); }
  _status(state) { return this._unavailable(state) ? "Unavailable" : state.state === "on" ? "On" : state.state === "off" ? "Off" : this._stateValue(state); }
  _stateValue(state) { return `${state.state} ${this._unitFor(state)}`.trim(); }
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
      .replace(/([a-z])([A-Z])/g, "$1 $2");
  }
  _isUsefulTelemetry(state) {
    const identity = this._identity(state);
    return /(pressurepsi|winterized|pump.*(rpm|speedpercent|temperature)|thermistor.*temperature|flow|fault|online)/.test(identity);
  }
  _isGaugeTelemetry(state) {
    const identity = this._identity(state);
    return !/winterized|fault|online/.test(identity) && /(pressurepsi|pump.*(rpm|speedpercent|temperature)|thermistor.*temperature|flow)/.test(identity);
  }
  _gaugePriority(state) {
    const identity = this._identity(state);
    if (/pressurepsi/.test(identity)) return 1;
    if (/water.*thermistor/.test(identity)) return 2;
    if (/primary.*pump.*rpm/.test(identity)) return 3;
    if (/feature.*pump.*rpm/.test(identity)) return 4;
    if (/thermistor/.test(identity)) return 5;
    return 6;
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
  _escape(value) { return String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]); }
}

customElements.define("poolside-dashboard", PoolsideDashboard);
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "poolside-dashboard")) {
  window.customCards.push({ type: "poolside-dashboard", name: "Poolside Dashboard", description: "Daily Poolside controls with advanced live telemetry gauges." });
}
