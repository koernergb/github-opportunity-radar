import { expect, test } from "@playwright/test";

const pages = ["Assistant", "Opportunities", "Repositories", "Preferences", "Runs", "Settings"];

test("all primary routes load and command palette is keyboard accessible", async ({ page }) => {
  await page.route("**/api/v1/readiness", (route) => route.fulfill({ json: { status: "ready", checks: {}, secrets: {} } }));
  await page.route("**/api/v1/opportunities**", (route) => route.fulfill({ json: { items: [], meta: { page: 1, page_size: 25, total: 0 } } }));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Good morning" })).toBeVisible();
  for (const name of pages) {
    await page.getByRole("link", { name }).click();
    await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
  }
  await page.keyboard.press("Control+k");
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeHidden();
});
