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
        .row { display:flex; justify-content:space-between; align-items:center; min-height:38px; }
        .notice { color:var(--warning-color); font-size:.78rem; margin-top:12px; }
      </style>
      <ha-card><h2></h2><div class="muted">Shared valves and equipment follow the cloud mode procedure.</div>
      <div class="rail"></div><div class="shared section"></div><div class="pool section"></div><div class="spa section"></div></ha-card>`;
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
      this.shadowRoot.querySelector(".shared").innerHTML =
        '<div class="notice">No active-body selector was found. Reload the Poolside integration.</div>';
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
    const shared = this.config.shared_entities?.length ? this.config.shared_entities : discovered.shared;
    const pool = this.config.pool_entities?.length ? this.config.pool_entities : discovered.pool;
    const spa = this.config.spa_entities?.length ? this.config.spa_entities : discovered.spa;
    this._renderEntities("shared", shared);
    this._renderEntities("pool", selected === "pool" ? pool : []);
    this._renderEntities("spa", selected === "spa" ? spa : []);
  }

  _renderEntities(sectionName, entityIds) {
    const section = this.shadowRoot.querySelector(`.${sectionName}`);
    section.hidden = entityIds.length === 0;
    section.innerHTML = entityIds.map((entityId) => {
      const state = this._hass.states[entityId];
      if (!state) return "";
      const value = state.state === "on" || state.state === "off" ? state.state : `${state.state} ${state.attributes.unit_of_measurement || ""}`;
      return `<div class="row"><span>${this._escape(state.attributes.friendly_name || entityId)}</span><span>${this._escape(value)}</span></div>`;
    }).join("");
  }

  _discoverEntities() {
    const result = { shared: [], pool: [], spa: [] };
    Object.entries(this._hass.states).forEach(([entityId, state]) => {
      const name = String(state.attributes.friendly_name || "").toLowerCase();
      const identity = `${name} ${entityId.toLowerCase()}`;
      const domain = entityId.split(".")[0];
      if (["switch", "light", "number"].includes(domain)) {
        if (identity.includes("pool")) result.pool.push(entityId);
        else if (identity.includes("spa")) result.spa.push(entityId);
        else result.shared.push(entityId);
      }
      if (["sensor", "binary_sensor"].includes(domain) && /(rpm|speed|flow|pressure|temperature|firmware|version|fault|online)/.test(identity)) {
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
