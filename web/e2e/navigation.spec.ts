import { expect, test } from "@playwright/test";

const pages = ["Assistant", "Opportunities", "Repositories", "Preferences", "Runs", "Settings"];

test("all primary routes load and command palette is keyboard accessible", async ({ page }) => {
  await page.route("**/api/v1/readiness", (route) => route.fulfill({ json: { status: "ready", checks: {}, secrets: {} } }));
  await page.route("**/api/v1/opportunities**", (route) => route.fulfill({ json: { items: [], meta: { page: 1, page_size: 25, total: 0 } } }));
  await page.route("**/api/v1/repositories", (route) => route.fulfill({ json: [{ repository_id: "00000000-0000-0000-0000-000000000020", full_name: "ml-explore/mlx", enabled: true, primary_language: "C++", candidate_count: 4, last_synced_at: "2026-08-08T12:00:00Z", health: null, sync_status: "current" }] }));
  await page.route("**/api/v1/runs", (route) => route.fulfill({ json: [{ run_id: "00000000-0000-0000-0000-000000000030", status: "success", current_stage: null, started_at: "2026-08-08T12:00:00Z", finished_at: "2026-08-08T12:01:00Z", summary: { materially_changed: 3 }, event_cursor: null }] }));
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

test("completed run timeline remains available after refresh", async ({ page }) => {
  const run = { run_id: "00000000-0000-0000-0000-000000000030", status: "partial", current_stage: null, started_at: "2026-08-08T12:00:00Z", finished_at: "2026-08-08T12:01:00Z", summary: { stage_failures: ["deadline"], repositories_failed: 1 }, event_cursor: "2026-08-08T12:01:00Z" };
  await page.route("**/api/v1/runs", (route) => route.fulfill({ json: [run] }));
  await page.route("**/api/v1/runs/*/events", (route) => route.fulfill({ json: [{ event_id: "00000000-0000-0000-0000-000000000031", stage: "analyze_score", event_type: "stage_started", level: "info", message: "Started analyze_score", error_type: null, details: {}, created_at: "2026-08-08T12:00:30Z" }] }));
  await page.goto("/runs");
  await expect(page.getByText("Started analyze_score")).toBeVisible();
  await expect(page.getByText(/deadline/)).toBeVisible();
  await page.reload();
  await expect(page.getByText("Started analyze_score")).toBeVisible();
});

test("assistant proposal requires confirmation and supports undo", async ({ page }) => {
  const conversation = { conversation_id: "00000000-0000-0000-0000-000000000050", title: "Change preferences", created_at: "2026-08-08T12:00:00Z", updated_at: "2026-08-08T12:00:00Z", message_count: 1 };
  const proposal = { proposal_id: "00000000-0000-0000-0000-000000000060", conversation_id: conversation.conversation_id, base_revision_id: "00000000-0000-0000-0000-000000000010", resulting_revision_id: null as string | null, kind: "preferences", arguments: { interests: ["compilers"] }, argument_hash: "a".repeat(64), summary: "Update interests", status: "pending", created_at: "2026-08-08T12:00:00Z", expires_at: "2026-08-08T12:15:00Z", resolved_at: null as string | null };
  await page.route("**/api/v1/conversations", (route) => route.fulfill({ json: [conversation] }));
  await page.route("**/api/v1/conversations/*", (route) => route.fulfill({ json: { conversation, messages: [] } }));
  await page.route("**/api/v1/assistant/proposals/*/confirm", (route) => { proposal.status = "applied"; proposal.resulting_revision_id = "00000000-0000-0000-0000-000000000061"; proposal.resolved_at = "2026-08-08T12:01:00Z"; return route.fulfill({ json: proposal }); });
  await page.route("**/api/v1/assistant/proposals/*/undo", (route) => route.fulfill({ json: { status: "undone", revision_id: proposal.base_revision_id } }));
  await page.route("**/api/v1/assistant/proposals/*", (route) => route.fulfill({ json: [proposal] }));
  await page.goto("/assistant");
  await expect(page.getByText(/"compilers"/)).toBeVisible();
  await page.getByRole("button", { name: "Confirm exact change" }).click();
  await expect(page.getByRole("button", { name: "Undo revision" })).toBeVisible();
  await page.getByRole("button", { name: "Undo revision" }).click();
});
