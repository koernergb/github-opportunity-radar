import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock, KeyRound, ShieldCheck } from "lucide-react";
import { type FormEvent, useState } from "react";

import { deleteSecret, getValidated, postJson, putJson, putSecret } from "../api/client";
import {
  credentialMutationSchema,
  llmProvidersSchema,
  preferencesSchema,
  revisionSchema,
  scheduleSchema,
  type LlmProvider,
} from "../api/types";
import { PageHeader } from "../components/AppShell";

type ProviderName = LlmProvider["provider"];

export function SettingsPage() {
  const queryClient = useQueryClient();
  const schedule = useQuery({ queryKey: ["schedule"], queryFn: () => getValidated("/schedule", scheduleSchema) });
  const providers = useQuery({ queryKey: ["llm-providers"], queryFn: () => getValidated("/llm/providers", llmProvidersSchema) });
  const preferences = useQuery({ queryKey: ["preferences"], queryFn: () => getValidated("/preferences", preferencesSchema) });
  const [interval, setInterval] = useState(60);
  const [timezone, setTimezone] = useState(Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC");
  const [analysisProviderEdit, setAnalysisProvider] = useState<ProviderName | null>(null);
  const [assistantProviderEdit, setAssistantProvider] = useState<ProviderName | null>(null);
  const [analysisModelEdit, setAnalysisModel] = useState<string | null>(null);
  const [assistantModelEdit, setAssistantModel] = useState<string | null>(null);
  const selectedAnalysis = providers.data?.find((provider) => provider.selected_for_analysis);
  const selectedAssistant = providers.data?.find((provider) => provider.selected_for_assistant);
  const analysisProvider = analysisProviderEdit ?? selectedAnalysis?.provider ?? "openai";
  const assistantProvider = assistantProviderEdit ?? selectedAssistant?.provider ?? "openai";
  const analysisModel = analysisModelEdit ?? selectedAnalysis?.analysis_model ?? selectedAnalysis?.model_suggestions[0] ?? "gpt-5-mini";
  const assistantModel = assistantModelEdit ?? selectedAssistant?.assistant_model ?? selectedAssistant?.model_suggestions[0] ?? "gpt-5-mini";

  const refreshProviders = async () => queryClient.invalidateQueries({ queryKey: ["llm-providers"] });
  const saveSchedule = useMutation({
    mutationFn: (enabled: boolean) => putJson("/schedule", { enabled, interval_minutes: schedule.data?.interval_minutes ?? interval, timezone: schedule.data?.timezone ?? timezone }, scheduleSchema),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ["schedule"] }),
  });
  const saveSelection = useMutation({
    mutationFn: () => {
      const config = structuredClone(preferences.data?.config ?? {}) as Record<string, unknown>;
      const oldLlm = (config.llm ?? {}) as Record<string, unknown>;
      config.llm = { ...oldLlm, provider: analysisProvider, model: analysisModel, assistant_provider: assistantProvider, assistant_model: assistantModel };
      return postJson("/preferences/proposals", { config, summary: "Update LLM providers", expected_active_id: preferences.data?.revision.revision_id ?? null, activate: true, source: "manual" }, revisionSchema);
    },
    onSuccess: async () => {
      await Promise.all([queryClient.invalidateQueries({ queryKey: ["preferences"] }), refreshProviders()]);
    },
  });

  function updateSchedule(event: FormEvent) {
    event.preventDefault();
    void putJson("/schedule", { enabled: schedule.data?.enabled ?? false, interval_minutes: interval, timezone }, scheduleSchema)
      .then(() => queryClient.invalidateQueries({ queryKey: ["schedule"] }));
  }

  return <div className="page">
    <PageHeader eyebrow="Local application" title="Settings" />
    <section className="panel llm-settings">
      <div className="panel-heading"><h2><KeyRound size={15} /> AI providers</h2></div>
      <div className="provider-selection">
        <label>Issue analysis provider<select value={analysisProvider} onChange={(event) => setAnalysisProvider(event.target.value as ProviderName)}>{providers.data?.map((provider) => <option key={provider.provider} value={provider.provider}>{provider.display_name}</option>)}</select></label>
        <label>Analysis model<input list={`${analysisProvider}-models`} value={analysisModel} onChange={(event) => setAnalysisModel(event.target.value)} /></label>
        <label>Assistant provider<select value={assistantProvider} onChange={(event) => setAssistantProvider(event.target.value as ProviderName)}>{providers.data?.map((provider) => <option key={provider.provider} value={provider.provider}>{provider.display_name}</option>)}</select></label>
        <label>Assistant model<input list={`${assistantProvider}-models`} value={assistantModel} onChange={(event) => setAssistantModel(event.target.value)} /></label>
        {providers.data?.map((provider) => <datalist id={`${provider.provider}-models`} key={provider.provider}>{provider.model_suggestions.map((model) => <option value={model} key={model} />)}</datalist>)}
        <button className="primary-button" onClick={() => saveSelection.mutate()} disabled={!analysisModel || !assistantModel || saveSelection.isPending}>Save provider selection</button>
      </div>
      {saveSelection.isSuccess && <p className="validation-success" role="status">Provider configuration revision activated.</p>}
      <div className="provider-grid">
        {providers.data?.map((provider) => <ProviderCard key={provider.provider} provider={provider} refresh={refreshProviders} />)}
      </div>
    </section>
    <div className="settings-grid">
      <section className="panel form-panel"><div className="panel-heading"><h2><Clock size={15} />Local schedule</h2></div><form className="form-body" onSubmit={updateSchedule}><p>Schedule state is stored locally, uses this IANA timezone, and shares the manual/CLI run lock.</p><label>Interval in minutes<input type="number" min="15" max="10080" value={interval} onChange={(event) => setInterval(Number(event.target.value))} /></label><label>Timezone<input value={timezone} onChange={(event) => setTimezone(event.target.value)} /></label><div className="form-actions"><button type="submit" className="secondary-button">Save timing</button><button type="button" className="primary-button" onClick={() => saveSchedule.mutate(!(schedule.data?.enabled ?? false))}>{schedule.data?.enabled ? "Disable schedule" : "Enable schedule"}</button></div>{schedule.data && <div className="schedule-state"><strong>{schedule.data.enabled ? "Enabled" : "Disabled"}</strong><span>Next: {schedule.data.next_run_at ? new Date(schedule.data.next_run_at).toLocaleString() : "not scheduled"}</span><span>Last scheduler state: {schedule.data.last_status ?? "none"}</span></div>}</form></section>
      <aside className="panel compact-panel"><p className="eyebrow">Security boundary</p><h2><ShieldCheck size={15} /> Local credentials</h2><p>Keys saved here go to your operating-system credential vault. Environment keys remain read-only.</p><small>Keys are never returned to this page, browser storage, configuration revisions, or YAML exports.</small></aside>
    </div>
  </div>;
}

function ProviderCard({ provider, refresh }: { provider: LlmProvider; refresh: () => Promise<unknown> }) {
  const [key, setKey] = useState("");
  const [testModel, setTestModel] = useState(provider.analysis_model ?? provider.assistant_model ?? provider.model_suggestions[0] ?? "");
  const save = useMutation({ mutationFn: () => putSecret(`/llm/providers/${provider.provider}/credential`, { api_key: key }, credentialMutationSchema), onSuccess: async () => { setKey(""); await refresh(); } });
  const remove = useMutation({ mutationFn: () => deleteSecret(`/llm/providers/${provider.provider}/credential`, credentialMutationSchema), onSuccess: refresh });
  const test = useMutation({ mutationFn: () => postJson(`/llm/providers/${provider.provider}/test`, { model: testModel }, credentialMutationSchema) });
  return <article className="provider-card">
    <div><strong>{provider.display_name}</strong><span className={`credential-status ${provider.credential_status}`}>{provider.credential_status}{provider.credential_source ? ` · ${provider.credential_source}` : ""}</span></div>
    <small>Structured analysis · {provider.assistant_tools ? "assistant tools" : "analysis only"}</small>
    {provider.notes && <p>{provider.notes}</p>}
    <label>{provider.display_name} API key<input type="password" autoComplete="off" value={key} placeholder="Paste a new key" onChange={(event) => setKey(event.target.value)} /></label>
    <div className="provider-actions"><button className="secondary-button" disabled={key.length < 8 || save.isPending} onClick={() => save.mutate()}>Save key</button><button className="secondary-button" disabled={provider.credential_status !== "configured" || provider.credential_source === "environment" || remove.isPending} onClick={() => remove.mutate()}>Remove</button></div>
    <label>Connection-test model<input list={`${provider.provider}-models`} value={testModel} onChange={(event) => setTestModel(event.target.value)} /></label>
    <button className="secondary-button" disabled={!testModel || provider.credential_status !== "configured" || test.isPending} onClick={() => test.mutate()}>Test connection</button>
    {(save.isError || remove.isError || test.isError) && <p className="danger" role="alert">The provider operation failed without exposing credential details.</p>}
    {test.isSuccess && <p className="positive" role="status">Connection succeeded.</p>}
  </article>;
}
