import { expect, test, type Page } from "@playwright/test";

const password = "Synthetic-Test-Password-2026!";

async function completeOnboarding(page: Page): Promise<void> {
  await page.goto("/");
  const createHome = page.getByRole("button", { name: /create my smart home/i });
  const login = page.getByRole("textbox", { name: /^(email|username)/i });
  await expect(createHome.or(login)).toBeVisible({ timeout: 60_000 });

  if (!(await createHome.isVisible().catch(() => false))) {
    await login.fill("synthetic-owner");
    await page.getByRole("textbox", { name: /^password/i }).fill(password);
    await page.getByRole("button", { name: /log in/i }).click();
    await page.waitForURL((url) => url.pathname.startsWith("/lovelace"), {
      timeout: 60_000,
    });
    return;
  }

  await createHome.click();
  await page.getByRole("textbox", { name: /^name/i }).fill("Synthetic Owner");
    await page.getByRole("textbox", { name: /^(email|username)/i }).fill("synthetic-owner");
  await page.getByRole("textbox", { name: /^password/i }).fill(password);
  await page.getByRole("textbox", { name: /^confirm password/i }).fill(password);
  await page.getByRole("button", { name: /create account/i }).click();

  for (let step = 0; step < 5; step += 1) {
    await page.waitForTimeout(1_500);
    if (!new URL(page.url()).pathname.includes("onboarding")) return;
    const next = page.getByRole("button", { name: /next|finish|skip/i }).last();
    await expect(next).toBeVisible({ timeout: 30_000 });
    await next.click();
  }
  await page.waitForURL((url) => url.pathname.startsWith("/lovelace"), {
    timeout: 60_000,
  });
}

test("user adds Poolside and safely shuts down an active water-flow group", async ({
  page,
  request,
}) => {
  await completeOnboarding(page);
  await page.goto("/config/integrations");
  const addIntegration = page
    .getByRole("button", { name: /add integration/i })
    .or(page.locator('[aria-label="Add integration"]'))
    .first();
  await expect(addIntegration).toBeVisible({ timeout: 60_000 });
  await addIntegration.click();
  const brandDialog = page.getByRole("dialog").last();
  await expect(brandDialog).toBeVisible({ timeout: 60_000 });
  const search = page.getByPlaceholder("Search for a brand name", { exact: true });
  await expect(search).toBeVisible();
  await search.fill("Poolside");
  await expect(search).toHaveValue("Poolside");
  const poolsideBrand = page.getByText("Poolside", { exact: true }).last();
  await expect(poolsideBrand).toBeVisible({ timeout: 60_000 });
  await poolsideBrand.click();
  await page.getByRole("textbox", { name: /^(email|username)/i }).fill("synthetic-owner");
  await page.getByRole("textbox", { name: /^password/i }).fill(password);
  await page.getByRole("button", { name: /submit/i }).click();
  await expect(page.getByText("The Attendant", { exact: true })).toBeVisible({
    timeout: 60_000,
  });
  await page.getByRole("button", { name: /skip and finish|finish/i }).click();
  await expect
    .poll(
      () =>
        page.locator("home-assistant").evaluate((app: any) => {
          const states = Object.entries(app.hass?.states ?? {}) as [string, any][];
          const modeReady = states.some(
            ([id, state]) =>
              id.startsWith("select.") &&
              Array.isArray(state.attributes?.options) &&
              state.attributes.options.includes("Pool") &&
              state.attributes.options.includes("Spa"),
          );
          const filterRateReady = states.some(
            ([id, state]) =>
              id.startsWith("number.") &&
              /filter.*power level/i.test(
                `${state.attributes?.friendly_name ?? ""} ${state.attributes?.poolside_name ?? ""}`,
              ),
          );
          return modeReady && filterRateReady;
        }),
      { timeout: 60_000, message: "Poolside entities should finish platform setup" },
    )
    .toBe(true);

  await page.reload();
  await expect
    .poll(
      () => page.evaluate(() => Boolean(customElements.get("poolside-status-badge"))),
      { timeout: 60_000, message: "Poolside status badge module should register after reload" },
    )
    .toBe(true);
  const statusBadge = page.locator("poolside-status-badge").last();
  await page.locator("home-assistant").evaluate((app: any) => {
    const states = Object.entries(app.hass.states) as [string, any][];
    const byUniqueName = (pattern: RegExp) =>
      states.find(([, state]) => pattern.test(state.attributes?.friendly_name ?? ""))?.[0];
    const card = document.createElement("poolside-status-badge") as any;
    card.setConfig({
      name: "Poolside",
      water_entity: byUniqueName(/water.*thermistor/i),
      air_entity: byUniqueName(/air.*temperature/i),
      lights_entity: byUniqueName(/all lights/i),
    });
    card.hass = app.hass;
    document.body.append(card);
  });
  await expect(statusBadge).toBeVisible({ timeout: 60_000 });
  await expect(statusBadge.locator(".name")).toHaveText("Poolside");
  // The synthetic site only exposes the aggregate light among these configured
  // values. Missing telemetry must be hidden instead of rendering Unknown.
  await expect(statusBadge.locator(".metric")).toHaveCount(1);
  await expect(statusBadge.locator(".metric")).toContainText("Lights");
  await expect(statusBadge).not.toContainText(/unknown|unavailable/i);

  const badgeEditor = page.locator("poolside-status-badge-editor").last();
  await page.locator("home-assistant").evaluate((app: any) => {
    const lights = Object.entries(app.hass.states).find(
      ([id, state]: [string, any]) =>
        id.startsWith("light.") && /all lights/i.test(state.attributes?.friendly_name ?? ""),
    )?.[0];
    if (!lights) throw new Error("Poolside aggregate light was not created");
    const editor = document.createElement("poolside-status-badge-editor") as any;
    editor.setConfig({ type: "custom:poolside-status-badge", entity: lights });
    editor.hass = app.hass;
    document.body.append(editor);
  });
  await expect(badgeEditor).toBeVisible();
  await expect(badgeEditor.locator('ha-entity-picker[data-key="lights_entity"]')).toHaveCount(1);

  const gaugeEditor = page.locator("poolside-heater-gauge-editor").last();
  await page.locator("home-assistant").evaluate((app: any) => {
    const editor = document.createElement("poolside-heater-gauge-editor") as any;
    editor.setConfig({ type: "custom:poolside-heater-gauge", entity: "" });
    editor.hass = app.hass;
    document.body.append(editor);
  });
  await expect(gaugeEditor).toBeVisible();
  await expect(gaugeEditor.locator('ha-entity-picker[data-key="entity"]')).toHaveCount(1);

  await page.goto("/lovelace/0");
  // A full navigation is intentional: it verifies the integration registers
  // its bundled card module in a fresh frontend, not only in an already warm
  // browser tab.
  await page.reload();
  const dashboard = page.locator("poolside-dashboard");
  await expect(dashboard).toBeVisible({ timeout: 60_000 });
  await dashboard.evaluate((card: any) => {
    // Home Assistant may reapply card configuration while editing or restoring
    // a dashboard. Reconfiguration must not replace the card with a blank view.
    card.setConfig(card.config);
  });
  await expect(dashboard.getByText("Water and chemistry — 24 hours", { exact: true })).toBeVisible();

  const filterPercentage = dashboard
    .locator(".feature")
    .filter({ hasText: "Filter" })
    .locator(".feature-number");
  await expect(filterPercentage).toBeVisible();
  await filterPercentage.evaluate((slider: any) => {
    slider.value = 55;
    slider.dispatchEvent(new Event("change", { bubbles: true, composed: true }));
  });
  await expect
    .poll(async () => {
      const response = await request.get(
        `${process.env.FAKE_POOLSIDE_URL ?? "http://127.0.0.1:8080"}/test/state`,
      );
      const body = await response.json();
      return body.desired.DesiredStates.find(
        (state: { ControlUUID: string }) => state.ControlUUID === "filter-one",
      ).PowerLevel;
    })
    .toBe(55);

  const bodySelector = page.locator("poolside-body-selector").last();
  await page.locator("home-assistant").evaluate((app: any) => {
    const hass = app.hass;
    const entityId = Object.entries(hass.states).find(
      ([id, state]: [string, any]) =>
        id.startsWith("select.") && state.attributes?.friendly_name?.includes("Dashboard body"),
    )?.[0];
    if (!entityId) throw new Error("Poolside dashboard body selector was not created");
    const card = document.createElement("poolside-body-selector") as any;
    card.setConfig({ entity: entityId });
    card.setConfig({ entity: entityId, name: "Pool / Spa" });
    card.hass = hass;
    document.body.append(card);
  });
  await expect(bodySelector).toBeVisible({ timeout: 60_000 });
  await expect(bodySelector.getByRole("button", { name: "Select Off" })).toHaveText("Off");
  await expect(bodySelector.getByRole("button", { name: "Select Pool" })).toHaveText("Pool");
  await expect(bodySelector.getByRole("button", { name: "Select Spa" })).toHaveText("Spa");
  await bodySelector.getByRole("button", { name: "Select Spa" }).click();
  await expect
    .poll(() =>
      page.locator("home-assistant").evaluate((app: any) =>
        Object.entries(app.hass.states).find(
          ([id, state]: [string, any]) =>
            id.startsWith("select.") && state.attributes?.friendly_name?.includes("Dashboard body"),
        )?.[1]?.state,
      ),
    )
    .toBe("Spa");
  await bodySelector.evaluate((card: any) => {
    card.hass = document.querySelector("home-assistant")?.hass;
  });
  await expect(bodySelector.locator(".state")).toContainText("Spa");
  await dashboard.evaluate((card: any) => {
    card.hass = document.querySelector("home-assistant")?.hass;
  });
  const heaterToggle = dashboard.locator(".heater ha-switch.toggle");
  await expect(heaterToggle).toBeVisible();
  await expect(heaterToggle).toHaveAttribute("data-entity", /^switch\./);
  page.once("dialog", async (dialog) => {
    expect(dialog.message()).toContain("switch water flow to Spa");
    await dialog.accept();
  });
  await heaterToggle.evaluate((toggle: any) => {
    toggle.checked = true;
    toggle.dispatchEvent(new Event("change", { bubbles: true, composed: true }));
  });
  await expect
    .poll(async () => {
      const response = await request.get(
        `${process.env.FAKE_POOLSIDE_URL ?? "http://127.0.0.1:8080"}/test/state`,
      );
      const body = await response.json();
      return body.desired.DesiredStates.find(
        (state: { ControlUUID: string }) => state.ControlUUID === "heat-one",
      ).Status;
    })
    .toBe("ON");
  await expect
    .poll(async () => {
      const response = await request.get(`${process.env.FAKE_POOLSIDE_URL ?? "http://127.0.0.1:8080"}/test/state`);
      const body = await response.json();
      return body.desired.DesiredStates
        .filter((state: { ControlUUID: string }) =>
          ["filter-one", "spa-filter"].includes(state.ControlUUID),
        )
        .map((state: { Status: string }) => state.Status)
        .join(",");
    })
    .toBe("OFF,ON");
  const fakeUrl = process.env.FAKE_POOLSIDE_URL ?? "http://127.0.0.1:8080";
  page.once("dialog", (dialog) => dialog.accept());
  // The test-only card is appended outside HA's application shell. Dispatch the
  // component's click event directly so the shell cannot intercept its pointer
  // coordinates; this still executes the same card event handler a user click
  // invokes.
  await bodySelector.getByRole("button", { name: "Select Off" }).dispatchEvent("click");
  await expect
    .poll(async () => {
      const response = await request.get(`${fakeUrl}/test/state`);
      const body = await response.json();
      return body.desired.DesiredStates
        .filter((state: { ControlUUID: string }) => ["filter-one", "spa-filter", "heat-one"].includes(state.ControlUUID))
        .every((state: { Status: string }) => state.Status === "OFF");
    })
    .toBe(true);
  await expect
    .poll(async () => {
      const response = await request.get(`${fakeUrl}/test/state`);
      const body = await response.json();
      return body.desired.DesiredStates.find(
        (state: { ControlUUID: string }) => state.ControlUUID === "light-one",
      ).Status;
    })
    .toBe("ON");
});
