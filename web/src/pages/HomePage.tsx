import { useQuery } from "@tanstack/react-query";
import { ArrowRight, CircleAlert, Radar } from "lucide-react";
import { Link } from "react-router-dom";

import { getValidated } from "../api/client";
import { opportunityPageSchema, readinessSchema } from "../api/types";
import { PageHeader } from "../components/AppShell";

export function HomePage() {
  const readiness = useQuery({ queryKey: ["readiness"], queryFn: () => getValidated("/readiness", readinessSchema) });
  const opportunities = useQuery({ queryKey: ["opportunities", "top"], queryFn: () => getValidated("/opportunities?page_size=5", opportunityPageSchema) });
  return <div className="page"><PageHeader eyebrow="Overview" title="Good morning"><button className="primary-button">Run radar</button></PageHeader>
    <section className="status-strip" aria-label="Radar status"><span className="status-dot" />{readiness.isLoading ? "Checking local services…" : readiness.isError ? "Radar is offline" : "Radar is ready"}<span className="muted">GitHub read-only</span></section>
    <div className="dashboard-grid"><section className="panel"><div className="panel-heading"><div><p className="eyebrow">Ranked for you</p><h2>Top opportunities</h2></div><Link to="/opportunities">View all <ArrowRight size={15} /></Link></div>
      {opportunities.isLoading && <div className="skeleton-list" aria-label="Loading opportunities"><i /><i /><i /></div>}
      {opportunities.isError && <div className="inline-state danger"><CircleAlert />Could not reach the local API.</div>}
      {opportunities.data?.items.length === 0 && <div className="inline-state"><Radar />No ranked issues yet. Run the radar to get started.</div>}
      {opportunities.data?.items.map((item, index) => <Link className="opportunity-row" to="/opportunities" key={item.issue_id}><span className="rank">{index + 1}</span><span><strong>{item.title}</strong><small>{item.repository}#{item.number} · {item.effort_low_hours ?? "?"}–{item.effort_high_hours ?? "?"}h</small></span><span className="score">{Math.round(item.score)}</span></Link>)}
    </section><aside className="panel compact-panel"><p className="eyebrow">Since last run</p><h2>Changes</h2><div className="metric"><strong>—</strong><span>Waiting for a completed run</span></div></aside></div>
  </div>;
}
