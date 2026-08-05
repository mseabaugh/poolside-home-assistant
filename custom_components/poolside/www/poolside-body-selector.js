/**
 * Poolside multi-state body selector.
 *
 * The card is presentation only. The Poolside select entity remains the
 * authoritative XOR state and validates every requested option.
 */
class PoolsideBodySelector extends HTMLElement {
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
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `
      <style>
        :host { display:block; }
        ha-card { padding: 16px; }
        .heading { font-size: 1.05rem; font-weight: 600; }
        .state { opacity: .75; font-size: .82rem; margin-top: 2px; }
        .rail {
          position: relative;
          margin-top: 18px;
          border-radius: 16px;
          height: 34px;
          background: #e1e2e6;
          overflow: hidden;
        }
        .fill {
          position: absolute;
          inset: 0;
          right: auto;
          width: 0%;
          background: #d4d4d9;
          border-radius: 16px 0 0 16px;
          transition: width 0.2s ease;
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
          font-size: 0;
          min-width: 0;
          position: relative;
          z-index: 3;
        }
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
      </style>
      <ha-card>
        <div class="heading"></div><div class="state"></div>
        <div class="rail">
          <div class="fill" id="fill"></div>
          <div class="segments" id="segments"></div>
          <div class="thumb"><span class="thumb-symbol"></span></div>
        </div>
        <div class="confirm" hidden></div>
      </ha-card>`;
    this._heading = this.shadowRoot.querySelector(".heading");
    this._state = this.shadowRoot.querySelector(".state");
    this._rail = this.shadowRoot.querySelector(".rail");
    this._segments = this.shadowRoot.querySelector("#segments");
    this._fill = this.shadowRoot.querySelector("#fill");
    this._thumb = this.shadowRoot.querySelector(".thumb");
    this._thumbSymbol = this.shadowRoot.querySelector(".thumb-symbol");
    this._confirm = this.shadowRoot.querySelector(".confirm");
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

    this._heading.textContent = this.config.name || "Active body";
    this._state.textContent = entity.state === "unknown" ? "Waiting for confirmation" : entity.state;
    const states = names.length;
    this._segments.style.gridTemplateColumns = `repeat(${states}, minmax(0, 1fr))`;
    this._segments.querySelectorAll(".segment").forEach((node) => node.remove());
    this._fill.style.width = "0%";
    this._thumb.style.left = "0%";
    this._thumbSymbol.textContent = this._symbolForOption(entity.state);

    const selectedIndex = Math.max(names.indexOf(entity.state), 0);
    const maxIndex = Math.max(states - 1, 1);
    const selectedPercent = (selectedIndex / maxIndex) * 100;
    const fillPercent = ((selectedIndex + 1) / states) * 100;
    this._fill.style.width = `${fillPercent}%`;
    this._thumb.style.left = `${selectedPercent}%`;

    names.forEach((option) => {
      const button = document.createElement("button");
      button.className = "segment";
      button.type = "button";
      button.setAttribute("aria-label", `Select ${option}`);
      button.setAttribute("aria-pressed", option === entity.state ? "true" : "false");
      button.style.display = "block";
      button.setAttribute("aria-label", `Select ${this._escape(option)}`);
      button.addEventListener("click", () => this._select(option, entity.state));
      this._segments.appendChild(button);
    });
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
    const currentIsBody = current && current.toLowerCase() !== "off";
    const targetIsBody = option.toLowerCase() !== "off";
    if (currentIsBody && targetIsBody) {
      const message = `Switch from ${current} to ${option}? This will turn off the other body of water.`;
      if (!window.confirm(message)) return;
    }
    this._confirm.hidden = false;
    this._confirm.textContent = `Applying ${option}…`;
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

customElements.define("poolside-body-selector", PoolsideBodySelector);

// Lovelace discovers custom cards through this registry. Without it the resource
// can load successfully but the card will not appear in the dashboard picker.
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === "poolside-body-selector")) {
  window.customCards.push({
    type: "poolside-body-selector",
    name: "Poolside Body Selector",
    description: "Multi-state body-of-water selector with confirmation.",
    preview: true,
  });
}
