import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, CircleAlert, Play, Radar } from "lucide-react";
import { Link } from "react-router-dom";
import { z } from "zod";

import { getValidated, postJson } from "../api/client";
import { opportunityPageSchema, readinessSchema, repositoriesSchema, runsSchema } from "../api/types";
import { PageHeader } from "../components/AppShell";

export function HomePage() {
  const queryClient = useQueryClient();
  const readiness = useQuery({ queryKey: ["readiness"], queryFn: () => getValidated("/readiness", readinessSchema) });
  const opportunities = useQuery({ queryKey: ["opportunities", "top"], queryFn: () => getValidated("/opportunities?page_size=5", opportunityPageSchema) });
  const repositories = useQuery({ queryKey: ["repositories"], queryFn: () => getValidated("/repositories", repositoriesSchema) });
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => getValidated("/runs", runsSchema) });
  const start = useMutation({ mutationFn: () => postJson("/runs", { scope: "all", deadline_seconds: 600, fallback_only: false }, z.object({ run_id: z.string(), status: z.string() })), onSuccess: async () => queryClient.invalidateQueries({ queryKey: ["runs"] }) });
  const latest = runs.data?.[0]; const changed = Number(latest?.summary.materially_changed ?? latest?.summary.scored ?? 0); const healthy = repositories.data?.filter((item) => item.sync_status === "current").length ?? 0;
  return <div className="page"><PageHeader eyebrow="Overview" title="Good morning"><button className="primary-button" onClick={() => start.mutate()} disabled={start.isPending}><Play size={14} />{start.isPending ? "Starting…" : "Run radar"}</button></PageHeader>
    <section className="status-strip" aria-label="Radar status"><span className="status-dot" />{readiness.isLoading ? "Checking local services…" : readiness.isError ? "Radar is offline" : "Radar is ready"}<span className="muted">GitHub read-only</span></section>
    <div className="dashboard-grid"><section className="panel"><div className="panel-heading"><div><p className="eyebrow">Ranked for you</p><h2>Top opportunities</h2></div><Link to="/opportunities">View all <ArrowRight size={15} /></Link></div>
      {opportunities.isLoading && <div className="skeleton-list" aria-label="Loading opportunities"><i /><i /><i /></div>}
      {opportunities.isError && <div className="inline-state danger"><CircleAlert />Could not reach the local API.</div>}
      {opportunities.data?.items.length === 0 && <div className="inline-state"><Radar />No ranked issues yet. Run the radar to get started.</div>}
      {opportunities.data?.items.map((item, index) => <Link className="opportunity-row" to="/opportunities" key={item.issue_id}><span className="rank">{index + 1}</span><span><strong>{item.title}</strong><small>{item.repository}#{item.number} · {item.effort_low_hours ?? "?"}–{item.effort_high_hours ?? "?"}h</small></span><span className="score">{Math.round(item.score)}</span></Link>)}
    </section><aside className="home-stack"><section className="panel compact-panel"><p className="eyebrow">Since last run</p><h2>Material changes</h2><div className="metric"><strong>{latest ? changed : "—"}</strong><span>{latest ? `Last run ${latest.status}` : "Waiting for a completed run"}</span></div></section><section className="panel compact-panel"><p className="eyebrow">Tracked repositories</p><h2>Repository health</h2><div className="metric"><strong>{healthy}/{repositories.data?.length ?? 0}</strong><span>currently synchronized</span></div></section><section className="panel compact-panel"><p className="eyebrow">Next / last</p><h2>Run status</h2><p className="home-run-state">{latest ? `${new Date(latest.started_at).toLocaleString()} · ${latest.status}` : "No runs recorded"}</p><Link to="/settings">Manage local schedule <ArrowRight size={13} /></Link></section></aside></div>
  </div>;
}
