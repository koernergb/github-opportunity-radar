import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { opportunityFixture } from "./fixtures";

const revision = { revision_id: "00000000-0000-0000-0000-000000000010", valid: true, config_hash: "abcdef123456", profile_hash: "123456abcdef", source: "manual", summary: "Active profile", created_at: "2026-08-08T12:00:00Z", activated_at: "2026-08-08T12:00:00Z", supersedes_id: null, validation_errors: [] };
const config = { version: 1, user: { timezone: "America/Detroit", max_estimated_hours: 12, interests: ["performance"], career_targets: ["ML systems"] }, scoring: { payoff_weights: { career_relevance: .22, technical_depth: .18, project_impact: .17, portfolio_explainability: .15, learning_value: .12, visibility: .08, timeliness: .08 } }, repositories: [{ full_name: "ml-explore/mlx", enabled: true }] };

export const handlers = [
  http.get("/api/v1/opportunities", () => HttpResponse.json(opportunityFixture)),
  http.get("/api/v1/opportunities/:issueId", () => HttpResponse.json({
    summary: opportunityFixture.items[0],
    body_text: "Treat <script>alert('x')</script> as plain issue text.",
    labels: ["performance"], assignees: [], comments: [], linked_pull_requests: [],
    repository_health: null, analysis: { suggested_first_move: "Reproduce the benchmark." },
    explanation: { ranking_eligible: true, missing_data: [] }, feedback: [],
  })),
  http.post("/api/v1/opportunities/:issueId/feedback", ({ params }) => HttpResponse.json({
    feedback_id: "00000000-0000-0000-0000-000000000099", issue_id: params.issueId,
    status: "interested", note: null, pr_url: null, created_at: "2026-08-08T12:00:00Z",
  }, { status: 201 })),
  http.get("/api/v1/preferences", () => HttpResponse.json({ revision, config })),
  http.get("/api/v1/preferences/revisions", () => HttpResponse.json([revision])),
  http.post("/api/v1/preferences/proposals", () => HttpResponse.json({ ...revision, revision_id: "00000000-0000-0000-0000-000000000011", activated_at: null }, { status: 201 })),
  http.post("/api/v1/preferences/import", () => HttpResponse.json({ ...revision, source: "imported", revision_id: "00000000-0000-0000-0000-000000000012", activated_at: null }, { status: 201 })),
  http.post("/api/v1/preferences/revisions/:revisionId/activate", () => HttpResponse.json({ revision, config })),
  http.get("/api/v1/preferences/export", () => new HttpResponse("version: 1\n", { headers: { "Content-Type": "application/yaml" } })),
  http.get("/api/v1/repositories", () => HttpResponse.json([{ repository_id: "00000000-0000-0000-0000-000000000020", full_name: "ml-explore/mlx", enabled: true, primary_language: "C++", candidate_count: 4, last_synced_at: "2026-08-08T12:00:00Z", health: null, sync_status: "current" }])),
  http.get("/api/v1/runs", () => HttpResponse.json([{ run_id: "00000000-0000-0000-0000-000000000030", status: "success", current_stage: null, started_at: "2026-08-08T12:00:00Z", finished_at: "2026-08-08T12:01:00Z", summary: { scored: 4 }, event_cursor: "2026-08-08T12:01:00Z" }])),
  http.get("/api/v1/runs/:runId/events", () => HttpResponse.json([{ event_id: "00000000-0000-0000-0000-000000000031", stage: "digest", event_type: "stage_started", level: "info", message: "Started digest", error_type: null, details: {}, created_at: "2026-08-08T12:00:30Z" }])),
  http.post("/api/v1/runs", () => HttpResponse.json({ run_id: "00000000-0000-0000-0000-000000000032", status: "queued" }, { status: 202 })),
  http.get("/api/v1/health", () => HttpResponse.json({ status: "ok", version: "0.1.0" })),
  http.get("/api/v1/readiness", () =>
    HttpResponse.json({
      status: "ready",
      checks: { config: { status: "ready" }, database: { status: "ready" } },
      secrets: { github_token: { status: "configured" }, openai_api_key: { status: "missing" } },
    }),
  ),
];

export const server = setupServer(...handlers);
