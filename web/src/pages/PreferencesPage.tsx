import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Download, History, RotateCcw, Upload } from "lucide-react";
import { useEffect, useState } from "react";

import { ApiClientError, getText, getValidated, postJson } from "../api/client";
import { preferencesSchema, revisionSchema } from "../api/types";
import { PageHeader } from "../components/AppShell";

type Config = Record<string, unknown> & {
  user: Record<string, unknown> & { timezone?: string; max_estimated_hours?: number; interests?: string[]; career_targets?: string[] };
  scoring: Record<string, unknown> & { payoff_weights: Record<string, number> };
};

export function PreferencesPage() {
  const queryClient = useQueryClient();
  const preferences = useQuery({ queryKey: ["preferences"], queryFn: () => getValidated("/preferences", preferencesSchema) });
  const revisions = useQuery({ queryKey: ["preference-revisions"], queryFn: () => getValidated("/preferences/revisions", revisionSchema.array()) });
  const [draft, setDraft] = useState<Config | null>(null);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [yamlText, setYamlText] = useState("");
  useEffect(() => {
    // Query data initializes an editable copy; later edits never mutate the cache object.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (preferences.data && draft === null) setDraft(structuredClone(preferences.data.config) as Config);
  }, [draft, preferences.data]);
  const refresh = async () => { await Promise.all([queryClient.invalidateQueries({ queryKey: ["preferences"] }), queryClient.invalidateQueries({ queryKey: ["preference-revisions"] })]); };
  const preview = useMutation({ mutationFn: () => postJson("/preferences/proposals", { config: draft, summary: "Manual preference edit", expected_active_id: preferences.data?.revision.revision_id ?? null, activate: false, source: "manual" }, revisionSchema), onSuccess: (revision) => { setPreviewId(revision.revision_id); void refresh(); } });
  const activate = useMutation({ mutationFn: (revisionId: string) => postJson(`/preferences/revisions/${revisionId}/activate`, { expected_active_id: preferences.data?.revision.revision_id ?? null }, preferencesSchema), onSuccess: async () => { setPreviewId(null); setDraft(null); await refresh(); } });
  const importYaml = useMutation({ mutationFn: () => postJson("/preferences/import", { yaml_text: yamlText, summary: "Imported in web UI", expected_active_id: preferences.data?.revision.revision_id ?? null, activate: false }, revisionSchema), onSuccess: (revision) => { setPreviewId(revision.revision_id); void refresh(); } });
  const exportYaml = async () => { const value = await getText("/preferences/export"); const blob = new Blob([value], { type: "application/yaml" }); const link = document.createElement("a"); link.href = URL.createObjectURL(blob); link.download = "radar-profile.yaml"; link.click(); URL.revokeObjectURL(link.href); };
  const user = draft?.user;
  const scoring = draft?.scoring;
  const setUser = (key: string, value: unknown) => setDraft((current) => current ? { ...current, user: { ...current.user, [key]: value } } : current);
  return <div className="page"><PageHeader eyebrow="Your profile" title="Preferences"><button className="secondary-button" onClick={() => void exportYaml()}><Download size={15} />Export YAML</button></PageHeader>
    {preferences.isLoading && <div className="inline-state">Loading active preferences…</div>}{preferences.isError && <div className="inline-state danger">No active configuration. Start Radar once to bootstrap your profile.</div>}
    {draft && user && scoring && <div className="preferences-grid"><section className="panel form-panel"><div className="panel-heading"><div><p className="eyebrow">Structured profile</p><h2>Contribution fit</h2></div><span className="hash">{preferences.data?.revision.config_hash?.slice(0, 8)}</span></div><div className="form-body">
      <label>Timezone<input value={String(user.timezone ?? "")} onChange={(event) => setUser("timezone", event.target.value)} /></label>
      <label>Maximum estimated hours<input type="number" min="0.5" step="0.5" value={Number(user.max_estimated_hours ?? 0)} onChange={(event) => setUser("max_estimated_hours", Number(event.target.value))} /></label>
      <label>Interests, comma separated<input value={(user.interests ?? []).join(", ")} onChange={(event) => setUser("interests", event.target.value.split(",").map((value) => value.trim()).filter(Boolean))} /></label>
      <label>Career targets, comma separated<input value={(user.career_targets ?? []).join(", ")} onChange={(event) => setUser("career_targets", event.target.value.split(",").map((value) => value.trim()).filter(Boolean))} /></label>
      <fieldset><legend>Scoring weights</legend>{Object.entries(scoring.payoff_weights as Record<string, number>).map(([key, value]) => <label key={key}>{key.replaceAll("_", " ")}<input type="number" min="0" max="1" step="0.01" value={value} onChange={(event) => setDraft((current) => current ? { ...current, scoring: { ...current.scoring, payoff_weights: { ...current.scoring.payoff_weights, [key]: Number(event.target.value) } } } : current)} /></label>)}</fieldset>
      <div className="form-actions"><button className="secondary-button" onClick={() => preview.mutate()} disabled={preview.isPending}>Validate & preview</button>{previewId && <button className="primary-button" onClick={() => activate.mutate(previewId)} disabled={activate.isPending}><Check size={15} />Activate revision</button>}</div>
      {preview.data && <div className={preview.data.valid ? "validation-success" : "validation-errors"}>{preview.data.valid ? "Valid configuration. Review and activate it." : preview.data.validation_errors.map((error) => <p key={error.path}><strong>{error.path}</strong> {error.message}</p>)}</div>}
      {activate.error instanceof ApiClientError && activate.error.status === 409 && <div className="validation-errors"><p><strong>Conflict:</strong> preferences changed elsewhere. Reload before applying.</p><button onClick={() => void refresh()}>Reload active revision</button></div>}
    </div></section><aside className="panel revisions-panel"><div className="panel-heading"><div><p className="eyebrow">Append-only</p><h2><History size={15} /> Revision history</h2></div></div>{revisions.data?.map((revision) => <article key={revision.revision_id} className={revision.revision_id === preferences.data?.revision.revision_id ? "active-revision" : ""}><strong>{revision.summary}</strong><small>{revision.source} · {revision.config_hash?.slice(0, 8) ?? "invalid"}</small><time>{new Date(revision.created_at).toLocaleString()}</time>{revision.revision_id !== preferences.data?.revision.revision_id && revision.valid && <button onClick={() => activate.mutate(revision.revision_id)}><RotateCcw size={13} />Activate / undo</button>}</article>)}</aside></div>}
    <section className="panel yaml-panel"><div className="panel-heading"><div><p className="eyebrow">Portable configuration</p><h2>YAML import</h2></div></div><div className="form-body"><label>Paste profile YAML<textarea value={yamlText} onChange={(event) => setYamlText(event.target.value)} placeholder="version: 1" /></label><button className="secondary-button" onClick={() => importYaml.mutate()} disabled={!yamlText || importYaml.isPending}><Upload size={15} />Validate import</button>{importYaml.data && <p role="status">Import revision created with {importYaml.data.valid ? "valid" : "invalid"} status.</p>}</div></section>
  </div>;
}
