import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
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

it("previews exact arguments before a separate confirmation", async () => {
  let pending = true;
  server.use(http.get("/api/v1/assistant/proposals/:conversationId", () => HttpResponse.json(pending ? [{ proposal_id: "00000000-0000-0000-0000-000000000060", conversation_id: "00000000-0000-0000-0000-000000000050", base_revision_id: "00000000-0000-0000-0000-000000000010", resulting_revision_id: null, kind: "preferences", arguments: { interests: ["compilers"] }, argument_hash: "a".repeat(64), summary: "Update interests", status: "pending", created_at: "2026-08-08T12:00:00Z", expires_at: "2026-08-08T12:15:00Z", resolved_at: null }] : [])), http.post("/api/v1/assistant/proposals/:proposalId/confirm", () => { pending = false; return HttpResponse.json({ proposal_id: "00000000-0000-0000-0000-000000000060", conversation_id: "00000000-0000-0000-0000-000000000050", base_revision_id: "00000000-0000-0000-0000-000000000010", resulting_revision_id: "00000000-0000-0000-0000-000000000061", kind: "preferences", arguments: { interests: ["compilers"] }, argument_hash: "a".repeat(64), summary: "Update interests", status: "applied", created_at: "2026-08-08T12:00:00Z", expires_at: "2026-08-08T12:15:00Z", resolved_at: "2026-08-08T12:01:00Z" }); }));
  const user = userEvent.setup(); renderPage();
  expect(await screen.findByText(/"compilers"/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Confirm exact change" }));
  await waitFor(() => expect(screen.queryByRole("button", { name: "Confirm exact change" })).not.toBeInTheDocument());
});
