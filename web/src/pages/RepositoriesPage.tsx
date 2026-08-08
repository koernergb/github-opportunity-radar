import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, GitBranch, Plus, Power } from "lucide-react";
import { useState } from "react";

import { getValidated, postJson } from "../api/client";
import { preferencesSchema, repositoriesSchema, revisionSchema } from "../api/types";
import { PageHeader } from "../components/AppShell";

type RepositoryConfig = Record<string, unknown> & { full_name: string; enabled: boolean };
type EditableConfig = Record<string, unknown> & { repositories: RepositoryConfig[] };

export function RepositoriesPage() {
  const queryClient = useQueryClient();
  const observed = useQuery({
    queryKey: ["repositories"],
    queryFn: () => getValidated("/repositories", repositoriesSchema),
  });
  const preferences = useQuery({
    queryKey: ["preferences"],
    queryFn: () => getValidated("/preferences", preferencesSchema),
  });
  const [name, setName] = useState("");
  const [message, setMessage] = useState("");
  const mutateConfig = useMutation({
    mutationFn: ({ fullName, action }: { fullName: string; action: "add" | "toggle" }) => {
      if (!/^[A-Za-z0-9-]+\/[A-Za-z0-9_.-]+$/.test(fullName)) {
        throw new Error("Use owner/repository format.");
      }
      const config = structuredClone(
        preferences.data?.config ?? { repositories: [] },
      ) as EditableConfig;
      const repositories = [...config.repositories];
      const index = repositories.findIndex(
        (repository) => repository.full_name.toLowerCase() === fullName.toLowerCase(),
      );
      if (action === "add") {
        if (index >= 0) throw new Error("Repository is already tracked.");
        repositories.push({
          full_name: fullName,
          enabled: true,
          include_labels: [],
          exclude_labels: [],
          min_issue_age_minutes: 30,
          max_issue_age_days: 730,
          max_estimated_hours: null,
          custom_weights: {},
          exclude_assigned_to_others: true,
        });
      } else if (index >= 0) {
        repositories[index] = {
          ...repositories[index],
          enabled: !repositories[index]?.enabled,
        } as RepositoryConfig;
      }
      config.repositories = repositories;
      return postJson(
        "/preferences/proposals",
        {
          config,
          summary: `${action === "add" ? "Track" : "Toggle"} ${fullName}`,
          expected_active_id: preferences.data?.revision.revision_id ?? null,
          activate: true,
          source: "manual",
        },
        revisionSchema,
      );
    },
    onSuccess: async () => {
      setName("");
      setMessage("Configuration revision activated. GitHub was not modified.");
      await queryClient.invalidateQueries({ queryKey: ["preferences"] });
    },
    onError: (error) => setMessage(error.message),
  });
  const configured = (preferences.data?.config.repositories ?? []) as RepositoryConfig[];
  return (
    <div className="page repositories-content">
      <PageHeader eyebrow="Tracking" title="Repositories" />
      <section className="add-repository">
        <label><span>Add a public repository</span><input value={name} onChange={(event) => setName(event.target.value)} placeholder="owner/repository" /></label>
        <button className="primary-button" onClick={() => mutateConfig.mutate({ fullName: name, action: "add" })} disabled={!name}><Plus size={15} />Add to config</button>
        <small>Radar only reads GitHub. This creates a local configuration revision.</small>
        {message && <p role="status">{message}</p>}
      </section>
      <section className="repository-list">
        <div className="repository-list-head"><span>Repository</span><span>Config</span><span>Observed sync</span><span>Health</span><span>Candidates</span><span /></div>
        {configured.map((repository) => {
          const state = observed.data?.find((item) => item.full_name === repository.full_name);
          return <article key={repository.full_name}><span><GitBranch size={15} /><strong>{repository.full_name}</strong></span><span className={repository.enabled ? "positive" : "muted"}>{repository.enabled ? "Enabled" : "Disabled"}</span><span>{state?.sync_status ?? "Not synced"}</span><span>{state?.health ? "Available" : "Awaiting evidence"}</span><span>{state?.candidate_count ?? 0}</span><button className="secondary-button" onClick={() => mutateConfig.mutate({ fullName: repository.full_name, action: "toggle" })}><Power size={14} />{repository.enabled ? "Disable" : "Enable"}</button></article>;
        })}
        {configured.length === 0 && <div className="inline-state"><Activity />No repositories configured.</div>}
      </section>
    </div>
  );
}
