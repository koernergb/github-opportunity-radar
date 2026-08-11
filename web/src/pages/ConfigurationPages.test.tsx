import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { MemoryRouter } from "react-router-dom";
import { expect, it } from "vitest";

import { PreferencesPage } from "./PreferencesPage";
import { RepositoriesPage } from "./RepositoriesPage";
import { SettingsPage } from "./SettingsPage";

function renderWithClient(element: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter>{element}</MemoryRouter></QueryClientProvider>);
}

it("validates a preference revision before activation", async () => {
  const user = userEvent.setup();
  const view = renderWithClient(<PreferencesPage />);
  const timezone = await screen.findByRole("textbox", { name: "Timezone" });
  await user.clear(timezone);
  await user.type(timezone, "UTC");
  await user.click(screen.getByRole("button", { name: "Validate & preview" }));
  expect(await screen.findByText("Valid configuration. Review and activate it.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Activate revision/ })).toBeInTheDocument();
  expect(await axe(view.container)).toHaveNoViolations();
});

it("adds a repository through local configuration only", async () => {
  const user = userEvent.setup();
  renderWithClient(<RepositoriesPage />);
  const input = await screen.findByPlaceholderText("owner/repository");
  await user.type(input, "openai/openai-python");
  await user.click(screen.getByRole("button", { name: /Add to config/ }));
  expect(await screen.findByText(/GitHub was not modified/)).toBeInTheDocument();
});

it("keeps provider credentials write-only in settings", async () => {
  const user = userEvent.setup();
  renderWithClient(<SettingsPage />);
  const keyInput = await screen.findByLabelText("Anthropic API key");
  expect(keyInput).toHaveAttribute("type", "password");
  expect(keyInput).toHaveValue("");
  await user.type(keyInput, "anthropic-secret");
  await user.click(screen.getAllByRole("button", { name: "Save key" })[1]!);
  expect(keyInput).toHaveValue("");
  expect(screen.queryByDisplayValue("anthropic-secret")).not.toBeInTheDocument();
});
