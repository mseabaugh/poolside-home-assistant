/**
 * Poolside multi-state body selector.
 *
 * Selecting a body is presentation only. Poolside validates the only physical
 * action exposed here: the confirmed high-level water-flow shutdown for Off.
 */
class PoolsideBodySelector extends HTMLElement {
  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: 2, min_rows: 2 };
  }

  static getConfigElement() {
    return document.createElement("poolside-body-selector");
  }

  static getStubConfig() {
    return { entity: "select.poolside_active_body" };
  }

  setConfig(config) {
    if (!config || typeof config.entity !== "string") {
      throw new Error("poolside-body-selector requires an entity");
    }
    this.config = config;
    const root = this.shadowRoot || this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        :host { display:block; width:100%; grid-column:1 / -1; }
        ha-card {
          box-sizing:border-box;
          width:100%;
          max-width:var(--poolside-selector-max-width, none);
          margin-inline:auto;
          padding:var(--poolside-selector-card-padding, 16px);
        }
        .heading { font-size: 1.05rem; font-weight: 600; }
        .state { opacity: .75; font-size: .82rem; margin-top: 2px; }
        .rail {
          position: relative;
          margin-top: 18px;
          border-radius: var(--poolside-selector-radius, 22px);
          height: var(--poolside-selector-height, 44px);
          background: var(--secondary-background-color);
          overflow: hidden;
        }
        .fill {
          position: absolute;
          top: 4px;
          bottom: 4px;
          left: 0;
          right: auto;
          width: 0%;
          background: var(--primary-color);
          border-radius: calc(var(--poolside-selector-radius, 22px) - 4px);
          transition: left 0.2s ease, width 0.2s ease;
        }
        .segments {
          position: absolute;
          inset: 0;
          display: grid;
        }
        .segment {
          border: 0;
          margin: 0;
          padding: 0;
          background: transparent;
          cursor: pointer;
          color: var(--primary-text-color);
          font: inherit;
          font-size: .95rem;
          min-width: 0;
          position: relative;
          z-index: 3;
        }
        .segment[aria-pressed="true"] { color: var(--text-primary-color); font-weight: 600; }
        .segment:disabled { cursor: wait; opacity: .65; }
        .segment:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
        .thumb {
          position: absolute;
          top: 7px;
          width: 20px;
          height: 20px;
          border-radius: 999px;
          background: #8f939b;
          display: flex;
          align-items: center;
          justify-content: center;
          color: #fff;
          font-size: 11px;
          transform: translateX(-50%);
          transition: left 0.2s ease;
          z-index: 4;
          pointer-events: none;
          display: none;
        }
        .thumb-symbol {
          font-size: 11px;
          line-height: 1;
          letter-spacing: -1px;
          opacity: 0.9;
        }
        .thumb::before {
          content: "";
          width: 2px;
          height: 8px;
          border-radius: 1px;
          background: currentColor;
          box-shadow: 2px 0 0 currentColor, 4px 0 0 currentColor, 6px 0 0 currentColor;
        }
        .confirm { color: var(--warning-color); font-size:.78rem; margin-top:14px; }
        .flow-note { opacity:.7; font-size:.75rem; margin-top:8px; }
      </style>
      <ha-card>
        <div class="heading"></div><div class="state"></div>
        <div class="flow-note">Pool and Spa select the dashboard view. Off safely turns off active water-flow Controls.</div>
        <div class="rail">
          <div class="fill" id="fill"></div>
          <div class="segments" id="segments"></div>
          <div class="thumb"><span class="thumb-symbol"></span></div>
        </div>
        <div class="confirm" hidden></div>
      </ha-card>`;
    this._heading = root.querySelector(".heading");
    this._state = root.querySelector(".state");
    this._rail = root.querySelector(".rail");
    this._segments = root.querySelector("#segments");
    this._fill = root.querySelector("#fill");
    this._thumb = root.querySelector(".thumb");
    this._thumbSymbol = root.querySelector(".thumb-symbol");
    this._confirm = root.querySelector(".confirm");
    this._applyLayoutConfig();
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (this.config) this._render();
  }

  _render() {
    if (!this._hass || !this.config || !this._rail) return;
    const entity = this._hass.states[this.config.entity];
    if (!entity) return;
    const options = Array.isArray(entity.attributes.options)
      ? entity.attributes.options
      : [entity.state];
    const names = options.filter((option) => typeof option === "string" && option.length);
    if (!names.length) return;

    this._heading.textContent = this.config.name || "Dashboard body";
    const unavailableReason = entity.attributes?.flow_procedure_reason;
    const confirmedFlow = entity.attributes?.confirmed_water_flow;
    this._state.textContent = entity.attributes?.transition_state
      ? `Changing flow: ${entity.attributes.transition_state}`
      : entity.state === "unavailable" && unavailableReason
        ? `Unavailable: ${unavailableReason}`
        : entity.state === "unknown" ? "Waiting for confirmation"
          : confirmedFlow ? `${entity.state} · confirmed flow: ${confirmedFlow}` : entity.state;
    const states = names.length;
    const weights = this._segmentWeights(states);
    this._segments.style.gridTemplateColumns = weights.map((weight) => `${weight}fr`).join(" ");
    this._segments.querySelectorAll(".segment").forEach((node) => node.remove());
    this._fill.style.width = "0%";
    this._fill.style.left = "0%";
    this._thumb.style.left = "0%";
    this._thumbSymbol.textContent = this._symbolForOption(entity.state);

    const selectedIndex = Math.max(names.indexOf(entity.state), 0);
    const totalWeight = weights.reduce((total, weight) => total + weight, 0);
    const precedingWeight = weights.slice(0, selectedIndex).reduce((total, weight) => total + weight, 0);
    const selectedPercent = (precedingWeight / totalWeight) * 100;
    const selectedWidth = (weights[selectedIndex] / totalWeight) * 100;
    this._fill.style.width = `${selectedWidth}%`;
    this._fill.style.left = `${selectedPercent}%`;
    this._thumb.style.left = `${selectedPercent + (selectedWidth / 2)}%`;

    names.forEach((option) => {
      const button = document.createElement("button");
      button.className = "segment";
      button.type = "button";
      button.setAttribute("aria-label", `Select ${option}`);
      button.setAttribute("aria-pressed", option === entity.state ? "true" : "false");
      button.style.display = "block";
      button.setAttribute("aria-label", `Select ${this._escape(option)}`);
      button.textContent = option;
      button.addEventListener("click", () => this._select(option, entity.state));
      if (entity.attributes?.transition_state || entity.state === "unavailable") button.disabled = true;
      this._segments.appendChild(button);
    });
  }

  _applyLayoutConfig() {
    const number = (value, fallback, minimum, maximum) => {
      const parsed = Number(value);
      return Number.isFinite(parsed) ? Math.max(minimum, Math.min(maximum, parsed)) : fallback;
    };
    const padding = number(this.config.card_padding, 16, 0, 48);
    const height = number(this.config.rail_height, 44, 32, 96);
    const radius = number(this.config.border_radius, Math.round(height / 2), 0, 48);
    const maxWidth = number(this.config.max_width, 0, 240, 2400);
    this.style.setProperty("--poolside-selector-card-padding", `${padding}px`);
    this.style.setProperty("--poolside-selector-height", `${height}px`);
    this.style.setProperty("--poolside-selector-radius", `${radius}px`);
    this.style.setProperty("--poolside-selector-max-width", maxWidth ? `${maxWidth}px` : "none");
  }

  _segmentWeights(count) {
    const configured = this.config?.segment_widths;
    if (!Array.isArray(configured) || configured.length !== count) return Array(count).fill(1);
    const weights = configured.map(Number);
    return weights.every((weight) => Number.isFinite(weight) && weight > 0) ? weights : Array(count).fill(1);
  }

  _symbolForOption(option) {
    const normalized = (option || "").toLowerCase();
    if (normalized === "off") return "⛶";
    if (normalized === "pool") return "◍";
    if (normalized === "spa") return "◉";
    return "▣";
  }

  async _select(option, current) {
    if (option === current) return;
    if (option.toLowerCase() === "off") {
      const message = "Turn off active water-flow Controls for this connected group? Poolside will preserve lights, saved set points, schedules, and diagnostics.";
      if (!window.confirm(message)) return;
    }
    this._confirm.hidden = false;
    this._confirm.textContent = option.toLowerCase() === "off" ? "Requesting safe shutdown…" : `Showing ${option}…`;
    try {
      await this._hass.callService("select", "select_option", {
        entity_id: this.config.entity,
        option,
      });
    } finally {
      this._confirm.hidden = true;
    }
  }

  _escape(value) {
    return value.replace(/[&<>"']/g, (character) => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" })[character]);
  }
}

if (!customElements.get("poolside-body-selector")) {
  customElements.define("poolside-body-selector", PoolsideBodySelector);
}

// Lovelace discovers custom cards through this registry. Without it the resource
// can load successfully but the card will not appear in the dashboard picker.
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "poolside-body-selector")) {
  window.customCards.push({
    type: "poolside-body-selector",
    name: "Poolside Body Selector",
    description: "Dashboard body selector with safe water-flow shutdown.",
    preview: true,
  });
}
