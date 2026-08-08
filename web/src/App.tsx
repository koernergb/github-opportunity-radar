import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, RouterProvider } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { HomePage } from "./pages/HomePage";
import { OpportunitiesPage } from "./pages/OpportunitiesPage";
import { PreferencesPage } from "./pages/PreferencesPage";
import { RepositoriesPage } from "./pages/RepositoriesPage";
import { AssistantPage, RunsPage, SettingsPage } from "./pages/Pages";

const router = createBrowserRouter([{ path: "/", element: <AppShell />, errorElement: <main className="fatal-state"><h1>That page could not load</h1><a href="/">Return home</a></main>, children: [
  { index: true, element: <HomePage /> },
  { path: "assistant", element: <AssistantPage /> },
  { path: "opportunities", element: <OpportunitiesPage /> },
  { path: "repositories", element: <RepositoriesPage /> },
  { path: "preferences", element: <PreferencesPage /> },
  { path: "runs", element: <RunsPage /> },
  { path: "settings", element: <SettingsPage /> },
]}]);
const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } });

export function App() { return <QueryClientProvider client={queryClient}><RouterProvider router={router} /></QueryClientProvider>; }
