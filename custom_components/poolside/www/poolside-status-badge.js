/** Compact Poolside homeowner status badge using explicitly configured entity IDs. */
class PoolsideStatusBadge extends HTMLElement {
  static getConfigElement() { return document.createElement("poolside-status-badge-editor"); }
  static getStubConfig() {
    return { lights_entity: "" };
  }

  setConfig(config) {
    if (!config || (!config.entity && !Object.keys(config).some((key) => key.endsWith("_entity")))) {
      throw new Error("poolside-status-badge requires at least one explicit entity ID");
    }
    for (const [key, value] of Object.entries(config)) {
      if (key.endsWith("_entity") && value != null && typeof value !== "string") {
        throw new Error(`${key} must be an entity ID`);
      }
    }
    if (config.entity != null && typeof config.entity !== "string") {
      throw new Error("entity must be an entity ID");
    }
    this.config = {
      ...config,
      lights_entity: config.lights_entity || config.entity,
    };
    const root = this.shadowRoot || this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        :host { display:inline-flex; max-width:min(100%, 760px); }
        .badge {
          display:flex; align-items:center; gap:10px; min-height:40px; max-width:100%;
          padding:5px 12px 5px 8px; box-sizing:border-box; border-radius:20px;
          color:var(--primary-text-color); background:var(--ha-card-background, var(--card-background-color));
          box-shadow:var(--ha-card-box-shadow, none); border:1px solid var(--divider-color);
          cursor:pointer; font-size:.78rem;
        }
        .brand { display:flex; align-items:center; gap:5px; flex:0 0 auto; font-weight:600; }
        .brand ha-icon { --mdc-icon-size:20px; color:var(--primary-color); }
        .metrics { display:flex; align-items:center; gap:8px; min-width:0; overflow-x:auto; scrollbar-width:none; }
        .metrics::-webkit-scrollbar { display:none; }
        .metric { display:inline-flex; align-items:center; gap:3px; white-space:nowrap; color:var(--secondary-text-color); }
        .metric ha-icon { --mdc-icon-size:15px; color:var(--state-icon-color, var(--primary-color)); }
        .value { color:var(--primary-text-color); font-weight:600; }
        .unavailable { opacity:.55; }
        @media (max-width:600px) { .label { display:none; } .badge { gap:7px; } .metrics { gap:7px; } }
      </style>
      <div class="badge" role="button" tabindex="0" aria-label="Poolside status">
        <span class="brand"><ha-icon icon="mdi:pool"></ha-icon><span class="name"></span></span>
        <span class="metrics"></span>
      </div>`;
    this._badge = root.querySelector(".badge");
    this._badge.addEventListener("click", () => this._openDetails());
    this._badge.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); this._openDetails(); }
    });
    this._render();
  }

  set hass(hass) { this._hass = hass; if (this.config) this._render(); }

  _state(key) {
    const entityId = this.config?.[key];
    return typeof entityId === "string" ? this._hass?.states?.[entityId] : undefined;
  }

  _number(state) {
    const value = Number(state?.state);
    return Number.isFinite(value) ? value : null;
  }

  _unit(state) { return state?.attributes?.unit_of_measurement || ""; }

  _format(state, kind, key) {
    const value = this._number(state);
    if (value === null) return null;
    if (kind === "temperature") return `${value.toFixed(2)}${this._unit(state) || "°F"}`;
    if (kind === "percent") {
      const maximumKey = key === "primary_pump_entity" ? "primary_pump_max" : "feature_pump_max";
      const maximum = Number(this.config?.[maximumKey]);
      const percent = this._unit(state) === "%" ? value : Number.isFinite(maximum) && maximum > 0 ? value * 100 / maximum : value;
      return `${Math.max(0, Math.min(100, percent)).toFixed(0)}%`;
    }
    return `${value.toFixed(2).replace(/\.00$/, "")}${this._unit(state) ? ` ${this._unit(state)}` : ""}`;
  }

  _metric(key, icon, label, kind) {
    const state = this._state(key);
    if (!state || ["unknown", "unavailable"].includes(state.state)) return "";
    let value;
    if (key === "lights_entity") {
      const brightness = Number(state.attributes?.brightness_percent);
      const fallback = Number(state.attributes?.brightness);
      const percent = Number.isFinite(brightness) ? brightness : Number.isFinite(fallback) ? fallback * 100 / 255 : state.state === "on" ? 100 : 0;
      value = `${Math.max(0, Math.min(100, percent)).toFixed(0)}%`;
    } else value = this._format(state, kind, key);
    if (value === null) return "";
    return `<span class="metric"><ha-icon icon="${icon}"></ha-icon><span class="label">${label}</span><span class="value">${value}</span></span>`;
  }

  _render() {
    if (!this._hass || !this.config || !this.shadowRoot) return;
    this.shadowRoot.querySelector(".name").textContent = this.config.name || "Poolside";
    const metrics = [
      this._metric("water_entity", "mdi:thermometer-water", "Water", "temperature"),
      this._metric("air_entity", "mdi:thermometer", "Air", "temperature"),
      this._metric("primary_pump_entity", "mdi:pump", "Main", "percent"),
      this._metric("feature_pump_entity", "mdi:pump", "Feature", "percent"),
      this._metric("lights_entity", "mdi:lightbulb-group", "Lights", "percent"),
      this._metric("ph_entity", "mdi:ph", "pH", "number"),
      this._metric("orp_entity", "mdi:water-check", "ORP", "number"),
    ].filter(Boolean);
    this.shadowRoot.querySelector(".metrics").innerHTML = metrics.join("");
    this._badge.classList.toggle("unavailable", metrics.length === 0);
  }

  _openDetails() {
    const entityId = this.config.details_entity || this.config.lights_entity || this.config.water_entity;
    if (!entityId) return;
    this.dispatchEvent(new CustomEvent("hass-more-info", { bubbles:true, composed:true, detail:{ entityId } }));
  }
}

/** Native Home Assistant visual editor for explicit Poolside badge entity IDs. */
class PoolsideStatusBadgeEditor extends HTMLElement {
  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._applyHass();
  }

  _render() {
    if (!this._config) return;
    const root = this.shadowRoot || this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        :host { display:block; }
        .editor { display:grid; gap:12px; padding:8px 0; }
        ha-textfield, ha-entity-picker { display:block; width:100%; }
      </style>
      <div class="editor">
        <ha-textfield data-key="name" label="Name"></ha-textfield>
        ${this._picker("water_entity", "Water temperature", "sensor")}
        ${this._picker("air_entity", "Air temperature", "sensor")}
        ${this._picker("primary_pump_entity", "Main pump percentage", "sensor")}
        ${this._picker("feature_pump_entity", "Feature pump percentage", "sensor")}
        ${this._picker("lights_entity", "All Poolside lights", "light")}
        ${this._picker("ph_entity", "pH", "sensor")}
        ${this._picker("orp_entity", "ORP", "sensor")}
      </div>`;
    const name = root.querySelector('[data-key="name"]');
    name.value = this._config.name || "";
    name.addEventListener("change", (event) => this._changed("name", event.target.value));
    for (const picker of root.querySelectorAll("ha-entity-picker")) {
      const key = picker.dataset.key;
      picker.value = this._config[key] || (key === "lights_entity" ? this._config.entity : "") || "";
      picker.addEventListener("value-changed", (event) => this._changed(key, event.detail?.value));
    }
    this._applyHass();
  }

  _picker(key, label, domain) {
    return `<ha-entity-picker data-key="${key}" label="${label}" include-domains='["${domain}"]' allow-custom-entity></ha-entity-picker>`;
  }

  _applyHass() {
    if (!this.shadowRoot || !this._hass) return;
    for (const picker of this.shadowRoot.querySelectorAll("ha-entity-picker")) picker.hass = this._hass;
  }

  _changed(key, value) {
    const config = { ...this._config };
    if (value) config[key] = value;
    else delete config[key];
    if (key === "lights_entity") delete config.entity;
    this._config = config;
    this.dispatchEvent(new CustomEvent("config-changed", {
      bubbles: true,
      composed: true,
      detail: { config },
    }));
  }
}

if (!customElements.get("poolside-status-badge")) customElements.define("poolside-status-badge", PoolsideStatusBadge);
if (!customElements.get("poolside-status-badge-editor")) customElements.define("poolside-status-badge-editor", PoolsideStatusBadgeEditor);
window.customBadges = window.customBadges || [];
if (!window.customBadges.some((badge) => badge.type === "poolside-status-badge")) {
  window.customBadges.push({
    type:"poolside-status-badge",
    name:"Poolside Status",
    description:"Compact temperatures, pumps, lights, and chemistry status.",
    preview:true,
    documentationURL:"https://github.com/mseabaugh/poolside-home-assistant",
  });
}
