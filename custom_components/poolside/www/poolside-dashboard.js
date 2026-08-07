/** Local Poolside dashboard with active-body visibility. */
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
        ha-card { padding:16px; }
        h2 { margin:0 0 4px; font-size:1.1rem; }
        .muted { opacity:.7; font-size:.8rem; }
        .summary-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:8px; margin:14px 0; }
        .metric { padding:10px; border:1px solid var(--divider-color); border-radius:10px; }
        .metric-label { display:block; opacity:.7; font-size:.72rem; }
        .metric-value { display:block; margin-top:3px; font-size:1rem; font-weight:600; }
        .rail { display:flex; gap:4px; margin:16px 0; padding:3px; background:#e1e5e9; border-radius:24px; }
        button { border:0; border-radius:20px; background:transparent; padding:9px 12px; flex:1; cursor:pointer; }
        button.active { background:var(--primary-color); color:var(--text-primary-color); font-weight:600; }
        .section { border-top:1px solid var(--divider-color); padding-top:12px; margin-top:12px; }
        .section[hidden] { display:none; }
        .section h3 { margin:0 0 4px; font-size:.95rem; }
        .row { display:flex; justify-content:space-between; align-items:center; min-height:38px; }
        .control-label { display:flex; align-items:center; gap:10px; min-width:0; }
        .control-label span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        ha-icon { color:var(--state-icon-color); }
        .control-actions { display:flex; align-items:center; gap:12px; margin-left:12px; }
        .toggle { flex:0 0 auto; min-width:58px; padding:6px 10px; border:1px solid var(--divider-color); background:var(--card-background-color); color:var(--primary-text-color); }
        .toggle.active { background:var(--primary-color); color:var(--text-primary-color); border-color:var(--primary-color); }
        .number { width:42%; accent-color:var(--primary-color); }
        .color { width:34px; height:28px; padding:0; border:1px solid var(--divider-color); border-radius:6px; background:transparent; }
        .effect { max-width:140px; padding:5px; border:1px solid var(--divider-color); border-radius:6px; background:var(--card-background-color); color:var(--primary-text-color); }
        summary { cursor:pointer; font-weight:600; }
        .notice { color:var(--warning-color); font-size:.78rem; margin-top:12px; }
      </style>
      <ha-card><h2></h2><div class="muted">Shared valves and equipment follow the cloud mode procedure.</div>
      <div class="rail"></div><div class="summary-grid"></div>
      <details class="controls section" open><summary>Controls</summary><div class="pool section"><h3>Pool</h3><div class="entity-rows"></div></div><div class="spa section"><h3>Spa</h3><div class="entity-rows"></div></div></details>
      <details class="diagnostics section"><summary>Diagnostics</summary><div class="diagnostic-rows"></div></details></ha-card>`;
    this._render();
  }

  set hass(hass) { this._hass = hass; this._render(); }

  _render() {
    if (!this._hass || !this.config) return;
    const modeEntity = this._resolveModeEntity();
    const mode = modeEntity ? this._hass.states[modeEntity] : undefined;
    this.shadowRoot.querySelector("h2").textContent = this.config.name || "Poolside";
    const rail = this.shadowRoot.querySelector(".rail");
    if (!mode) {
      rail.innerHTML = "";
      this.shadowRoot.querySelector(".summary-grid").innerHTML = '<div class="notice">Poolside status is unavailable.</div>';
      this.shadowRoot.querySelector(".diagnostic-rows").innerHTML =
        '<div class="notice">No active-body selector was found. Reload the Poolside integration.</div>';
      this.shadowRoot.querySelector(".diagnostics").hidden = false;
      this.shadowRoot.querySelector(".pool").hidden = true;
      this.shadowRoot.querySelector(".spa").hidden = true;
      return;
    }
    const options = Array.isArray(mode.attributes.options) ? mode.attributes.options : ["Off"];
    rail.innerHTML = "";
    options.forEach((option) => {
      const button = document.createElement("button");
      button.textContent = option;
      button.classList.toggle("active", option === mode.state);
      button.addEventListener("click", () => this._select(option, mode.state));
      rail.appendChild(button);
    });
    const selected = (mode.state || "Off").toLowerCase();
    const discovered = this._discoverEntities();
    const configured = (key, fallback, predicate = () => true) => {
      const ids = Array.isArray(this.config[key])
        ? this.config[key].filter((entityId) => this._hass.states[entityId] && predicate(entityId))
        : [];
      return ids.length ? ids : fallback;
    };
    const isControl = (entityId) => ["switch", "light", "number"].includes(entityId.split(".")[0]);
    const diagnostics = configured("shared_entities", discovered.shared, (id) => ["sensor", "binary_sensor"].includes(id.split(".")[0]));
    let pool = configured("pool_entities", discovered.pool, isControl);
    let spa = configured("spa_entities", discovered.spa, isControl);
    // Older entity naming may omit the body name. Keep the active-body view
    // useful by showing discovered safe controls in the selected section.
    if (!pool.length && !spa.length && selected !== "off") {
      if (selected === "pool") pool = discovered.controls;
      if (selected === "spa") spa = discovered.controls;
    }
    const activeControls = selected === "pool" ? pool : selected === "spa" ? spa : [];
    this._renderSummary(mode, activeControls, diagnostics);
    this._renderEntities("pool", selected === "pool" ? pool : []);
    this._renderEntities("spa", selected === "spa" ? spa : []);
    this._renderDiagnostics(diagnostics);
  }

  _renderSummary(mode, controls, diagnostics) {
    const states = [...diagnostics, ...controls].map((id) => this._hass.states[id]).filter(Boolean);
    const findValue = (pattern) => {
      const match = diagnostics.map((id) => this._hass.states[id]).find((state) => state && pattern.test(`${state.attributes.friendly_name || ""} ${state.entity_id || ""}`.toLowerCase()) && !["unavailable", "unknown"].includes(state.state));
      return match ? `${match.state} ${match.attributes.unit_of_measurement || ""}`.trim() : "—";
    };
    const active = states.filter((state) => state.state === "on").length;
    const unavailable = states.filter((state) => ["unavailable", "unknown"].includes(state.state)).length;
    const findControl = (pattern) => controls.map((id) => this._hass.states[id]).find((state) => state && pattern.test(state.attributes.friendly_name || ""));
    const heater = findControl(/heater/i);
    const filter = findControl(/filter|pump|circulation/i);
    const lights = controls.filter((id) => id.startsWith("light.")).map((id) => this._hass.states[id]).filter(Boolean);
    const features = controls.map((id) => this._hass.states[id]).filter((state) => state && /(bubbler|blower|cleaner|spill|jets)/i.test(state.attributes.friendly_name || ""));
    const heaterSetpoint = controls.filter((id) => id.startsWith("number.")).map((id) => this._hass.states[id]).find((state) => state && /heater|temperature|setpoint/i.test(state.attributes.friendly_name || ""));
    const heaterState = heater ? (heater.state === "on" ? "On" : heater.state) : "—";
    const heatValue = heaterSetpoint && !["unavailable", "unknown"].includes(heaterSetpoint.state) ? ` · ${heaterSetpoint.state} ${heaterSetpoint.attributes.unit_of_measurement || ""}` : "";
    const metrics = [
      ["Mode", mode.state || "—"],
      ["Water temperature", findValue(/water.*temp|temp.*water|temperature/)],
      ["Circulation", filter ? (filter.state === "on" ? "On" : filter.state) : findValue(/rpm|speed|flow/)],
      ["Heating", `${heaterState}${heatValue}`],
      ["Lighting", `${lights.filter((state) => state.state === "on").length}/${lights.length}`],
      ["Features", `${features.filter((state) => state.state === "on").length}/${features.length}`],
    ];
    this.shadowRoot.querySelector(".summary-grid").innerHTML = metrics.map(([label, value]) => `<div class="metric"><span class="metric-label">${this._escape(label)}</span><span class="metric-value">${this._escape(value)}</span></div>`).join("");
  }

  _renderEntities(sectionName, entityIds) {
    const section = this.shadowRoot.querySelector(`.${sectionName}`);
    section.hidden = entityIds.length === 0;
    section.querySelector(".entity-rows").innerHTML = entityIds.map((entityId) => {
      const state = this._hass.states[entityId];
      if (!state) return "";
      const domain = entityId.split(".")[0];
      const label = this._escape(state.attributes.friendly_name || entityId);
      const icon = this._iconFor(state, entityId);
      const unavailable = ["unavailable", "unknown"].includes(state.state);
      if (["switch", "light"].includes(domain)) {
        const active = state.state === "on";
        const attrs = state.attributes;
        // PoolsideLight always implements dimming and RGB writes. Some HA state
        // serializers omit empty capability attributes, so do not hide the
        // controls merely because the current state is off or unavailable.
        const isPoolsideLight = domain === "light" && (entityId.includes("poolside") || /^(pool|spa)\b/i.test(attrs.friendly_name || ""));
        const hasBrightness = isPoolsideLight || (domain === "light" && (attrs.brightness !== undefined || Array.isArray(attrs.supported_color_modes)));
        const rgb = Array.isArray(attrs.rgb_color) ? attrs.rgb_color : [0, 153, 204];
        const hex = `#${rgb.map((value) => Math.max(0, Math.min(255, Number(value) || 0)).toString(16).padStart(2, "0")).join("")}`;
        const supportsColor = isPoolsideLight || (domain === "light" && (Array.isArray(attrs.rgb_color) || Array.isArray(attrs.hs_color) || (Array.isArray(attrs.supported_color_modes) && attrs.supported_color_modes.some((mode) => ["rgb", "hs", "xy"].includes(mode)))));
        const effects = domain === "light" && Array.isArray(attrs.effect_list) ? attrs.effect_list : [];
        const brightness = hasBrightness
          ? `<input class="number light-brightness" type="range" min="0" max="255" step="1" value="${Number(attrs.brightness) || 0}" data-entity="${entityId}" aria-label="${label} brightness" ${unavailable ? "disabled" : ""}>`
          : "";
        const color = supportsColor
          ? `<input class="color light-color" type="color" value="${hex}" data-entity="${entityId}" aria-label="${label} color" ${unavailable ? "disabled" : ""}>`
          : "";
        const effect = effects.length ? `<select class="effect light-effect" data-entity="${entityId}" aria-label="${label} effect" ${unavailable ? "disabled" : ""}><option value="">Effect</option>${effects.map((item) => `<option value="${this._escape(item)}" ${item === attrs.effect ? "selected" : ""}>${this._escape(item)}</option>`).join("")}</select>` : "";
        return `<div class="row"><div class="control-label"><ha-icon icon="${icon}"></ha-icon><span>${label}</span></div><div class="control-actions">${brightness}${color}${effect}<button class="toggle ${active ? "active" : ""}" data-entity="${entityId}" ${unavailable ? "disabled" : ""}>${active ? "On" : "Off"}</button></div></div>`;
      }
      if (entityId.startsWith("number.") && state.attributes.min !== undefined) {
        const value = Number(state.state);
        return `<div class="row"><div class="control-label"><ha-icon icon="${icon}"></ha-icon><span>${label}</span></div><div class="control-actions"><input class="number" type="range" min="${state.attributes.min}" max="${state.attributes.max}" step="${state.attributes.step || 1}" value="${Number.isFinite(value) ? value : state.attributes.min}" data-entity="${entityId}" aria-label="${label}" ${unavailable ? "disabled" : ""}><span>${Number.isFinite(value) ? this._escape(`${value} ${state.attributes.unit_of_measurement || ""}`) : "—"}</span></div></div>`;
      }
      return `<div class="row"><span>${label}</span><span>${this._escape(`${state.state} ${state.attributes.unit_of_measurement || ""}`)}</span></div>`;
    }).join("");
    section.querySelectorAll(".toggle").forEach((button) => button.addEventListener("click", () => this._hass.callService(button.dataset.entity.startsWith("light.") ? "light" : "switch", "toggle", { entity_id: button.dataset.entity })));
    section.querySelectorAll(".number:not(.light-brightness)").forEach((input) => input.addEventListener("change", () => this._hass.callService("number", "set_value", { entity_id: input.dataset.entity, value: Number(input.value) })));
    section.querySelectorAll(".light-brightness").forEach((input) => input.addEventListener("change", () => this._hass.callService("light", "turn_on", { entity_id: input.dataset.entity, brightness: Number(input.value) })));
    section.querySelectorAll(".light-color").forEach((input) => input.addEventListener("change", () => {
      const value = input.value.replace("#", "");
      const rgb = [0, 2, 4].map((offset) => parseInt(value.slice(offset, offset + 2), 16));
      this._hass.callService("light", "turn_on", { entity_id: input.dataset.entity, rgb_color: rgb });
    }));
    section.querySelectorAll(".light-effect").forEach((input) => input.addEventListener("change", () => {
      if (input.value) this._hass.callService("light", "turn_on", { entity_id: input.dataset.entity, effect: input.value });
    }));
  }

  _iconFor(state, entityId) {
    const identity = `${state.attributes.friendly_name || ""} ${entityId}`.toLowerCase();
    if (identity.includes("heater")) return "mdi:thermometer-water";
    if (identity.includes("filter")) return "mdi:air-filter";
    if (identity.includes("cleaner")) return "mdi:robot-vacuum";
    if (identity.includes("blower") || identity.includes("pump")) return "mdi:fan";
    if (identity.includes("bubbler") || identity.includes("spill") || identity.includes("jets")) return "mdi:water";
    if (identity.includes("strip") || entityId.startsWith("light.")) return "mdi:lightbulb";
    if (entityId.startsWith("number.")) return "mdi:tune-vertical";
    return "mdi:toggle-switch-outline";
  }

  _renderDiagnostics(entityIds) {
    const rows = this.shadowRoot.querySelector(".diagnostic-rows");
    rows.innerHTML = entityIds.map((entityId) => {
      const state = this._hass.states[entityId];
      if (!state) return "";
      return `<div class="row"><span>${this._escape(state.attributes.friendly_name || entityId)}</span><span>${this._escape(`${state.state} ${state.attributes.unit_of_measurement || ""}`)}</span></div>`;
    }).join("");
    this.shadowRoot.querySelector(".diagnostics").hidden = entityIds.length === 0;
  }

  _discoverEntities() {
    const result = { controls: [], shared: [], pool: [], spa: [] };
    Object.entries(this._hass.states).forEach(([entityId, state]) => {
      const name = String(state.attributes.friendly_name || "").toLowerCase();
      const identity = `${name} ${entityId.toLowerCase()}`;
      const domain = entityId.split(".")[0];
      const isPoolside = entityId.includes("poolside") || /^(pool|spa|poolside)\b/.test(name);
      if (["switch", "light", "number"].includes(domain)) {
        if (isPoolside) {
          result.controls.push(entityId);
          if (identity.includes("pool")) result.pool.push(entityId);
          else if (identity.includes("spa")) result.spa.push(entityId);
        }
      }
      if (["sensor", "binary_sensor"].includes(domain) && isPoolside && /(rpm|speed|flow|pressure|temperature|firmware|version|fault|online)/.test(identity)) {
        result.shared.push(entityId);
      }
    });
    return result;
  }

  async _select(option, current) {
    if (option === current) return;
    if (current && current.toLowerCase() !== "off" && option.toLowerCase() !== "off" && !window.confirm(`Switch from ${current} to ${option}? Shared valves will be adjusted by Poolside.`)) return;
    await this._hass.callService("select", "select_option", { entity_id: this._resolveModeEntity(), option });
  }

  _resolveModeEntity() {
    if (this._hass.states[this.config.mode_entity]) return this.config.mode_entity;
    return Object.keys(this._hass.states).find((entityId) =>
      entityId.startsWith("select.") && entityId.includes("active_body"));
  }

  _escape(value) { return String(value).replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"})[c]); }
}

customElements.define("poolside-dashboard", PoolsideDashboard);
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "poolside-dashboard")) {
  window.customCards.push({ type: "poolside-dashboard", name: "Poolside Dashboard", description: "Active-body controls and read-only telemetry." });
}
