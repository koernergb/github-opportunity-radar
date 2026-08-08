import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ChevronRight, CircleHelp, ExternalLink, Search, ShieldAlert, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { z } from "zod";

import { getValidated, postJson } from "../api/client";
import { opportunityDetailSchema, opportunityPageSchema, type Opportunity } from "../api/types";
import { PageHeader } from "../components/AppShell";

const feedbackSchema = z.object({ feedback_id: z.string(), issue_id: z.string(), status: z.string(), note: z.string().nullable(), pr_url: z.string().nullable(), created_at: z.string() });

export function OpportunitiesPage() {
  const [params, setParams] = useSearchParams();
  const searchRef = useRef<HTMLInputElement>(null);
  const selected = params.get("issue");
  const search = params.get("query") ?? "";
  const repository = params.get("repository") ?? "";
  const confidence = params.get("confidence") ?? "";
  const diagnostic = params.get("diagnostic") ?? "eligible";
  const queryString = useMemo(() => {
    const query = new URLSearchParams({ page_size: "100", diagnostic });
    if (search) query.set("query", search);
    if (repository) query.set("repository", repository);
    if (confidence) query.set("min_confidence", confidence);
    return query.toString();
  }, [confidence, diagnostic, repository, search]);
  const opportunities = useQuery({ queryKey: ["opportunities", queryString], queryFn: () => getValidated(`/opportunities?${queryString}`, opportunityPageSchema) });
  const update = useCallback((key: string, value: string) => setParams((current) => {
    const next = new URLSearchParams(current);
    if (value) next.set(key, value); else next.delete(key);
    return next;
  }, { replace: true }), [setParams]);

  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      if (event.key === "/" && document.activeElement?.tagName !== "INPUT") { event.preventDefault(); searchRef.current?.focus(); }
      if (event.key === "Escape" && selected) update("issue", "");
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, [selected, update]);
  const repositories = [...new Set(opportunities.data?.items.map((item) => item.repository) ?? [])];
  return <div className="page opportunities-page"><PageHeader eyebrow="Issue intelligence" title="Opportunities"><span className="result-count">{opportunities.data?.meta.total ?? "—"} ranked issues</span></PageHeader>
    <section className="filter-bar" aria-label="Opportunity filters">
      <label className="search-field"><Search size={15} aria-hidden="true" /><span className="sr-only">Search issues</span><input ref={searchRef} value={search} onChange={(event) => update("query", event.target.value)} placeholder="Search issues  /" /></label>
      <label><span>Repository</span><select value={repository} onChange={(event) => update("repository", event.target.value)}><option value="">All repositories</option>{repositories.map((name) => <option key={name}>{name}</option>)}</select></label>
      <label><span>Confidence</span><select value={confidence} onChange={(event) => update("confidence", event.target.value)}><option value="">Any confidence</option><option value="0.7">High (70%+)</option><option value="0.4">Moderate (40%+)</option></select></label>
      <label><span>Visibility</span><select value={diagnostic} onChange={(event) => update("diagnostic", event.target.value)}><option value="eligible">Ranked only</option><option value="all">Include excluded</option></select></label>
    </section>
    <div className={`opportunity-workspace ${selected ? "has-inspector" : ""}`}>
      <section className="opportunity-table" aria-label="Ranked opportunities">
        <div className="table-head"><span>Score</span><span>Issue</span><span>Effort</span><span>Confidence</span><span>Fit</span><span>Merge estimate</span><span /></div>
        {opportunities.isLoading && <div className="inline-state">Loading ranked issues…</div>}
        {opportunities.isError && <div className="inline-state danger">Could not load ranked issues.</div>}
        {opportunities.data?.items.length === 0 && <div className="inline-state">No issues match these filters.</div>}
        {opportunities.data?.items.map((item) => <OpportunityRow key={item.issue_id} item={item} selected={selected === item.issue_id} onSelect={() => update("issue", item.issue_id)} />)}
      </section>
      {selected && <Inspector issueId={selected} onClose={() => update("issue", "")} />}
    </div>
  </div>;
}

function OpportunityRow({ item, selected, onSelect }: { item: Opportunity; selected: boolean; onSelect: () => void }) {
  const low = item.confidence < 0.4;
  const claimed = item.warnings.some((warning) => warning.includes("claim") || warning.includes("linked_pr"));
  return <button className={`table-row ${selected ? "selected" : ""}`} onClick={onSelect} aria-label={`Open ${item.repository} issue ${item.number}`}>
    <strong className="table-score">{Math.round(item.score)}</strong><span className="issue-cell"><strong>{item.title}</strong><small>{item.repository}#{item.number}</small>{claimed && <em className="warning-chip"><ShieldAlert size={12} />Claim or active PR</em>}{item.missing_evidence.length > 0 && <em className="missing-chip"><CircleHelp size={12} />Missing evidence</em>}</span>
    <span>{formatEffort(item)}</span><span className={low ? "low-confidence" : ""}>{low && <AlertTriangle size={13} />} {Math.round(item.confidence * 100)}%{low && <small> LOW</small>}</span><span>{Math.round(item.fit * 100)}%</span><span>{item.merge_band}<small>heuristic</small></span><ChevronRight size={15} />
  </button>;
}

function Inspector({ issueId, onClose }: { issueId: string; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState("interested");
  const detail = useQuery({ queryKey: ["opportunity", issueId], queryFn: () => getValidated(`/opportunities/${issueId}`, opportunityDetailSchema) });
  const feedback = useMutation({ mutationFn: () => postJson(`/opportunities/${issueId}/feedback`, { status }, feedbackSchema), onSuccess: () => queryClient.invalidateQueries({ queryKey: ["opportunity", issueId] }) });
  return <aside className="inspector" aria-label="Opportunity inspector"><div className="inspector-top"><p className="eyebrow">Issue inspector</p><button className="icon-button inspector-close" onClick={onClose} aria-label="Close inspector"><X size={17} /></button></div>
    {detail.isLoading && <div className="inline-state">Loading evidence…</div>}{detail.isError && <div className="inline-state danger">Could not load issue evidence.</div>}
    {detail.data && <><h2>{detail.data.summary.title}</h2><a className="issue-link" href={detail.data.summary.url} target="_blank" rel="noreferrer">{detail.data.summary.repository}#{detail.data.summary.number}<ExternalLink size={13} /></a>
      <div className="inspector-badges"><span>{formatEffort(detail.data.summary)}</span><span>{Math.round(detail.data.summary.confidence * 100)}% confidence</span><span>{detail.data.summary.merge_band} · heuristic merge</span></div>
      {(detail.data.summary.warnings.length > 0 || detail.data.linked_pull_requests.length > 0) && <section className="evidence-warning"><AlertTriangle /><div><strong>Check ownership before starting</strong><p>{detail.data.summary.warnings.join(", ") || "An active linked pull request exists."}</p></div></section>}
      <InspectorSection title="Issue text"><p className="untrusted-text">{detail.data.body_text ?? "No issue description was observed."}</p></InspectorSection>
      <InspectorSection title="Why it ranks"><KeyValue data={detail.data.explanation} /></InspectorSection>
      <InspectorSection title="Analysis"><KeyValue data={detail.data.analysis ?? { missing: "Semantic analysis unavailable" }} /></InspectorSection>
      <InspectorSection title="Repository evidence"><KeyValue data={detail.data.repository_health ?? { missing: "Repository history unavailable" }} /></InspectorSection>
      <InspectorSection title="Linked pull requests">{detail.data.linked_pull_requests.length ? detail.data.linked_pull_requests.map((pr) => <a key={pr.number} href={pr.url} target="_blank" rel="noreferrer">#{pr.number} {pr.title} · {pr.state}</a>) : <p>None observed.</p>}</InspectorSection>
      <section className="feedback-box"><h3>Track your progress</h3><div><select value={status} onChange={(event) => setStatus(event.target.value)} aria-label="Feedback status"><option value="interested">Interested</option><option value="investigating">Investigating</option><option value="too_hard">Too hard</option><option value="already_claimed">Already claimed</option></select><button className="primary-button" onClick={() => feedback.mutate()} disabled={feedback.isPending}>{feedback.isPending ? "Saving…" : "Save"}</button></div>{feedback.isSuccess && <p role="status">Feedback appended.</p>}</section>
    </>}
  </aside>;
}

function InspectorSection({ title, children }: { title: string; children: React.ReactNode }) { return <section className="inspector-section"><h3>{title}</h3>{children}</section>; }
function KeyValue({ data }: { data: Record<string, unknown> }) { return <dl>{Object.entries(data).slice(0, 8).map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{typeof value === "object" ? JSON.stringify(value) : String(value)}</dd></div>)}</dl>; }
function formatEffort(item: Opportunity) { return item.effort_low_hours == null ? "Unknown" : `${item.effort_low_hours}–${item.effort_high_hours ?? "?"}h`; }
