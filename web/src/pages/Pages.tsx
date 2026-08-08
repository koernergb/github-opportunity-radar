import { PageHeader, Placeholder } from "../components/AppShell";

function Page({ title, eyebrow, description, action }: { title: string; eyebrow: string; description: string; action?: string }) {
  return <div className="page"><PageHeader eyebrow={eyebrow} title={title}>{action && <button className="primary-button">{action}</button>}</PageHeader><Placeholder title={`${title} is ready`} description={description} /></div>;
}

export const AssistantPage = () => <Page eyebrow="Ask Radar" title="Assistant" description="Ask grounded questions about tracked repositories and ranked issues." />;
export const OpportunitiesPage = () => <Page eyebrow="Issue intelligence" title="Opportunities" description="Ranked issues will appear here with effort, fit, confidence, and maintainer evidence." />;
export const RepositoriesPage = () => <Page eyebrow="Tracking" title="Repositories" action="Add repository" description="Add open-source repositories to watch for contribution opportunities." />;
export const PreferencesPage = () => <Page eyebrow="Your profile" title="Preferences" action="Save revision" description="Tune languages, interests, effort limits, and scoring priorities." />;
export const RunsPage = () => <Page eyebrow="Pipeline activity" title="Runs" action="Run radar" description="Sync and analysis run history will appear here." />;
export const SettingsPage = () => <Page eyebrow="Local application" title="Settings" description="Review connection status, appearance, and local diagnostics." />;
