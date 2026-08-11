/** Temperature-banded Poolside heater control backed only by a safe Climate entity. */
class PoolsideHeaterGauge extends HTMLElement {
  static getConfigElement() { return document.createElement("poolside-heater-gauge-editor"); }
  static getStubConfig() { return { entity: "" }; }
  getGridOptions() { return { columns: 6, min_columns: 4, rows: 5, min_rows: 4 }; }

  setConfig(config) {
    if (!config || typeof config.entity !== "string" || (config.entity && !config.entity.startsWith("climate."))) {
      throw new Error("poolside-heater-gauge requires a climate entity");
    }
    this.config = config;
    this._ranges = this._normalizeRanges(config.ranges);
    const root = this.shadowRoot || this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        :host { display:block; height:100%; }
        ha-card { height:100%; padding:16px; box-sizing:border-box; }
        .header,.mode { display:flex; align-items:center; justify-content:space-between; gap:12px; }
        .title { font-size:1rem; font-weight:600; }
        .gauge { position:relative; max-width:380px; margin:4px auto -8px; }
        svg { display:block; width:100%; overflow:visible; }
        .track,.band { fill:none; stroke-width:18; stroke-linecap:round; }
        .track { stroke:var(--divider-color); opacity:.55; }
        .band { transition:opacity .2s; }
        .needle { fill:var(--card-background-color); stroke:var(--primary-text-color); stroke-width:3; }
        .center { position:absolute; inset:31% 12% auto; text-align:center; pointer-events:none; }
        .status { font-size:.88rem; }
        .temperature { font-size:3rem; line-height:1.1; font-weight:400; }
        .temperature small { font-size:1rem; vertical-align:top; }
        .controls { display:grid; grid-template-columns:42px minmax(72px,1fr) 42px; gap:8px; align-items:center; max-width:280px; margin:0 auto; }
        button { border:1px solid var(--divider-color); border-radius:999px; background:var(--card-background-color); color:var(--primary-text-color); font-size:1.5rem; height:42px; cursor:pointer; }
        ha-textfield { width:100%; --md-filled-text-field-container-color:var(--secondary-background-color); }
        .mode { margin-top:12px; padding-top:12px; border-top:1px solid var(--divider-color); }
        .mode-label { display:flex; flex-direction:column; }
        .mode-label small { color:var(--secondary-text-color); }
        .legend { display:flex; justify-content:center; flex-wrap:wrap; gap:10px; margin-top:10px; font-size:.72rem; color:var(--secondary-text-color); }
        .key { display:inline-flex; align-items:center; gap:4px; }
        .swatch { width:9px; height:9px; border-radius:50%; }
        [hidden] { display:none !important; }
      </style>
      <ha-card>
        <div class="header"><span class="title"></span></div>
        <div class="gauge">
          <svg viewBox="0 0 300 220" role="img" aria-label="Heater target temperature">
            <path class="track"></path><g class="bands"></g><circle class="needle" r="9"></circle>
          </svg>
          <div class="center"><div class="status"></div><div class="temperature"></div></div>
        </div>
        <div class="controls"><button class="minus" aria-label="Decrease temperature">−</button><ha-textfield class="input" type="number" label="Set temperature"></ha-textfield><button class="plus" aria-label="Increase temperature">+</button></div>
        <div class="mode"><span class="mode-label"><strong>Heater</strong><small class="mode-state"></small></span><ha-switch class="toggle" aria-label="Heater on or off"></ha-switch></div>
        <div class="legend"></div>
      </ha-card>`;
    this._wire();
    this._render();
  }

  set hass(hass) { this._hass = hass; if (this.config) this._render(); }

  _normalizeRanges(ranges) {
    const defaults = [
      { min:32, max:59, color:"#2196f3" }, { min:59, max:75, color:"#26c6da" },
      { min:75, max:90, color:"#ffb74d" }, { min:90, max:100, color:"#ff7043" },
      { min:100, max:104, color:"#e53935" },
    ];
    if (!Array.isArray(ranges) || ranges.length < 2 || ranges.length > 5) return defaults;
    const parsed = ranges.map((range) => ({ min:Number(range.min), max:Number(range.max), color:String(range.color || "") }));
    return parsed.every((range) => Number.isFinite(range.min) && Number.isFinite(range.max) && range.max > range.min && range.color) ? parsed : defaults;
  }

  _point(value, min, max) {
    const ratio = Math.max(0, Math.min(1, (value - min) / (max - min)));
    const angle = (135 + ratio * 270) * Math.PI / 180;
    return { x:150 + 112 * Math.cos(angle), y:150 + 112 * Math.sin(angle) };
  }

  _arc(start, end, min, max) {
    const first = this._point(start, min, max), last = this._point(end, min, max);
    const sweep = ((end - start) / (max - min)) * 270;
    return `M ${first.x} ${first.y} A 112 112 0 ${sweep > 180 ? 1 : 0} 1 ${last.x} ${last.y}`;
  }

  _wire() {
    const root = this.shadowRoot;
    root.querySelector(".minus").addEventListener("click", () => this._adjust(-1));
    root.querySelector(".plus").addEventListener("click", () => this._adjust(1));
    root.querySelector(".input").addEventListener("change", (event) => this._setTemperature(Number(event.target.value)));
    root.querySelector(".toggle").addEventListener("change", (event) => this._setMode(event.target.checked ? "heat" : "off"));
  }

  _render() {
    if (!this._hass || !this.config || !this.shadowRoot) return;
    const state = this._hass.states[this.config.entity];
    if (!state) {
      const root = this.shadowRoot;
      root.querySelector(".title").textContent = this.config.name || "Poolside heater";
      root.querySelector(".status").textContent = this.config.entity
        ? `Entity not found: ${this.config.entity}`
        : "Select a Poolside heater entity";
      root.querySelector(".temperature").textContent = "—";
      root.querySelector(".input").disabled = true;
      root.querySelector(".minus").disabled = true;
      root.querySelector(".plus").disabled = true;
      root.querySelector(".toggle").disabled = true;
      return;
    }
    const attrs = state.attributes || {};
    const min = Number.isFinite(Number(this.config.min)) ? Number(this.config.min) : 32;
    const max = Number.isFinite(Number(this.config.max)) ? Number(this.config.max) : 104;
    const target = Number(attrs.temperature ?? attrs.target_temperature);
    const safeTarget = Number.isFinite(target) ? Math.max(min, Math.min(max, target)) : min;
    const on = state.state === "heat";
    const root = this.shadowRoot;
    root.querySelector(".title").textContent = this.config.name || attrs.friendly_name || "Pool heater";
    root.querySelector(".status").textContent = on ? (attrs.hvac_action === "heating" ? "Heating" : "On") : "Off";
    root.querySelector(".temperature").innerHTML = `${this._escape(String(Math.round(safeTarget * 100) / 100))}<small>°F</small>`;
    root.querySelector(".track").setAttribute("d", this._arc(min, max, min, max));
    root.querySelector(".bands").innerHTML = this._ranges.map((range) => {
      const start = Math.max(min, range.min), end = Math.min(max, range.max);
      return end > start ? `<path class="band" d="${this._arc(start, end, min, max)}" stroke="${this._escape(range.color)}"></path>` : "";
    }).join("");
    const point = this._point(safeTarget, min, max);
    root.querySelector(".needle").setAttribute("cx", point.x); root.querySelector(".needle").setAttribute("cy", point.y);
    const input = root.querySelector(".input"); input.disabled = false; input.value = safeTarget; input.min = min; input.max = max; input.step = attrs.target_temp_step || 1;
    root.querySelector(".minus").disabled = false;
    root.querySelector(".plus").disabled = false;
    root.querySelector(".toggle").checked = on;
    root.querySelector(".toggle").disabled = state.state === "unavailable";
    root.querySelector(".mode-state").textContent = on ? "On" : "Off";
    root.querySelector(".legend").innerHTML = this._ranges.map((range) => `<span class="key"><i class="swatch" style="background:${this._escape(range.color)}"></i>${range.min}–${range.max}°</span>`).join("");
  }

  _adjust(direction) {
    const input = this.shadowRoot.querySelector(".input");
    const step = Number(input.step) || 1;
    this._setTemperature(Number(input.value) + direction * step);
  }
  _setTemperature(temperature) {
    const input = this.shadowRoot.querySelector(".input");
    if (!Number.isFinite(temperature)) return;
    const value = Math.max(Number(input.min), Math.min(Number(input.max), temperature));
    return this._hass.callService("climate", "set_temperature", { entity_id:this.config.entity, temperature:value });
  }
  _setMode(hvac_mode) { return this._hass.callService("climate", "set_hvac_mode", { entity_id:this.config.entity, hvac_mode }); }
  _escape(value) { return value.replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]); }
}

/** Native visual editor that requires an explicit Home Assistant Climate ID. */
class PoolsideHeaterGaugeEditor extends HTMLElement {
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
        .range { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
      </style>
      <div class="editor">
        <ha-entity-picker data-key="entity" label="Poolside heater" include-domains='["climate"]' allow-custom-entity></ha-entity-picker>
        <ha-textfield data-key="name" label="Name"></ha-textfield>
        <div class="range">
          <ha-textfield data-key="min" label="Minimum temperature" type="number"></ha-textfield>
          <ha-textfield data-key="max" label="Maximum temperature" type="number"></ha-textfield>
        </div>
      </div>`;
    for (const field of root.querySelectorAll("ha-textfield")) {
      const key = field.dataset.key;
      field.value = this._config[key] ?? "";
      field.addEventListener("change", (event) => {
        const raw = event.target.value;
        this._changed(key, ["min", "max"].includes(key) && raw !== "" ? Number(raw) : raw);
      });
    }
    const picker = root.querySelector("ha-entity-picker");
    picker.value = this._config.entity || "";
    picker.addEventListener("value-changed", (event) => this._changed("entity", event.detail?.value));
    this._applyHass();
  }

  _applyHass() {
    const picker = this.shadowRoot?.querySelector("ha-entity-picker");
    if (picker && this._hass) picker.hass = this._hass;
  }

  _changed(key, value) {
    const config = { ...this._config };
    if (value !== "" && value != null) config[key] = value;
    else delete config[key];
    this._config = config;
    this.dispatchEvent(new CustomEvent("config-changed", {
      bubbles: true,
      composed: true,
      detail: { config },
    }));
  }
}

if (!customElements.get("poolside-heater-gauge")) customElements.define("poolside-heater-gauge", PoolsideHeaterGauge);
if (!customElements.get("poolside-heater-gauge-editor")) customElements.define("poolside-heater-gauge-editor", PoolsideHeaterGaugeEditor);
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "poolside-heater-gauge")) window.customCards.push({ type:"poolside-heater-gauge", name:"Poolside Heater Gauge", description:"Heater control with configurable temperature color bands.", preview:true });
