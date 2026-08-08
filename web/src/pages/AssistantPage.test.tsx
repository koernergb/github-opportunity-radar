import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { expect, it } from "vitest";

import { server } from "../test/mocks";
import { AssistantPage } from "./AssistantPage";

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><AssistantPage /></QueryClientProvider>);
}

it("loads persisted history and streams a grounded answer", async () => {
  const user = userEvent.setup(); renderPage();
  expect(await screen.findByText("MLX #42 has the strongest stored score.")).toBeInTheDocument();
  await user.type(screen.getByLabelText("Message Radar"), "Which issue should I choose?");
  await user.click(screen.getByRole("button", { name: "Send" }));
  expect(await screen.findByText("Grounded answer")).toBeInTheDocument();
});

it("isolates a missing provider key to the assistant", async () => {
  server.use(http.post("/api/v1/conversations/:conversationId/messages", () => HttpResponse.json({ error: { code: "assistant_unavailable" } }, { status: 503 })));
  const user = userEvent.setup(); renderPage(); await screen.findByText("Best performance work");
  await user.type(screen.getByLabelText("Message Radar"), "Hello"); await user.click(screen.getByRole("button", { name: "Send" }));
  expect(await screen.findByText(/unavailable until an OpenAI API key/)).toBeInTheDocument();
});
