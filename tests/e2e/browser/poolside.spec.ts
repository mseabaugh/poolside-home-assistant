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

test("user adds Poolside and a UI switch round-trips through the application", async ({
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
  await expect(page.locator("poolside-dashboard")).toBeVisible({ timeout: 60_000 });
  const row = page.locator("hui-toggle-entity-row").filter({ hasText: "Filter" });
  await expect(row).toBeVisible({ timeout: 60_000 });
  const toggle = row.locator("ha-switch");
  await expect.poll(() => toggle.evaluate((element: any) => element.checked)).toBe(true);
  await toggle.click();
  await expect.poll(() => toggle.evaluate((element: any) => element.checked)).toBe(false);

  const fakeUrl = process.env.FAKE_POOLSIDE_URL ?? "http://127.0.0.1:8080";
  await expect
    .poll(async () => {
      const response = await request.get(`${fakeUrl}/test/state`);
      const body = await response.json();
      return body.desired.DesiredStates.find(
        (state: { ControlUUID: string }) => state.ControlUUID === "filter-one",
      ).Status;
    })
    .toBe("OFF");
});
