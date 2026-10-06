# InlineGraph AI Product and Implementation Guide

This document describes the current local application: what it does, how it is built, and what is not implemented. InlineGraph AI is a chat application for exploring selected parts of AI answers and carrying branch discussions into later prompts. Its branch workflow uses an LLM and a fixed, orchestrated sequence. It is not a general autonomous agent: it does not independently choose goals, use external tools, or take actions on a user's behalf.

## Product behavior

The main chat accepts a question and returns an answer. Users can select one or more text ranges from an answer, then open a prompt composer and ask a free-form question about them. Each exploration is saved as a branch with its selected text, source passages, prompt, replies, and review status. A branch can be continued as a normal conversational exchange.

Accepting a branch marks its content as approved context for a later main-chat question. It does not rewrite the current answer and does not require a separate merge action. When the user submits the next main-chat question, the backend includes prior conversation messages and earlier branch exchanges in the model prompt. Accepted branches are identified and prioritized; pending branches may help explain the user's intent; rejected branches are identified as not endorsed. The graph records which branch messages were included with each main-chat question.

The graph view displays main questions and answers, passages, selected text, branch prompts and replies, and context links into later questions. These links show which content was sent as context. They do not prove that the model relied on that content correctly.

## Agentic AI classification

The application is best described as an **LLM-powered chat application with an orchestrated branch workflow**, rather than an autonomous agent system. The branch workflow uses LangGraph to run a fixed sequence: prepare the prompt, generate a response, have a model review it, and optionally generate one revision. The backend also assembles and records context deterministically. The model does not select its own tools or actions, plan across open-ended goals, or perform external actions. Calling this workflow “agentic AI” without that qualification would overstate what the implementation does.

The runtime review is an advisory check for answering the latest instruction and handling supplied context. It is not an independent factuality check or a guarantee of correctness.

## Current technology and architecture

| Area | Current implementation |
|---|---|
| Web app | Next.js, React, and TypeScript |
| Graph interface | React Flow (`@xyflow/react`) |
| API | Python and FastAPI |
| Model orchestration | LangGraph branch workflow with SQLite checkpoints |
| Model access | Groq's OpenAI-compatible API through LangChain; default model ID `qwen/qwen3.8-27b` |
| Main chat data | SQLAlchemy with SQLite by default; `DATABASE_URL` can select another supported SQLAlchemy database such as PostgreSQL |
| Local model-free mode | Mock responses when no Groq key is configured, or when `LLM_MODE=mock` |

The Groq key is read by the backend from `.env`; it is not sent to the browser. The local application has no user accounts or production authentication. The graph is generated from relational conversation data; there is no separate graph database.

### Request flow

1. The web client submits a main-chat question or a branch prompt to FastAPI.
2. The API validates the conversation and selected passage references and gathers the applicable messages, selected text, source paragraphs, and earlier branch exchanges.
3. The main-chat model receives a prompt containing the conversation context and latest question. A branch model receives a system instruction plus role-separated branch history and the latest user turn.
4. Branch generation is reviewed by a second model call. If the reviewer requests a revision, the workflow may regenerate once and review again.
5. The API saves messages, status, and branch-to-question context provenance. The web app uses this data in chat and graph views.

## Context and history

Messages and branch exchanges are persisted in the local database. Main-chat prompts receive the earlier main conversation and prior branch explorations. Branch prompts receive the main conversation, relevant branch discussions, selected text, its full source paragraph or paragraphs, and the branch's own turns.

Context is assembled from stored history; there is no retrieval system, token-budget policy, automatic summarization, or context-window truncation implemented. Long conversations may eventually exceed the model's available context window. The graph and **See logs** debugger help inspect what was included, but they do not solve that size limit.

## Branch lifecycle and review

Branches have a review status and an acceptance decision. A generated answer is available for inspection. Accepting it makes it approved context for the next main-chat question. Continuing an accepted branch clears the accepted decision so the new content can be reviewed before it is treated as accepted. Rejecting a branch records that it should not be treated as an endorsed answer.

The reviewer checks response behavior against the user prompt and supplied context. Its “Pass” result means the advisory check did not request a revision; it does not certify factual accuracy.

## See logs debugger

The **See logs** control opens a browser-session debugger. While open, new interactions record the browser request method, path, body, and response status, along with backend model messages, parameters, responses, and branch context references returned by the API. The panel retains only the latest 20 recorded interactions and can be cleared. It is not a persistent observability service and does not include provider credentials. Prompt and response text can contain conversation content, so treat the panel as private debugging information.

## Data model

The current SQLAlchemy models include:

- `Conversation`, `Message`, and `AnswerVersion` for chat history and answer versions.
- `Passage` for selectable parts of assistant answers.
- `Branch`, `BranchSelection`, and `BranchMessage` for selected text and branch exchanges.
- `MessageContextSource` for branch messages included in a later main-chat question, including status at the time of use.
- `AnswerVersionSource` and `MergeDraft` for merge-related persistence/API structures. The current interface's acceptance flow is context carry-forward; it does not require an answer merge.

## Local setup

See the repository [README](../README.md) for prerequisites, environment settings, and commands to run the web app and API. Copy `.env.example` to `.env` and set `GROQ_API_KEY` to use Groq. Keep `.env` private; it is excluded from Git. With an empty key, the API uses mock mode in `auto` mode.

The API health endpoint is `http://localhost:8000/api/health`. The web app runs at `http://localhost:3000` with the documented development command.

## Known limits and future work

- There is no context token budget, history summarization, or truncation strategy.
- Branch review does not verify factual accuracy.
- The model may receive context without using it correctly; graph edges document inclusion, not semantic influence.
- There is no retrieval-augmented generation over user documents, user authentication, collaboration, hosted deployment, or persistent tracing service.
- Merge-related database structures and API routes exist, but accepting a branch is not a merge and the current primary workflow does not depend on merging.
- Provider limits, availability, latency, and output quality depend on the Groq account and selected model.

Potential follow-up work includes bounded context management, clearer context selection policies for very long chats, and evaluation of branch continuity and answer quality. These are future improvements, not current capabilities.

## Historical proposal

The file `Initial Product Proposal - Historical.docx` preserves the earlier proposal that informed the project. It contains concepts that were not implemented or were changed during development. This implementation guide and the README describe the current application and should be used for its actual behavior and technology choices.
