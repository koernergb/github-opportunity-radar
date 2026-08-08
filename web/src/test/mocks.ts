import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import { opportunityFixture } from "./fixtures";

export const handlers = [
  http.get("/api/v1/opportunities", () => HttpResponse.json(opportunityFixture)),
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
