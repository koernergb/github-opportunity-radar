import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { AppShell } from "./components/AppShell";
import { HomePage } from "./pages/HomePage";
import { server } from "./test/mocks";

function renderHome() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><MemoryRouter><HomePage /></MemoryRouter></QueryClientProvider>);
}

describe("application foundation", () => {
  it("renders API-backed home content without accessibility violations", async () => {
    const view = renderHome();
    expect(await screen.findByText("Improve batched attention performance")).toBeInTheDocument();
    expect(await axe(view.container)).toHaveNoViolations();
  });

  it("exposes every primary route in keyboard navigation", async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><AppShell /></MemoryRouter>);
    for (const label of ["Home", "Assistant", "Opportunities", "Repositories", "Preferences", "Runs", "Settings"]) {
      expect(screen.getByRole("link", { name: label })).toBeInTheDocument();
    }
    await user.keyboard("{Control>}k{/Control}");
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Close command palette" })).toBeInTheDocument();
  });

  it("renders explicit empty and offline states", async () => {
    server.use(
      http.get("/api/v1/opportunities", () => HttpResponse.json({ items: [], meta: { page: 1, page_size: 25, total: 0 } })),
      http.get("/api/v1/readiness", () => HttpResponse.error()),
    );
    renderHome();
    expect(await screen.findByText(/No ranked issues yet/)).toBeInTheDocument();
    expect(await screen.findByText("Radar is offline")).toBeInTheDocument();
  });
});
