import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock, ShieldCheck } from "lucide-react";
import { type FormEvent, useState } from "react";

import { getValidated, putJson } from "../api/client";
import { readinessSchema, scheduleSchema } from "../api/types";
import { PageHeader } from "../components/AppShell";

export function SettingsPage() {
  const queryClient = useQueryClient();
  const readiness = useQuery({ queryKey: ["readiness"], queryFn: () => getValidated("/readiness", readinessSchema) });
  const schedule = useQuery({ queryKey: ["schedule"], queryFn: () => getValidated("/schedule", scheduleSchema) });
  const [interval, setInterval] = useState(60);
  const [timezone, setTimezone] = useState(Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC");
  const save = useMutation({ mutationFn: (enabled: boolean) => putJson("/schedule", { enabled, interval_minutes: schedule.data?.interval_minutes ?? interval, timezone: schedule.data?.timezone ?? timezone }, scheduleSchema), onSuccess: async () => queryClient.invalidateQueries({ queryKey: ["schedule"] }) });
  function update(event: FormEvent) { event.preventDefault(); void putJson("/schedule", { enabled: schedule.data?.enabled ?? false, interval_minutes: interval, timezone }, scheduleSchema).then(() => queryClient.invalidateQueries({ queryKey: ["schedule"] })); }
  return <div className="page"><PageHeader eyebrow="Local application" title="Settings" /><div className="settings-grid"><section className="panel form-panel"><div className="panel-heading"><h2><Clock size={15} />Local schedule</h2></div><form className="form-body" onSubmit={update}><p>Schedule state is stored locally, uses this IANA timezone, and shares the manual/CLI run lock.</p><label>Interval in minutes<input type="number" min="15" max="10080" value={interval} onChange={(event) => setInterval(Number(event.target.value))} /></label><label>Timezone<input value={timezone} onChange={(event) => setTimezone(event.target.value)} /></label><div className="form-actions"><button type="submit" className="secondary-button">Save timing</button><button type="button" className="primary-button" onClick={() => save.mutate(!(schedule.data?.enabled ?? false))}>{schedule.data?.enabled ? "Disable schedule" : "Enable schedule"}</button></div>{schedule.data && <div className="schedule-state"><strong>{schedule.data.enabled ? "Enabled" : "Disabled"}</strong><span>Next: {schedule.data.next_run_at ? new Date(schedule.data.next_run_at).toLocaleString() : "not scheduled"}</span><span>Last scheduler state: {schedule.data.last_status ?? "none"}</span></div>}</form></section><aside className="panel compact-panel"><p className="eyebrow">Connections</p><h2><ShieldCheck size={15} /> Read-only boundary</h2><p>GitHub {readiness.data?.secrets.github_token?.status ?? "checking"}</p><p>OpenAI {readiness.data?.secrets.openai_api_key?.status ?? "checking"}</p><small>Secrets stay in environment variables and are never stored in configuration revisions or browser responses.</small></aside></div></div>;
}
