import { z } from "zod";

export const healthSchema = z.object({ status: z.literal("ok"), version: z.string() });
export const readinessSchema = z.object({
  status: z.enum(["ready", "not_ready"]),
  checks: z.record(z.string(), z.object({ status: z.string() })),
  secrets: z.record(z.string(), z.object({ status: z.enum(["configured", "missing", "invalid"]) })),
});
export const opportunitySchema = z.object({
  issue_id: z.string(),
  repository: z.string(),
  number: z.number(),
  title: z.string(),
  url: z.string().url(),
  score: z.number(),
  confidence: z.number(),
  effort_low_hours: z.number().nullable(),
  effort_high_hours: z.number().nullable(),
  fit: z.number(),
  merge_estimate: z.number(),
  merge_band: z.string(),
  merge_is_heuristic: z.literal(true),
  warnings: z.array(z.string()),
  missing_evidence: z.array(z.string()),
  updated_at: z.string(),
  scored_at: z.string(),
});
export const opportunityPageSchema = z.object({
  items: z.array(opportunitySchema),
  meta: z.object({ page: z.number(), page_size: z.number(), total: z.number() }),
});
export const opportunityDetailSchema = z.object({
  summary: opportunitySchema,
  body_text: z.string().nullable(),
  labels: z.array(z.string()),
  assignees: z.array(z.string()),
  comments: z.array(z.object({ author_login: z.string().nullable(), body_text: z.string(), created_at: z.string() })),
  linked_pull_requests: z.array(z.object({ number: z.number(), title: z.string(), url: z.string(), state: z.string() })),
  repository_health: z.record(z.string(), z.unknown()).nullable(),
  analysis: z.record(z.string(), z.unknown()).nullable(),
  explanation: z.record(z.string(), z.unknown()),
  feedback: z.array(z.object({ feedback_id: z.string(), issue_id: z.string(), status: z.string(), note: z.string().nullable(), pr_url: z.string().nullable(), created_at: z.string() })),
});

export type Opportunity = z.infer<typeof opportunitySchema>;
export type OpportunityPage = z.infer<typeof opportunityPageSchema>;
export type OpportunityDetail = z.infer<typeof opportunityDetailSchema>;
