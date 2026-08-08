import { PageHeader, Placeholder } from "../components/AppShell";

function Page({ title, eyebrow, description, action }: { title: string; eyebrow: string; description: string; action?: string }) {
  return <div className="page"><PageHeader eyebrow={eyebrow} title={title}>{action && <button className="primary-button">{action}</button>}</PageHeader><Placeholder title={`${title} is ready`} description={description} /></div>;
}

export const SettingsPage = () => <Page eyebrow="Local application" title="Settings" description="Review connection status, appearance, and local diagnostics." />;
