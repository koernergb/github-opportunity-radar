import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { MemoryRouter } from "react-router-dom";
import { expect, it } from "vitest";

import { OpportunitiesPage } from "./OpportunitiesPage";

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={["/opportunities"]}><OpportunitiesPage /></MemoryRouter></QueryClientProvider>);
}

it("shows explicit scoring semantics and renders issue text inertly", async () => {
  const user = userEvent.setup();
  const view = renderPage();
  expect(await screen.findByText("Improve batched attention performance")).toBeInTheDocument();
  expect(screen.getByText("heuristic")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /Open ml-explore\/mlx issue 42/ }));
  expect(await screen.findByText(/Treat <script>/)).toBeInTheDocument();
  expect(document.querySelector("script")).toBeNull();
  expect(await axe(view.container)).toHaveNoViolations();
});

it("keeps filters in URL state and appends feedback", async () => {
  const user = userEvent.setup();
  renderPage();
  const search = screen.getByRole("textbox", { name: "Search issues" });
  await user.type(search, "attention");
  expect(window.location.href).not.toContain("openai_api_key");
  await user.click(await screen.findByRole("button", { name: /Open ml-explore\/mlx issue 42/ }));
  await user.click(await screen.findByRole("button", { name: "Save" }));
  expect(await screen.findByText("Feedback appended.")).toBeInTheDocument();
});
