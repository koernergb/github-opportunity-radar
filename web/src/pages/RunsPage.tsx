import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CircleAlert, Clock, Play, Square, Wifi } from "lucide-react";
import { useEffect, useState } from "react";
import { z } from "zod";

import { getValidated, postJson } from "../api/client";
import { runEventSchema, runsSchema, type Run } from "../api/types";
import { PageHeader } from "../components/AppShell";

const startSchema = z.object({ run_id: z.string(), status: z.literal("queued") });
const cancelSchema = z.object({ run_id: z.string(), status: z.literal("cancellation_requested"), boundary: z.literal("between_committed_units") });

export function RunsPage() {
  const queryClient = useQueryClient();
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => getValidated("/runs", runsSchema), refetchInterval: 5_000 });
  const [selected, setSelected] = useState<string | null>(null);
  const current = runs.data?.find((run) => run.run_id === selected) ?? runs.data?.[0];
  const start = useMutation({ mutationFn: () => postJson("/runs", { scope: "all", fallback_only: false, deadline_seconds: 600 }, startSchema), onSuccess: async (run) => { setSelected(run.run_id); await queryClient.invalidateQueries({ queryKey: ["runs"] }); } });
  const cancel = useMutation({ mutationFn: (runId: string) => postJson(`/runs/${runId}/cancel`, {}, cancelSchema) });
  return <div className="page"><PageHeader eyebrow="Pipeline activity" title="Runs"><button className="primary-button" onClick={() => start.mutate()} disabled={start.isPending}><Play size={15} />{start.isPending ? "Starting…" : "Run radar"}</button></PageHeader>
    {start.isError && <div className="validation-errors">Could not start: another run may own the lock, or a connection is unavailable.</div>}
    <div className="runs-grid"><section className="panel run-list"><div className="panel-heading"><h2>History</h2></div>{runs.data?.map((run) => <button key={run.run_id} className={current?.run_id === run.run_id ? "selected" : ""} onClick={() => setSelected(run.run_id)}><RunStatus status={run.status} /><span><strong>{run.status}</strong><small>{new Date(run.started_at).toLocaleString()}</small></span></button>)}{runs.data?.length === 0 && <div className="inline-state">No pipeline runs yet.</div>}</section><section className="panel run-detail">{current ? <><div className="panel-heading"><div><p className="eyebrow">{current.run_id.slice(0, 8)}</p><h2>{current.status} run</h2></div>{["queued", "running"].includes(current.status) && <button className="secondary-button" onClick={() => cancel.mutate(current.run_id)}><Square size={13} />Cancel safely</button>}</div><RunTimeline key={current.run_id} run={current} />{cancel.isSuccess && <p className="run-notice">Cancellation requested; committed work will be preserved.</p>}</> : <div className="inline-state">Select a run to inspect its timeline.</div>}</section></div>
  </div>;
}

function RunTimeline({ run }: { run: Run }) {
  const [events, setEvents] = useState<z.infer<typeof runEventSchema>[]>([]);
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    if (!["queued", "running"].includes(run.status)) {
      void getValidated(`/runs/${run.run_id}/events`, runEventSchema.array()).then(setEvents);
      return;
    }
    const source = new EventSource(`/api/v1/runs/${run.run_id}/stream`);
    source.onopen = () => setConnected(true);
    source.onmessage = (event) => {
      const parsed = runEventSchema.safeParse(JSON.parse(event.data));
      if (parsed.success) setEvents((current) => current.some((item) => item.event_id === parsed.data.event_id) ? current : [...current, parsed.data]);
    };
    source.addEventListener("run_queued", source.onmessage as EventListener);
    source.addEventListener("stage_started", source.onmessage as EventListener);
    source.onerror = () => setConnected(false);
    return () => source.close();
  }, [run.run_id, run.status]);
  return <div className="run-timeline"><div className="stream-status"><Wifi size={13} />{["queued", "running"].includes(run.status) ? connected ? "Live" : "Reconnecting…" : "Recorded events"}</div>{events.map((event) => <article key={event.event_id}><span className={`event-dot ${event.level}`} /><div><strong>{event.message}</strong><small>{event.stage} · {new Date(event.created_at).toLocaleTimeString()}</small>{event.error_type && <em><CircleAlert size={12} />{event.error_type}</em>}</div></article>)}{events.length === 0 && <div className="inline-state"><Clock />Waiting for the first event…</div>}<div className="run-summary"><h3>Run summary</h3><pre>{JSON.stringify(run.summary, null, 2)}</pre></div></div>;
}

function RunStatus({ status }: { status: string }) { return status === "success" ? <Check className="positive" size={16} /> : status === "failed" ? <CircleAlert className="danger" size={16} /> : <Clock className="warning" size={16} />; }
