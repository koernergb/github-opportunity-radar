import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { expect, it } from "vitest";

import { RunsPage } from "./RunsPage";

it("renders durable run history and starts a queued run", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const user = userEvent.setup();
  render(<QueryClientProvider client={client}><MemoryRouter><RunsPage /></MemoryRouter></QueryClientProvider>);

  expect(await screen.findByText("Started digest")).toBeInTheDocument();
  expect(screen.getByText(/"scored": 4/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Run radar" }));
  expect(await screen.findByText("History")).toBeInTheDocument();
});
