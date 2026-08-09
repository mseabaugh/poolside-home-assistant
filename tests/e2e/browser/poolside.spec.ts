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
  await expect
    .poll(async () => {
      const response = await request.get(`${process.env.FAKE_POOLSIDE_URL ?? "http://127.0.0.1:8080"}/test/state`);
      const body = await response.json();
      return body.desired.DesiredStates.find(
        (state: { ControlUUID: string }) => state.ControlUUID === "filter-one",
      ).Status;
    })
    .toBe("ON");
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
        .filter((state: { ControlUUID: string }) => ["filter-one", "heat-one"].includes(state.ControlUUID))
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
