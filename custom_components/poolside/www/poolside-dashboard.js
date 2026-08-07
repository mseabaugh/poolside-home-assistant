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
        .rail { display:flex; gap:4px; margin:16px 0; padding:3px; background:#e1e5e9; border-radius:24px; }
        button { border:0; border-radius:20px; background:transparent; padding:9px 12px; flex:1; cursor:pointer; }
        button.active { background:var(--primary-color); color:var(--text-primary-color); font-weight:600; }
        .section { border-top:1px solid var(--divider-color); padding-top:12px; margin-top:12px; }
        .section[hidden] { display:none; }
        .section h3 { margin:0 0 4px; font-size:.95rem; }
        .row { display:flex; justify-content:space-between; align-items:center; min-height:38px; }
        .toggle { flex:0 0 auto; min-width:58px; padding:6px 10px; border:1px solid var(--divider-color); background:var(--card-background-color); color:var(--primary-text-color); }
        .toggle.active { background:var(--primary-color); color:var(--text-primary-color); border-color:var(--primary-color); }
        .number { width:42%; accent-color:var(--primary-color); }
        summary { cursor:pointer; font-weight:600; }
        .notice { color:var(--warning-color); font-size:.78rem; margin-top:12px; }
      </style>
      <ha-card><h2></h2><div class="muted">Shared valves and equipment follow the cloud mode procedure.</div>
      <div class="rail"></div><div class="pool section"><h3>Pool</h3><div class="entity-rows"></div></div><div class="spa section"><h3>Spa</h3><div class="entity-rows"></div></div>
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
    this._renderEntities("pool", selected === "pool" ? pool : []);
    this._renderEntities("spa", selected === "spa" ? spa : []);
    this._renderDiagnostics(diagnostics);
  }

  _renderEntities(sectionName, entityIds) {
    const section = this.shadowRoot.querySelector(`.${sectionName}`);
    section.hidden = entityIds.length === 0;
    section.querySelector(".entity-rows").innerHTML = entityIds.map((entityId) => {
      const state = this._hass.states[entityId];
      if (!state) return "";
      const label = this._escape(state.attributes.friendly_name || entityId);
      if (["switch", "light"].includes(entityId.split(".")[0])) {
        const active = state.state === "on";
        return `<div class="row"><span>${label}</span><button class="toggle ${active ? "active" : ""}" data-entity="${entityId}">${active ? "On" : "Off"}</button></div>`;
      }
      if (entityId.startsWith("number.") && state.attributes.min !== undefined) {
        return `<div class="row"><span>${label}</span><input class="number" type="range" min="${state.attributes.min}" max="${state.attributes.max}" step="${state.attributes.step || 1}" value="${state.state}" data-entity="${entityId}"></div>`;
      }
      return `<div class="row"><span>${label}</span><span>${this._escape(`${state.state} ${state.attributes.unit_of_measurement || ""}`)}</span></div>`;
    }).join("");
    section.querySelectorAll(".toggle").forEach((button) => button.addEventListener("click", () => this._hass.callService(button.dataset.entity.startsWith("light.") ? "light" : "switch", "toggle", { entity_id: button.dataset.entity })));
    section.querySelectorAll(".number").forEach((input) => input.addEventListener("change", () => this._hass.callService("number", "set_value", { entity_id: input.dataset.entity, value: Number(input.value) })));
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
