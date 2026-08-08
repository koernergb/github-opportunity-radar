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

export const revisionSchema = z.object({
  revision_id: z.string(), valid: z.boolean(), config_hash: z.string().nullable(), profile_hash: z.string().nullable(),
  source: z.string(), summary: z.string(), created_at: z.string(), activated_at: z.string().nullable(), supersedes_id: z.string().nullable(),
  validation_errors: z.array(z.object({ path: z.string(), message: z.string() })),
});
export const preferencesSchema = z.object({ revision: revisionSchema, config: z.record(z.string(), z.unknown()) });
export const repositorySchema = z.object({ repository_id: z.string(), full_name: z.string(), enabled: z.boolean(), primary_language: z.string().nullable(), candidate_count: z.number(), last_synced_at: z.string(), health: z.record(z.string(), z.unknown()).nullable(), sync_status: z.enum(["current", "stale"]) });
export const repositoriesSchema = z.array(repositorySchema);
export type Revision = z.infer<typeof revisionSchema>;
export const runSchema = z.object({ run_id: z.string(), status: z.string(), current_stage: z.string().nullable(), started_at: z.string(), finished_at: z.string().nullable(), summary: z.record(z.string(), z.unknown()), event_cursor: z.string().nullable() });
export const runsSchema = z.array(runSchema);
export const runEventSchema = z.object({ event_id: z.string(), stage: z.string(), event_type: z.string(), level: z.string(), message: z.string(), error_type: z.string().nullable(), details: z.record(z.string(), z.unknown()), created_at: z.string() });
export type Run = z.infer<typeof runSchema>;
export const conversationSummarySchema = z.object({ conversation_id: z.string(), title: z.string(), created_at: z.string(), updated_at: z.string(), message_count: z.number() });
export const conversationMessageSchema = z.object({ message_id: z.string(), role: z.string(), content: z.string(), status: z.string(), error_code: z.string().nullable(), created_at: z.string() });
export const conversationDetailSchema = z.object({ conversation: conversationSummarySchema, messages: z.array(conversationMessageSchema) });
export type ConversationMessage = z.infer<typeof conversationMessageSchema>;
export const assistantProposalSchema = z.object({ proposal_id: z.string(), conversation_id: z.string(), base_revision_id: z.string(), resulting_revision_id: z.string().nullable(), kind: z.string(), arguments: z.record(z.string(), z.unknown()), argument_hash: z.string(), summary: z.string(), status: z.string(), created_at: z.string(), expires_at: z.string(), resolved_at: z.string().nullable() });
export type AssistantProposal = z.infer<typeof assistantProposalSchema>;
export const scheduleSchema = z.object({ schedule_id: z.string(), enabled: z.boolean(), interval_minutes: z.number(), timezone: z.string(), next_run_at: z.string().nullable(), last_attempt_at: z.string().nullable(), last_status: z.string().nullable(), updated_at: z.string() });
