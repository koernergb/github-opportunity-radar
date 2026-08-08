import type { OpportunityPage } from "../api/types";

export const opportunityFixture: OpportunityPage = {
  items: [
    {
      issue_id: "00000000-0000-0000-0000-000000000042",
      repository: "ml-explore/mlx",
      number: 42,
      title: "Improve batched attention performance",
      url: "https://github.com/ml-explore/mlx/issues/42",
      score: 82,
      confidence: 0.78,
      effort_low_hours: 4,
      effort_high_hours: 8,
      fit: 0.91,
      merge_estimate: 0.64,
      merge_band: "high",
      merge_is_heuristic: true,
      warnings: [],
      missing_evidence: [],
      updated_at: "2026-08-08T12:00:00Z",
      scored_at: "2026-08-08T12:10:00Z",
    },
  ],
  meta: { page: 1, page_size: 25, total: 1 },
};
