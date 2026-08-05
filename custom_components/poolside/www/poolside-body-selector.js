/**
 * Poolside multi-state body selector.
 *
 * The card is presentation only. The Poolside select entity remains the
 * authoritative XOR state and validates every requested option.
 */
class PoolsideBodySelector extends HTMLElement {
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
        .rail { position: relative; display: grid; gap: 4px; margin: 18px 4px 2px; }
        .track { position:absolute; left: 5%; right: 5%; top: 14px; height: 4px;
          border-radius: 4px; background: var(--divider-color); }
        .stop { position: relative; z-index: 1; border:0; background:transparent;
          color: var(--secondary-text-color); cursor:pointer; font:inherit; padding:0;
          min-width: 0; }
        .dot { width: 18px; height:18px; margin:0 auto 7px; border-radius:50%;
          border:3px solid var(--ha-card-background, var(--card-background-color));
          background: var(--disabled-color); box-sizing:border-box; }
        .stop[selected] { color: var(--primary-text-color); font-weight:600; }
        .stop[selected] .dot { background: var(--primary-color); box-shadow: 0 0 0 3px var(--primary-color); }
        .stop:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 4px; border-radius: 4px; }
        .confirm { color: var(--warning-color); font-size:.78rem; margin-top:14px; }
      </style>
      <ha-card>
        <div class="heading"></div><div class="state"></div>
        <div class="rail"><div class="track"></div></div>
        <div class="confirm" hidden></div>
      </ha-card>`;
    this._heading = this.shadowRoot.querySelector(".heading");
    this._state = this.shadowRoot.querySelector(".state");
    this._rail = this.shadowRoot.querySelector(".rail");
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
    this._heading.textContent = this.config.name || "Active body";
    this._state.textContent = entity.state === "unknown" ? "Waiting for confirmation" : entity.state;
    this._rail.style.gridTemplateColumns = `repeat(${Math.max(names.length, 1)}, minmax(0, 1fr))`;
    this._rail.querySelectorAll(".stop").forEach((node) => node.remove());
    names.forEach((option) => {
      const button = document.createElement("button");
      button.className = "stop";
      button.type = "button";
      button.setAttribute("aria-label", `Select ${option}`);
      button.innerHTML = `<div class="dot"></div><span>${this._escape(option)}</span>`;
      if (option === entity.state) {
        button.setAttribute("selected", "");
        button.setAttribute("aria-pressed", "true");
      } else {
        button.setAttribute("aria-pressed", "false");
      }
      button.addEventListener("click", () => this._select(option, entity.state));
      this._rail.appendChild(button);
    });
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
