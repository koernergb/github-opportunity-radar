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

test("opportunity filters survive inspector feedback flow", async ({ page }) => {
  const item = { issue_id: "00000000-0000-0000-0000-000000000042", repository: "owner/repo", number: 42, title: "Safe issue", url: "https://github.com/owner/repo/issues/42", score: 80, confidence: 0.3, effort_low_hours: 2, effort_high_hours: 4, fit: 0.8, merge_estimate: 0.5, merge_band: "moderate", merge_is_heuristic: true, warnings: ["active_linked_pr"], missing_evidence: ["history"], updated_at: "2026-08-08T00:00:00Z", scored_at: "2026-08-08T00:00:00Z" };
  await page.route("**/api/v1/opportunities?**", (route) => route.fulfill({ json: { items: [item], meta: { page: 1, page_size: 100, total: 1 } } }));
  await page.route("**/api/v1/opportunities/*/feedback", (route) => route.fulfill({ status: 201, json: { feedback_id: "00000000-0000-0000-0000-000000000099", issue_id: item.issue_id, status: "interested", note: null, pr_url: null, created_at: "2026-08-08T00:00:00Z" } }));
  await page.route("**/api/v1/opportunities/*", (route) => route.fulfill({ json: { summary: item, body_text: "<script>inert</script>", labels: [], assignees: [], comments: [], linked_pull_requests: [{ number: 9, title: "Existing work", url: "https://github.com/owner/repo/pull/9", state: "open" }], repository_health: null, analysis: null, explanation: {}, feedback: [] } }));
  await page.goto("/opportunities");
  await page.getByRole("textbox", { name: "Search issues" }).fill("safe");
  await page.getByRole("button", { name: /Open owner\/repo issue 42/ }).click();
  await expect(page.getByText("Check ownership before starting")).toBeVisible();
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Feedback appended.")).toBeVisible();
  await page.getByRole("button", { name: "Close inspector" }).click();
  await expect(page).toHaveURL(/query=safe/);
  await expect(page.getByRole("textbox", { name: "Search issues" })).toHaveValue("safe");
});

test("preference conflict is explicit and recoverable", async ({ page }) => {
  const revision = { revision_id: "00000000-0000-0000-0000-000000000010", valid: true, config_hash: "abcdef123456", profile_hash: "123456abcdef", source: "manual", summary: "Active", created_at: "2026-08-08T12:00:00Z", activated_at: "2026-08-08T12:00:00Z", supersedes_id: null, validation_errors: [] };
  const config = { version: 1, user: { timezone: "UTC", max_estimated_hours: 8, interests: [], career_targets: [] }, scoring: { payoff_weights: { career_relevance: .22, technical_depth: .18, project_impact: .17, portfolio_explainability: .15, learning_value: .12, visibility: .08, timeliness: .08 } }, repositories: [] };
  await page.route("**/api/v1/preferences", (route) => route.fulfill({ json: { revision, config } }));
  await page.route("**/api/v1/preferences/revisions", (route) => route.fulfill({ json: [revision] }));
  await page.route("**/api/v1/preferences/proposals", (route) => route.fulfill({ status: 201, json: { ...revision, revision_id: "00000000-0000-0000-0000-000000000011", activated_at: null } }));
  await page.route("**/api/v1/preferences/revisions/*/activate", (route) => route.fulfill({ status: 409, json: { error: { code: "config_conflict", message: "The active configuration changed.", request_id: "test" } } }));
  await page.goto("/preferences");
  await page.getByRole("button", { name: "Validate & preview" }).click();
  await page.getByRole("button", { name: /Activate revision/ }).click();
  await expect(page.getByText(/preferences changed elsewhere/)).toBeVisible();
  await page.getByRole("button", { name: "Reload active revision" }).click();
  await expect(page.getByText("Contribution fit")).toBeVisible();
});
