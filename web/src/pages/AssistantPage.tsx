import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, MessageSquarePlus, Send } from "lucide-react";
import { type FormEvent, useState } from "react";

import { ApiClientError, getValidated, postJson } from "../api/client";
import { conversationDetailSchema, conversationSummarySchema, type ConversationMessage } from "../api/types";
import { PageHeader } from "../components/AppShell";

export function AssistantPage() {
  const queryClient = useQueryClient();
  const conversations = useQuery({ queryKey: ["conversations"], queryFn: () => getValidated("/conversations", conversationSummarySchema.array()) });
  const [selected, setSelected] = useState<string | null>(null);
  const activeId = selected ?? conversations.data?.[0]?.conversation_id ?? null;
  const detail = useQuery({ queryKey: ["conversation", activeId], queryFn: () => getValidated(`/conversations/${activeId}`, conversationDetailSchema), enabled: Boolean(activeId) });
  const create = useMutation({ mutationFn: () => postJson("/conversations", { title: "New conversation" }, conversationSummarySchema), onSuccess: async (value) => { setSelected(value.conversation_id); await queryClient.invalidateQueries({ queryKey: ["conversations"] }); } });
  const [draft, setDraft] = useState(""); const [streamed, setStreamed] = useState(""); const [sending, setSending] = useState(false); const [error, setError] = useState<string | null>(null);
  async function submit(event: FormEvent) {
    event.preventDefault(); if (!activeId || !draft.trim() || sending) return;
    const content = draft.trim(); setDraft(""); setStreamed(""); setError(null); setSending(true);
    try { await streamTurn(activeId, content, (delta) => setStreamed((current) => current + delta)); await queryClient.invalidateQueries({ queryKey: ["conversations"] }); }
    catch (reason) { setError(reason instanceof ApiClientError && reason.status === 503 ? "The assistant is unavailable until an OpenAI API key is configured." : "The assistant could not complete that turn. Your prior conversation is preserved."); }
    finally { setSending(false); }
  }
  return <div className="page"><PageHeader eyebrow="Grounded in stored Radar evidence" title="Assistant"><button className="secondary-button" onClick={() => create.mutate()}><MessageSquarePlus size={15} />New chat</button></PageHeader><div className="assistant-grid"><aside className="panel conversation-list"><div className="panel-heading"><h2>Conversations</h2></div>{conversations.data?.map((item) => <button key={item.conversation_id} className={item.conversation_id === activeId ? "selected" : ""} onClick={() => { setSelected(item.conversation_id); setStreamed(""); setError(null); }}><strong>{item.title}</strong><small>{item.message_count} messages</small></button>)}{conversations.data?.length === 0 && <div className="inline-state">Start a conversation to ask about ranked issues.</div>}</aside><section className="panel chat-panel"><div className="chat-transcript" aria-live="polite">{!activeId && <div className="assistant-empty"><Bot /><h2>Ask Radar</h2><p>Create a chat, then ask about opportunities, repository health, or recent runs. Answers use persisted read-only evidence.</p><button className="primary-button" onClick={() => create.mutate()}>Create conversation</button></div>}{detail.data?.messages.map((message) => <ChatMessage key={message.message_id} message={message} />)}{streamed && <ChatMessage message={{ message_id: "stream", role: "assistant", content: streamed, status: "streaming", error_code: null, created_at: new Date().toISOString() }} />}{error && <div className="chat-error">{error}</div>}</div><form className="chat-composer" onSubmit={submit}><label className="sr-only" htmlFor="assistant-message">Message Radar</label><textarea id="assistant-message" value={draft} onChange={(event) => setDraft(event.target.value)} placeholder={activeId ? "Ask about ranked issues…" : "Create a conversation first"} disabled={!activeId || sending} /><button className="primary-button" type="submit" disabled={!activeId || !draft.trim() || sending}><Send size={15} />{sending ? "Thinking…" : "Send"}</button><small>Read-only · tool use and sources are recorded</small></form></section></div></div>;
}

function ChatMessage({ message }: { message: ConversationMessage }) { return <article className={`chat-message ${message.role}`}><span>{message.role === "assistant" ? "Radar" : "You"}</span><p>{message.content || (message.status === "failed" ? "This turn failed safely." : "")}</p></article>; }

async function streamTurn(conversationId: string, content: string, onDelta: (text: string) => void) {
  const response = await fetch(`/api/v1/conversations/${conversationId}/messages`, { method: "POST", headers: { Accept: "text/event-stream", "Content-Type": "application/json" }, body: JSON.stringify({ content }) });
  if (!response.ok) throw new ApiClientError("Assistant unavailable", response.status); if (!response.body) throw new Error("Streaming is unavailable");
  const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = "";
  while (true) { const { done, value } = await reader.read(); buffer += decoder.decode(value, { stream: !done }); const blocks = buffer.split("\n\n"); buffer = blocks.pop() ?? ""; for (const block of blocks) { const event = block.match(/^event: (.+)$/m)?.[1]; const data = block.match(/^data: (.+)$/m)?.[1]; if (!data) continue; const payload = JSON.parse(data) as { text?: string }; if (event === "text_delta" && payload.text) onDelta(payload.text); if (event === "error") throw new Error("Assistant turn failed"); } if (done) break; }
}
