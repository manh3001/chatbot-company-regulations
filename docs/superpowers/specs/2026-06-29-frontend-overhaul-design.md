# Frontend Overhaul — Design Spec

Date: 2026-06-29
Status: Approved
Topic: Modernize the chatbot web UI (visual redesign + features), staying vanilla.

## Goal

Overhaul the static web front end (`static/index.html`, `static/style.css`,
`static/script.js`) to look modern and professional, and to surface
capabilities the backend already supports but the current UI ignores. No build
step, no framework, no new backend changes.

## Constraints

- **Vanilla only.** Plain HTML/CSS/JS served from `/static`. No bundler, no
  node_modules, no CDN dependencies. Self-contained.
- **No backend changes.** Every feature uses endpoints that already exist:
  `POST /ask_stream`, `GET /history/{session_id}`. The request/response
  contract is unchanged.
- **XSS-safe.** Model output is escaped before any markdown transformation.
- Keep the JS organized into small, single-purpose functions.

## Architecture

Three static files, same as today:

- `static/index.html` — app shell markup.
- `static/style.css` — theming via CSS custom properties (light + dark palettes).
- `static/script.js` — organized into focused functions: session management,
  API calls, rendering, markdown, citation parsing, theme, clipboard.

The session id continues to live in `localStorage` under `chat_session_id`,
exactly as today.

## Visual redesign

- **App-shell layout** replacing the fixed 400px card:
  - Header bar: title, dark-mode toggle, "New chat" button.
  - Flexible message area that fills the viewport and scrolls.
  - Sticky composer pinned to the bottom.
- **Responsive:** full width on mobile; centered max-width column on desktop.
- **Theming:** `:root` light palette and `[data-theme="dark"]` dark palette
  driven by CSS custom properties. The toggle flips `data-theme` on the
  `<html>` element. Choice persisted in `localStorage`; default follows the OS
  `prefers-color-scheme`.
- **Polish:** modern typography, message bubbles with role labels/avatars,
  subtle shadows, smooth scrolling, visible focus states.

## Features (all client-side)

1. **Load history on reload** — on page load, `GET /history/{sessionId}` and
   render each turn (user message, bot answer, timestamp). When empty, show a
   friendly welcome/empty state. A failed fetch fails silently to the empty
   state and never blocks the app.
2. **Render markdown** — a small self-contained renderer (~40 lines) supporting
   headings, bold, italic, unordered/ordered lists, inline code, and line
   breaks. HTML is escaped **first**, then markdown transforms are applied, so
   untrusted model output cannot inject markup.
3. **Dark mode toggle** — see Theming above.
4. **New chat** — generates a fresh `sessionId`, clears the visible
   conversation, and persists the new id. The previous conversation remains on
   the server under its old id.
5. **Copy-to-clipboard** — a copy button on each bot answer using
   `navigator.clipboard`, with a brief "Copied" confirmation. Clipboard
   failure shows a fallback message.
6. **Timestamps** — shown under each message. Restored turns use the timestamp
   from the history payload; live turns use client time.
7. **Typing indicator** — animated dots in the bot bubble until the first
   streamed token arrives, then replaced by streamed text.
8. **Auto-resizing input** — a `<textarea>` that grows with content, capped at
   a max height. Enter sends; Shift+Enter inserts a newline.
9. **Source-citation display** — the backend prompt instructs the model to end
   answers with a line `Nguồn: <section>`. Parse that trailing line out of the
   answer and render it as a styled source chip beneath the bubble, separate
   from the answer body. When the model returns the no-info sentence
   ("Không có thông tin trong nội quy."), there is no `Nguồn:` line and no chip
   is shown.

## Data flow

Send → `POST /ask_stream` with `{question, session_id}` → show typing indicator
→ stream tokens into the bot bubble → on completion:

1. Split the trailing `Nguồn: …` line off the accumulated answer.
2. Render the answer body as escaped markdown.
3. Render the citation chip (if present), copy button, and timestamp.

Empty stream → show the existing "no suitable answer" fallback message.

## Error handling

- Keep the try/catch around the `/ask_stream` fetch; connection errors render
  in the bot bubble ("Lỗi kết nối đến server.").
- History fetch failure → silent fallback to empty state.
- Clipboard failure → fallback confirmation message.

## Testing

- Backend: existing pytest suite is unaffected (no backend changes).
- Frontend: two pure functions are unit-tested with a small standalone
  harness — the markdown renderer and the `Nguồn:` citation parser. Both are
  pure (string in, string/struct out) and the highest-value logic to cover.
- Manual verification by running the app and exercising each feature.

## Out of scope

- Vector search / retrieval changes.
- New backend endpoints or response-shape changes.
- Frameworks, build tooling, or external runtime dependencies.
