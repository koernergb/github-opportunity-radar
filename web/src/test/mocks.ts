import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { opportunityFixture } from "./fixtures";

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
