"use client";

import dynamic from "next/dynamic";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

const GraphView = dynamic(() => import("@/components/GraphView"), { ssr: false });

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type Passage = { id: string; ordinal: number; content: string };
type Message = { id: string; role: "user" | "assistant"; content: string; answer_version_id: string | null; passages: Passage[] };
type BranchMessage = { id: string; role: "user" | "assistant"; content: string };
type SelectedText = { text: string; source_passage_ids: string[]; versionId: string };
type Branch = {
  id: string; source_passage_id: string; source_answer_version_id: string; action_type: string;
  user_instruction: string; status: string; accepted: boolean | null; reviewer_note: string;
  source_passage: string; selections: { text: string; source_passage_ids: string[] }[]; messages: BranchMessage[];
};
type Conversation = {
  id: string; title: string; current_answer_version_id: string | null;
  messages: Message[]; branches: Branch[]; versions: { id: string; version_number: number; content: string }[];
  context_sources?: { target_message_id: string; source_branch_id: string; source_branch_message_ids: string[]; source_status: string; source_accepted: boolean | null }[];
};

type DebugLog = { at: string; method: string; path: string; request: unknown; status: number | null; modelTrace: unknown; error?: string };

async function api<T>(path: string, init?: RequestInit, onDebug?: (entry: DebugLog) => void): Promise<T> {
  const method = init?.method || "GET";
  let requestBody: unknown = null;
  if (typeof init?.body === "string") {
    try { requestBody = JSON.parse(init.body); } catch { requestBody = init.body; }
  }
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  const payload = await response.json().catch(() => null);
  onDebug?.({
    at: new Date().toISOString(),
    method,
    path,
    request: requestBody,
    status: response.status,
    modelTrace: payload?.debug_trace || null,
    error: response.ok ? undefined : payload?.detail || `Request failed (${response.status})`,
  });
  if (!response.ok) {
    throw new Error(payload?.detail || `Request failed (${response.status})`);
  }
  return payload as T;
}

function InlineText({ text }: { text: string }) {
  return <>{text.split(/(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g).map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={index}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("*") && part.endsWith("*")) return <em key={index}>{part.slice(1, -1)}</em>;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={index}>{part.slice(1, -1)}</code>;
    return <span key={index}>{part}</span>;
  })}</>;
}

export default function Home() {
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [provider, setProvider] = useState<"mock" | "groq">("mock");
  const [model, setModel] = useState("qwen/qwen3.8-27b");
  const [view, setView] = useState<"chat" | "graph">("chat");
  const [selectedTexts, setSelectedTexts] = useState<SelectedText[]>([]);
  const [selectionToolbar, setSelectionToolbar] = useState<{ left: number; top: number } | null>(null);
  const [captureAdditional, setCaptureAdditional] = useState(false);
  const [askDialogOpen, setAskDialogOpen] = useState(false);
  const [selectionPrompt, setSelectionPrompt] = useState("");
  const [activeBranchId, setActiveBranchId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [branchReply, setBranchReply] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [debugOpen, setDebugOpen] = useState(false);
  const [debugLogs, setDebugLogs] = useState<DebugLog[]>([]);
  const recordDebug = useCallback((entry: DebugLog) => setDebugLogs((current) => [entry, ...current].slice(0, 20)), []);

  const refresh = useCallback(async () => {
    const payload = await api<{ provider: "mock" | "groq"; model: string; conversation: Conversation }>("/api/demo");
    setProvider(payload.provider); setModel(payload.model); setConversation(payload.conversation);
  }, []);

  useEffect(() => { refresh().catch((e) => setError(e.message)); }, [refresh]);

  const selectedBranch = useMemo(
    () => conversation?.branches.find((branch) => branch.id === activeBranchId) || null,
    [conversation, activeBranchId],
  );

  function captureTextSelection() {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || !selection.toString().trim()) return;
    const ranges = Array.from({ length: selection.rangeCount }, (_, index) => selection.getRangeAt(index));
    const firstRange = ranges[0];
    const startElement = firstRange.startContainer.nodeType === Node.ELEMENT_NODE
      ? firstRange.startContainer as Element
      : firstRange.startContainer.parentElement;
    const answerCard = startElement?.closest<HTMLElement>(".answer-card");
    if (!answerCard) return;
    const versionId = answerCard.dataset.answerVersionId;
    if (!versionId || ranges.some((range) => {
      const endElement = range.endContainer.nodeType === Node.ELEMENT_NODE
        ? range.endContainer as Element
        : range.endContainer.parentElement;
      return endElement?.closest(".answer-card") !== answerCard;
    })) return;

    const fragments = ranges.map((range) => {
      const text = range.toString().trim();
      const passageIds = Array.from(answerCard.querySelectorAll<HTMLElement>("[data-passage-id]"))
        .filter((element) => {
          try { return range.intersectsNode(element); } catch { return false; }
        })
        .map((element) => element.dataset.passageId)
        .filter((id): id is string => Boolean(id));
      return { text, source_passage_ids: [...new Set(passageIds)], versionId };
    }).filter((fragment) => fragment.text && fragment.source_passage_ids.length);
    if (!fragments.length) return;
    if (captureAdditional && selectedTexts[0]?.versionId !== versionId) {
      setError("Add selections from the same answer version.");
      return;
    }

    setSelectedTexts((current) => {
      const next = captureAdditional ? [...current, ...fragments] : fragments;
      return next.slice(0, 12);
    });
    setCaptureAdditional(false);
    const rect = firstRange.getBoundingClientRect();
    setSelectionToolbar({
      left: Math.max(16, Math.min(rect.left + rect.width / 2, window.innerWidth - 210)),
      top: Math.max(12, rect.top - 58),
    });
    setActiveBranchId(null);
  }

  function startAdditionalSelection() {
    setCaptureAdditional(true);
    setSelectionToolbar(null);
    window.getSelection()?.removeAllRanges();
  }

  function clearTextSelection() {
    setSelectedTexts([]);
    setSelectionToolbar(null);
    setCaptureAdditional(false);
    setAskDialogOpen(false);
    setSelectionPrompt("");
    window.getSelection()?.removeAllRanges();
  }

  async function submitSelectionQuestion(e: FormEvent) {
    e.preventDefault();
    if (!conversation || !selectedTexts.length || !selectionPrompt.trim() || busy) return;
    setError(""); setBusy(true);
    try {
      const updated = await api<Conversation>(`/api/conversations/${conversation.id}/branches`, {
        method: "POST", body: JSON.stringify({
          source_passage_id: selectedTexts[0].source_passage_ids[0],
          source_answer_version_id: selectedTexts[0].versionId,
          action_type: "ask",
          user_instruction: selectionPrompt.trim(),
          selections: selectedTexts.map(({ text, source_passage_ids }) => ({ text, source_passage_ids })),
          debug: debugOpen,
        }),
      }, debugOpen ? recordDebug : undefined);
      setConversation(updated);
      setActiveBranchId(updated.branches.at(-1)?.id || null);
      clearTextSelection();
    } catch (e) { setError(e instanceof Error ? e.message : "Could not ask about the selected text"); }
    finally { setBusy(false); }
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!conversation || !draft.trim() || busy) return;
    setError(""); setBusy(true);
    try {
      const updated = await api<Conversation>(`/api/conversations/${conversation.id}/messages`, {
        method: "POST", body: JSON.stringify({ question: draft.trim(), debug: debugOpen }),
      }, debugOpen ? recordDebug : undefined);
      setConversation(updated); setDraft(""); setActiveBranchId(null);
    } catch (e) { setError(e instanceof Error ? e.message : "Something went wrong"); }
    finally { setBusy(false); }
  }

  async function newConversation() {
    setBusy(true); setError("");
    try {
      const next = await api<Conversation>("/api/conversations", { method: "POST", body: "{}" });
      setConversation(next); clearTextSelection(); setActiveBranchId(null); setView("chat");
    } catch (e) { setError(e instanceof Error ? e.message : "Could not create conversation"); }
    finally { setBusy(false); }
  }

  async function continueBranch(e: FormEvent) {
    e.preventDefault();
    if (!selectedBranch || !branchReply.trim() || busy) return;
    setBusy(true); setError("");
    try {
      const updated = await api<Conversation>(`/api/branches/${selectedBranch.id}/messages`, {
        method: "POST", body: JSON.stringify({ message: branchReply.trim(), debug: debugOpen }),
      }, debugOpen ? recordDebug : undefined);
      setConversation(updated); setBranchReply("");
    } catch (e) { setError(e instanceof Error ? e.message : "Could not continue branch"); }
    finally { setBusy(false); }
  }

  async function decideBranch(branch: Branch, decision: "accept" | "reject") {
    setBusy(true); setError("");
    try {
      const updated = await api<Conversation>(`/api/branches/${branch.id}/status?decision=${decision}`, { method: "PATCH" }, debugOpen ? recordDebug : undefined);
      setConversation(updated);
    } catch (e) { setError(e instanceof Error ? e.message : "Could not update branch"); }
    finally { setBusy(false); }
  }

  if (!conversation) return <main className="loading-screen"><div className="brand-mark">i</div><p>{error || "Opening your workspace…"}</p></main>;

  return (
    <main className="app-shell">
      <aside className="left-rail">
        <a className="brand" href="#top" aria-label="InlineGraph AI home"><span className="brand-mark">i</span><span>inlinegraph<span className="brand-ai">.ai</span></span></a>
        <button className="new-chat" onClick={newConversation} disabled={busy}><span>＋</span> New conversation</button>
        <div className="rail-label">WORKSPACE</div>
        <button className="history-item active"><span className="history-dot" />{conversation.title}</button>
        <div className="rail-bottom"><div className="avatar">A</div><div><strong>Local workspace</strong><small>Private demo</small></div><span className="more">···</span></div>
      </aside>

      <section className="workspace" id="top">
        <header className="topbar">
          <div className="crumb">Workspace <span>/</span> {conversation.title}</div>
          <div className="top-actions">
            <div className={`provider-pill ${provider === "groq" ? "provider-live" : "provider-mock"}`}>
              <span className="status-dot" />{provider === "groq" ? `GROQ · ${model}` : "MOCK MODE"}
            </div>
            <div className="view-switch" role="tablist" aria-label="Conversation view">
              <button role="tab" aria-selected={view === "chat"} className={view === "chat" ? "selected" : ""} onClick={() => setView("chat")}>◻ Chat</button>
              <button role="tab" aria-selected={view === "graph"} className={view === "graph" ? "selected" : ""} onClick={() => setView("graph")}>⌘ Graph</button>
            </div>
            <button className="debug-toggle" type="button" aria-pressed={debugOpen} onClick={() => setDebugOpen((open) => !open)}>{debugOpen ? "Hide logs" : "See logs"}</button>
          </div>
        </header>

        {debugOpen && <aside className="debug-panel" aria-label="Request debugger">
          <div className="debug-panel-heading"><div><span className="eyebrow">LOCAL DEBUGGER</span><h2>Request logs</h2><p>Session only · captures new requests while open · API keys are never included</p></div><div className="debug-panel-actions"><button type="button" onClick={() => setDebugLogs([])}>Clear</button><button type="button" aria-label="Hide logs" onClick={() => setDebugOpen(false)}>×</button></div></div>
          {debugLogs.length === 0 ? <p className="debug-empty">Send a main-chat question, ask about selected text, or continue a branch to capture its API body and the exact prompt sent to the model.</p> : <div className="debug-log-list">{debugLogs.map((entry, index) => <details className="debug-log-entry" key={`${entry.at}-${index}`} open={index === 0}>
            <summary><span>{entry.method} {entry.path}</span><time>{new Date(entry.at).toLocaleTimeString()}</time><i>{entry.status ?? "ERR"}</i></summary>
            <h3>Browser → API request</h3><pre>{JSON.stringify(entry.request, null, 2)}</pre>
            <h3>Backend → model request and response</h3>{entry.modelTrace ? <pre>{JSON.stringify(entry.modelTrace, null, 2)}</pre> : <p className="debug-empty">{entry.path.includes("/status") ? "This review-status request does not call an AI model." : "No model trace was returned; inspect the request status and error above."}</p>}
            {entry.error && <p className="debug-error">{entry.error}</p>}
          </details>)}</div>}
        </aside>}

        {provider === "mock" && <div className="mock-banner"><span>ⓘ</span><div><strong>Previewing with local sample responses.</strong> Add <code>GROQ_API_KEY</code> to the root <code>.env</code> and restart the API to enable Qwen.</div></div>}
        {error && <div className="error-banner" role="alert">{error}<button onClick={() => setError("")} aria-label="Dismiss">×</button></div>}

        {view === "graph" ? (
          <div className="graph-layout">
            <div className="graph-area"><GraphView conversation={conversation} onSelectBranch={(id) => setActiveBranchId(id)} /></div>
            <aside className="graph-inspector">
              <div className="inspector-heading"><div><span className="eyebrow">SELECTED NODE</span><h2>{selectedBranch ? "Branch detail" : "Graph detail"}</h2></div>{selectedBranch && <span className={`status-label status-${selectedBranch.status}`}>{selectedBranch.status.replaceAll("_", " ")}</span>}</div>
              {selectedBranch ? <div className="graph-branch-detail">
                <div className="branch-title-row"><span className="action-icon action-ask">?</span><div><h3>Question about selected text</h3><small>{selectedBranch.user_instruction}</small></div></div>
                {selectedBranch.status === "accepted" && <div className="accepted-context-note">✓ Accepted. This answer will be included in context for your next main-chat question.</div>}
                <div className="inspector-section"><span className="eyebrow">SELECTED TEXT</span>{(selectedBranch.selections || []).map((item, index) => <blockquote key={`${index}-${item.text}`}>{item.text}</blockquote>)}{!selectedBranch.selections?.length && <blockquote>{selectedBranch.source_passage}</blockquote>}</div>
                <div className="inspector-section"><span className="eyebrow">SOURCE PARAGRAPH</span><blockquote>{selectedBranch.source_passage}</blockquote></div>
                {selectedBranch.messages.filter((item) => item.role === "assistant").map((item) => <div className="inspector-section" key={item.id}><span className="eyebrow">BRANCH ANSWER</span><p>{item.content}</p></div>)}
                {selectedBranch.reviewer_note && <div className="review-note"><span>Runtime review</span><p>{selectedBranch.reviewer_note}</p><small>Advisory only; it does not verify factual accuracy.</small></div>}
                <div className="graph-inspector-actions">
                  {selectedBranch.status !== "accepted" && <><button className="secondary-button" disabled={busy} onClick={() => decideBranch(selectedBranch, "reject")}>Reject branch</button><button className="accept-button" disabled={busy} onClick={() => decideBranch(selectedBranch, "accept")}>✓ Accept</button></>}
                  <button className="back-link" onClick={() => { setView("chat"); setBranchReply(""); }}>← Continue in chat view</button>
                </div>
              </div> : <div className="graph-detail-empty"><div className="node-hint">⌖</div><h3>Choose a node</h3><p>Select a branch to inspect its source, response, and review status. Select a passage to see its origin.</p><button onClick={() => setView("chat")}>Return to chat view</button></div>}
            </aside>
          </div>
        ) : (
          <div className="conversation-layout">
            <section className="chat-column" aria-label="Conversation">
              <div className="chat-scroll" onMouseUp={captureTextSelection} onKeyUp={(event) => { if (event.key.startsWith("Shift")) captureTextSelection(); }}>
                <div className="welcome-heading"><span className="eyebrow">PASSAGE-FIRST AI</span><h1>Explore an answer,<br /><em>one idea at a time.</em></h1><p>Select any text in an answer to ask a question. Add multiple selections when you want to connect ideas.</p></div>
                {conversation.messages.map((message) => message.role === "user" ? (
                  <div className="user-row" key={message.id}><div className="user-bubble">{message.content}</div><div className="user-avatar">A</div></div>
                ) : (
                  <article className="answer-card" key={message.id} data-answer-version-id={message.answer_version_id || ""}>
                    <div className="answer-top"><div className="assistant-mark">✳</div><div className="answer-meta"><strong>InlineGraph</strong><span>Answer · v{conversation.versions.find((version) => version.id === message.answer_version_id)?.version_number || 1}</span></div><button className="icon-button" title="Copy answer" onClick={() => navigator.clipboard?.writeText(message.content)}>⧉</button></div>
                    <div className="answer-body">
                      {message.passages.map((passage) => {
                        const count = conversation.branches.filter((branch) => branch.source_passage_id === passage.id).length;
                        return <div className="passage-wrap" key={passage.id}>
                          <p className="passage"><span className="passage-content" data-passage-id={passage.id}><InlineText text={passage.content} /></span>{count > 0 && <span className="branch-count">{count} {count === 1 ? "branch" : "branches"}</span>}</p>
                        </div>;
                      })}
                    </div>
                    <div className="answer-foot"><span>↳ Highlight a phrase or several passages to ask about them</span><button onClick={() => setView("graph")}>View in graph ↗</button></div>
                  </article>
                ))}
                {conversation.messages.length <= 1 && <div className="starter-prompts"><span>Try asking</span>{["Why does tree cover matter?", "What solutions work best?"].map((q) => <button key={q} onClick={() => setDraft(q)}>{q} <span>↗</span></button>)}</div>}
              </div>

              <form className="composer" onSubmit={submit}>
                <div className="composer-input"><textarea id="composer-input" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Ask a follow-up or start a new topic…" rows={2} maxLength={8000} disabled={busy} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); e.currentTarget.form?.requestSubmit(); } }} />
                  <div className="composer-bottom"><span><kbd>↵</kbd> send <span className="hint-separator">·</span> <kbd>⇧ ↵</kbd> new line</span><button className="send-button" type="submit" disabled={busy || !draft.trim()} aria-label="Send message">{busy ? <span className="spinner" /> : "↑"}</button></div>
                </div>
              </form>
            </section>

            <aside className="inspector" aria-label="Branch inspector">
              <div className="inspector-heading"><div><span className="eyebrow">EXPLORATION</span><h2>{selectedBranch ? "Branch detail" : "Branch map"}</h2></div><span className="branch-total">{conversation.branches.length.toString().padStart(2, "0")}</span></div>
              {selectedBranch ? <div className="branch-detail">
                <button className="back-link" onClick={() => setActiveBranchId(null)}>← All branches</button>
                <div className="branch-title-row"><span className="action-icon action-ask">?</span><div><h3>Question about selected text</h3><span className={`status-label status-${selectedBranch.status}`}>{selectedBranch.status.replaceAll("_", " ")}</span></div></div>
                {selectedBranch.status === "accepted" && <div className="accepted-context-note">✓ Accepted. This answer will be included in context for your next main-chat question.</div>}
                <div className="inspector-section"><span className="eyebrow">SELECTED TEXT</span>{(selectedBranch.selections || []).map((item, index) => <blockquote key={`${index}-${item.text}`}>{item.text}</blockquote>)}{!selectedBranch.selections?.length && <blockquote>{selectedBranch.source_passage}</blockquote>}</div>
                <div className="inspector-section"><span className="eyebrow">SOURCE PARAGRAPH</span><blockquote>{selectedBranch.source_passage}</blockquote></div>
                <div className="inspector-section"><span className="eyebrow">INSTRUCTION</span><p>{selectedBranch.user_instruction}</p></div>
                <div className="branch-thread">{selectedBranch.messages.map((message) => <div key={message.id} className={`branch-message ${message.role}`}><span>{message.role === "assistant" ? "✳" : "You"}</span><p><InlineText text={message.content} /></p></div>)}</div>
                {selectedBranch.reviewer_note && <div className="review-note"><span>Runtime review</span><p>{selectedBranch.reviewer_note}</p><small>Advisory check; it does not verify factual accuracy.</small></div>}
                <form className="continue-form" onSubmit={continueBranch}><textarea value={branchReply} onChange={(e) => setBranchReply(e.target.value)} rows={2} placeholder="Continue this branch…" disabled={busy} /><button disabled={busy || !branchReply.trim()} aria-label="Continue branch">↑</button></form>
                {selectedBranch.status !== "accepted" && <div className="branch-controls"><button className="secondary-button" disabled={busy} onClick={() => decideBranch(selectedBranch, "reject")}>Reject</button><button className="accept-button" disabled={busy} onClick={() => decideBranch(selectedBranch, "accept")}>✓ Accept</button></div>}
              </div> : conversation.branches.length ? <div className="branch-list">{conversation.branches.map((branch) => <button className="branch-list-item" key={branch.id} onClick={() => setActiveBranchId(branch.id)}><span className="action-icon action-ask">?</span><span className="branch-list-copy"><strong>Question</strong><small>{branch.user_instruction}</small></span><span className={`list-status status-${branch.status}`} aria-label={branch.status} /></button>)}</div> : <div className="empty-map"><div className="empty-map-graphic"><span>✳</span><i>↗</i><b>?</b></div><h3>Your branches live here</h3><p>Highlight any text in an answer, then ask a question about it. Earlier explorations also inform later answers.</p><button onClick={() => document.querySelector<HTMLElement>(".passage-content")?.scrollIntoView({ behavior: "smooth", block: "center" })}>Select text in an answer <span>↑</span></button></div>}
              <div className="inspector-bottom"><span className="legend-dot" /> Independent by default <span className="legend-divider">·</span> User controlled</div>
            </aside>
          </div>
        )}
      </section>

      {captureAdditional && <div className="selection-mode-hint" role="status">Select another part of this answer</div>}
      {selectionToolbar && selectedTexts.length > 0 && !askDialogOpen && <div
        className="selection-toolbar"
        role="toolbar"
        aria-label="Actions for selected text"
        style={{ left: selectionToolbar.left, top: selectionToolbar.top }}
        onMouseDown={(event) => event.preventDefault()}
      >
        <span className="selection-count">{selectedTexts.length} {selectedTexts.length === 1 ? "selection" : "selections"}</span>
        {selectedTexts.length < 12 && <button type="button" onClick={startAdditionalSelection}>＋ Add another</button>}
        <button type="button" className="selection-ask-button" onClick={() => setAskDialogOpen(true)}>Ask</button>
        <button type="button" className="selection-close" aria-label="Clear selection" onClick={clearTextSelection}>×</button>
      </div>}

      {askDialogOpen && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) clearTextSelection(); }}>
        <section className="ask-selection-modal" role="dialog" aria-modal="true" aria-labelledby="ask-selection-title">
          <div className="modal-heading"><div><span className="eyebrow">SELECTED TEXT</span><h2 id="ask-selection-title">What would you like to ask?</h2></div><button className="icon-button" type="button" onClick={clearTextSelection} aria-label="Close question">×</button></div>
          <div className="selected-text-list">{selectedTexts.map((item, index) => <blockquote key={`${index}-${item.text}`}>{item.text}</blockquote>)}</div>
          <form onSubmit={submitSelectionQuestion}>
            <label className="sr-only" htmlFor="selection-question">Your question about the selected text</label>
            <textarea id="selection-question" className="selection-question-input" value={selectionPrompt} onChange={(event) => setSelectionPrompt(event.target.value)} placeholder="Ask anything about the selected text…" maxLength={4000} rows={3} autoFocus disabled={busy} onKeyDown={(event) => { if (event.key === "Escape") clearTextSelection(); }} />
            <div className="selection-dialog-footer"><button type="button" className="secondary-button" disabled={busy || selectedTexts.length >= 12} onClick={() => { setAskDialogOpen(false); startAdditionalSelection(); }}>＋ Add another highlight</button><button className="accept-button" type="submit" disabled={busy || !selectionPrompt.trim()}>{busy ? "Asking…" : "Ask question ↑"}</button></div>
          </form>
        </section>
      </div>}

    </main>
  );
}
