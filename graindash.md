# GrainDash — Web Dashboard Specification

> Obsidian-inspired knowledge browser for Grain PKOS. (Updated 2026-05-27: Obsidian/Notion sync removed — this custom web dashboard is the primary UI.)
> Separate SvelteKit (or Next.js) repo. Communicates with Grain backend via REST API.
> Auth via Telegram Login Widget — no email/password.

---

## Architecture

```
Browser ──→ GrainDash (SvelteKit/Next.js) ──→ Grain Backend API ──→ Supabase
                     │                                │
                     │                               service_role key (bypasses RLS)
                     │                                │
                  session_token                     Trusted backend
               (Authorization: Bearer)
```

- Dashboard never calls Supabase directly. All requests go through the backend API.
- Backend uses `service_role` key (bypasses RLS). User isolation is enforced by `get_current_user` → `user_id` on every query.
- Dashboard doesn't need to know about `user_id` — the backend extracts it from the session JWT.

---

## Auth Flow

### Login Page (`/login`)

- Single "Login with Telegram" button
- Uses [Telegram Login Widget](https://core.telegram.org/widgets/login):
  ```html
  <script async src="https://telegram.org/js/telegram-widget.js?22"
          data-telegram-login="<BOT_USERNAME>"
          data-size="large"
          data-onauth="onTelegramAuth(user)"
          data-request-access="write"></script>
  ```
- On callback, POST to `https://grain-backend.com/auth/telegram-login` with the user object
- Store `session_token` in `localStorage` or `HttpOnly` cookie
- Redirect to `/dashboard`

### Auth Middleware (frontend)

Every protected route:
1. Reads `session_token` from storage
2. Sends `Authorization: Bearer <token>` on all API calls
3. On 401 → redirect to `/login`
4. On first load, call `GET /auth/me` to validate session and get user display name

---

## Backend API Endpoints — Complete Audit

### Already Built & Dashboard-Ready

| Method | Path | Purpose | Auth |
|--------|------|---------|------|
| `POST` | `/auth/telegram-login` | Login via Telegram widget | No (signed callback) |
| `GET` | `/auth/me` | Current user info | `get_current_user` (session JWT) |
| `GET` | `/health` | Health check | No |

### Already Built — NEEDS AUTH FIX for Dashboard

These endpoints exist but have auth gaps that would leak data across users if the dashboard calls them.

| Method | Path | Auth Gap | Fix Required |
|--------|------|----------|--------------|
| `POST` | `/search` | Uses `_resolve_user_id` (X-User-Id header). Dashboard sends session JWT, not X-User-Id. | Add `get_current_user` as alternative dependency. |
| `GET` | `/related-notes/{note_id}` | **No user scoping.** `get_note_by_id()` has no `user_id` filter. Anyone can fetch any note by UUID. | Add `get_current_user`. Scope all note lookups to `user_id`. |
| `GET` | `/facets` | **No user scoping.** Queries ALL notes across all users. | Add `get_current_user`, filter by `user_id`. |
| `POST` | `/ingest-note` | Uses `_resolve_user_id` (X-User-Id header). | Add `get_current_user` as alternative. |

**Underlying data leak:** `get_note_by_id(note_id)` in `app/db/queries.py` has no `user_id` filter. Must be fixed before any dashboard note-detail endpoint goes live.

### Not Yet Built — New Endpoints Required (11 total)

| Method | Path | Purpose | Auth Dependency |
|--------|------|---------|-----------------|
| `GET` | `/notes` | List notes (paginated, filterable) | `get_current_user` |
| `GET` | `/notes/{id}` | Single note detail | `get_current_user` |
| `GET` | `/notes/{id}/entities` | Entities linked to a note | `get_current_user` |
| `GET` | `/topics` | All topics for user, with note count | `get_current_user` |
| `GET` | `/topics/{id}/notes` | Notes under a topic | `get_current_user` |
| `GET` | `/entities` | All entities for user | `get_current_user` |
| `GET` | `/entities/{id}` | Entity detail + linked notes | `get_current_user` |
| `PUT` | `/notes/{id}` | Update note fields (title, topic_id, facets) | `get_current_user` |
| `DELETE` | `/notes/{id}` | Delete note | `get_current_user` |
| `GET` | `/stats` | Dashboard stats (note count, topic count, entity count, last capture time) | `get_current_user` |
| `GET` | `/graph-data` | All nodes + edges for force-directed graph | `get_current_user` |

Query params for `GET /notes`:
`?topic_id=UUID&entity_id=UUID&facet_key=str&facet_value=str&search=str&sort=created_at|title&order=desc|asc&page=1&per_page=20`

Response: `{ notes: NoteOutput[], total: int, page: int, per_page: int }`

Response for `GET /stats`:
`{ note_count: int, topic_count: int, entity_count: int, last_capture_at: ISO8601 | null }`

Response for `GET /graph-data`:
`{ nodes: [{ id: UUID, title: str, topic_name: str, topic_id: UUID }], links: [{ source: UUID, target: UUID, relation_type: str, score: float }] }`

All data scoped by `user_id` extracted from session JWT.

---

## Backend Prerequisites — Fix Before SvelteKit

These fixes must ship before or alongside the dashboard. Implement at step 1 of the build order:

1. **Add `user_id` param to `get_note_by_id()`** in `app/db/queries.py` — filter by user when provided.
2. **Fix `POST /search`** — accept `get_current_user` alongside `_resolve_user_id`.
3. **Fix `GET /related-notes/{note_id}`** — add `get_current_user`, scope all note lookups.
4. **Fix `GET /facets`** — add `get_current_user`, filter by `user_id`.
5. **Fix `POST /ingest-note`** — accept `get_current_user` as alt to `_resolve_user_id`.
6. **Add all 11 new endpoints** listed above.

---

## Data Schema → UI Mapping

### notes Table → Knowledge Card

```
notes table:
  id UUID (PK)
  raw_text TEXT
  summary TEXT           → Knowledge Card body
  title TEXT             → Card title
  source_url TEXT        → Link button
  source_type TEXT       → Badge ("telegram_text", "link", "pdf", etc.)
  personal_insight TEXT  → Italic quote block
  topic_id UUID (FK)    → Topic tag / link
  user_id UUID (FK)
  embedding vector(3072) → Not shown in UI
  facets JSONB           → Tag chips grouped by key
  created_at TIMESTAMPTZ → Date display

**Note:** "Status" (Established/Hypothesis/Debate/Speculative) is stored **inline in the summary text** as `**Status:** Established`. The frontend must parse it from the summary on the Knowledge Card. There is no separate `status` column.
```

**UI: Knowledge Card** (Obsidian-style)
```
┌─────────────────────────────────────────────────┐
│ [source_type badge] [status tag]                │
│                                                  │
│ # Topic: TopicName            [🆔 aB3kZ9]       │
│ ─────────────────────────────────────────────── │
│ 🔑 Core: The core claim or thesis               │
│                                                  │
│ The summary text... runs freely here...          │
│ Can be multiple paragraphs from the raw LLM      │
│ output.                                          │
│                                                  │
│ Facts:                                           │
│ • First fact from the Facts section              │
│ • Second fact                                    │
│ • Third fact                                     │
│                                                  │
│ Why this matters: Personal insight text          │
│                                                  │
│ Tags: [Location:Nova Scotia] [Subject:Geology]   │
│       [Category:Science]                         │
│                                                  │
│ 🔗 Source URL                        📅 2026-05-27│
│ ─────────────────────────────────────────────── │
│ [Edit] [Move] [Delete]    [View Graph] [Backlinks]│
└─────────────────────────────────────────────────┘
```

### topics Table → Topic Tree / Tag

```
topics table:
  id UUID (PK)
  name TEXT              → Display name
  parent_id UUID (FK)    → Parent topic (for hierarchy)
  description TEXT       → Tooltip / hover detail
  user_id UUID (FK)
  embedding vector(3072) → Not shown
```

### entities Table → Entity Browser

```
entities table:
  id UUID (PK)
  name TEXT              → Display name
  type TEXT              → "concept" | "technology" | "project" | "person"
  user_id UUID (FK)
  embedding vector(3072) → Not shown
```

**note_entities** junction table → Links notes to entities on the note detail page.

### relations Table → Graph Edges

```
relations table:
  id UUID (PK)
  source_note_id UUID (FK)  → Source node
  target_note_id UUID (FK)  → Target node
  relation_type TEXT         → "related_to" | "extends" | "contradicts" | "depends_on"
  score FLOAT                → Edge weight / confidence
  user_id UUID (FK)
```

### agent_state Table → Not shown in UI (Telegram-only)

---

## Page Map

### 1. Landing Page (`/`)

**Purpose:** Marketing / brand page. What is Grain?

**Content:**
- Hero: Logo + tagline "Your Personal Knowledge Operating System"
- 3 feature cards with icons: "Capture Anything", "AI Organizes Automatically", "Explore Your Knowledge Graph"
- "Login with Telegram" button (same as `/login`)
- Footer: minimal, no links needed

**Style:** Clean, centered, dark theme (matching Obsidian's aesthetic). Single-page. No scrolling required — all content above the fold.

### 2. Login Page (`/login`)

**Purpose:** Authenticate via Telegram.

**Content:**
- Centered card
- Grain logo + "Welcome to Grain"
- "Login with Telegram" widget button
- On success → redirect to `/dashboard`

**Style:** Minimal. Dark card on dark background. Telegram button is the only interactive element.

### 3. Dashboard / Home (`/dashboard`)

**Purpose:** Entry point after login. Quick overview.

**Content:**
- **Top bar:** Logo + search bar + user avatar/name
- **Stats row:** "X Notes · Y Topics · Z Entities · Last capture: 2h ago"
- **Quick capture box:** Text area with "Send" button → calls `POST /ingest-note`
- **Recent notes feed:** Last 10 notes, listed as compact cards (title + topic + date + first 100 chars)
- **Top topics widget:** List of topics sorted by note count
- **Sidebar:** (optional) Navigation links

**Style:** Two-column layout (sidebar + main). Dark theme. Cards have subtle borders.

### 4. Browse by Topic (`/topics`)

**Purpose:** See all topics as a navigable tree/list.

**Content:**
- **Topic tree:** Left panel — hierarchical tree of topics (uses `parent_id`). Expand/collapse.
- **Topic detail:** Right panel — when a topic is selected:
  - Topic name + description
  - Note count
  - List of notes in this topic (compact card format)
  - Option to edit topic name, set parent
- **Search:** Filter topics by name

**Style:** Split-panel (inspired by Obsidian's folder pane). Tree nodes with chevrons on left, notes listed on right.

### 5. Note Detail (`/notes/{id}`)

**Purpose:** Full Knowledge Card view + rich interactions.

**Content:**
- Full Knowledge Card (as described above)
- **Linked entities section:** Tags/badges for each entity linked to this note, grouped by type
- **Backlinks panel:** Other notes that reference this note (from `relations` table where this note is the target) with Obsidian-style `[[wikilinks]]` in note summaries
- **Graph preview:** Small inline force-directed graph showing this note + its 1-hop neighbors
- **Inline edit buttons:** Edit title, edit summary, add fact, change status, move topic
- **Delete button:** With confirmation dialog

**Style:** Centered single-column layout. Knowledge Card is the hero. Graph is embedded as a small interactive canvas below the card. Backlinks listed as a sidebar or bottom section.

### 6. Semantic Search (`/search?q=...`)

**Purpose:** Full search experience (vs the quick search bar).

**Content:**
- **Search bar:** Large, always visible
- **Results list:** Cards ranked by similarity score, with similarity indicator bar
- **Filters sidebar:**
  - By topic (dropdown/checkboxes)
  - By facet key+value
  - By source type
  - By date range
  - By status (Established, Hypothesis, etc.)
- **Result card format:** Topic tag, title, first 200 chars of summary, source URL, similarity score, date

**Style:** Two-column (filters + results). Each result is a compact card with a faint similarity bar on the left edge.

### 7. Knowledge Graph Explorer (`/graph`)

**Purpose:** Interactive full-screen force-directed graph view.

**Content:**
- **Full-screen canvas** using D3.js force simulation (or vis.js / cytoscape.js)
- **Nodes:** Each note is a node. Color-coded by topic. Size by importance/connection count.
- **Edges:** Lines between nodes. Color-coded by relation type. Thickness by score.
- **Interaction:**
  - Click node → show note preview tooltip (title + 50 chars)
  - Double-click → navigate to `/notes/{id}`
  - Drag nodes → reposition
  - Pin nodes → right-click to pin/unpin
  - Zoom in/out
- **Controls overlay:**
  - Search box to highlight nodes by text
  - Filter by topic (checkboxes)
  - Filter by relation type
  - "Show only my notes" toggle
- **Legend:** Topic colors, edge types
- **Minimap:** Small overview in corner

**Style:** Full dark canvas. Nodes are subtle circles or rounded rectangles. Edges are faint lines. Only highlighted/selected nodes are fully opaque.

**Data source:** New `GET /graph-data` backend endpoint returns:
```json
{
  "nodes": [
    {"id": "uuid", "title": "...", "topic_name": "...", "note_count": 3}
  ],
  "links": [
    {"source": "uuid", "target": "uuid", "relation_type": "extends", "score": 0.85}
  ]
}
```

### 8. Entity Browser (`/entities`)

**Purpose:** Browse all extracted entities grouped by type.

**Content:**
- **Type tabs:** "All · Concepts · Technologies · Projects · People"
- **Entity cards:** Each card shows entity name, type badge, count of linked notes
- **Click entity →** `/entities/{id}` with:
  - Entity name + type
  - List of notes that mention this entity (with similarity score or context snippet)
  - Option to rename entity

**Style:** Grid of cards grouped by type. Each card has a subtle border.

### 9. Facet Browser (`/facets`)

**Purpose:** Browse notes by structured facets (location, subject, etc.).

**Content:**
- **Facet key sidebar:** List of all facet keys (from `GET /facets`)
- **Click a key →** show all values for that key with note counts
- **Click a value →** show notes with that facet value
- Each note card shows which facet key:value matched

**Style:** Tree-like sidebar + results panel. Similar to topic browsing.

### 10. Settings (`/settings`)

**Purpose:** User preferences.

**Content:**
- Profile info (from Telegram — read-only)
- Theme toggle (dark/light — currently dark only, prepare for light theme support)
- Notification preferences (future)
- Logout button

---

## Visual Style Guide

### Theme

- **Base:** Dark mode (Obsidian-inspired). Dark surface `#1e1e1e`, darker sidebar `#181818`, subtle borders `#2e2e2e`.
- **Font:** System font stack (`-apple-system, BlinkMacSystemFont, "Segoe UI", "Inter", sans-serif`) for UI. Monospace (`"JetBrains Mono", "Fira Code", monospace`) for code/pre blocks.
- **Accent:** Grain uses a warm accent. Suggested: `#d4a574` (warm amber/gold) or `#7ecba1` (sage green). Pick one and use consistently.

### Color Palette

```
Background:       #121212 (page)
Surface:          #1e1e1e (cards, panels)
Surface-hover:    #2a2a2a
Border:           #2e2e2e
Text-primary:     #e0e0e0
Text-secondary:   #9e9e9e
Text-muted:       #666666
Accent:           #d4a574 (amber/gold)
Accent-hover:     #e8b88a
Danger:           #e5534b
Success:          #3fb950
Warning:          #d29922
Info:             #58a6ff
```

### Typography

- Headings: `font-weight: 600`
- Body: `font-weight: 400`, `line-height: 1.6`
- Knowledge Card summary: `font-size: 0.95rem`, `line-height: 1.75`
- Small text (dates, tags): `font-size: 0.8rem`, `color: text-muted`
- Code/inline code: `font-family: monospace`, `background: #2e2e2e`, `padding: 0.1em 0.3em`, `border-radius: 3px`

### Components

**Note Card (compact — for lists):**
```
┌─────────────────────────────────────────────────┐
│ [Topic Tag] [Status Badge]        📅 2026-05-27 │
│ Title text truncated to one line...              │
│ Summary preview — first 120 chars of the core   │
│ claim or facts...                                │
└─────────────────────────────────────────────────┘
```

**Note Card (full — Knowledge Card):** As described above.

**Topic Tree Node:**
```
▶ Topic Name (12)         ← chevron + name + note count
  ▶ Sub-topic (3)
```

**Graph Node:** Small filled circle, radius proportional to connection count. Color by topic. Hover → glow + tooltip.

**Search Bar:** Rounded input with search icon. On focus → dropdown with recent searches. On type → debounced search (300ms) showing inline results or navigating to `/search`.

**User Avatar:** Telegram profile photo (or fallback: first letter of display name in a circle).

**Tags/Chips:** Small rounded pills. Topic tags have accent color. Facet tags have info color. Entity tags have varied colors by type.

---

## Technical Notes

### Frontend Framework

Recommend **SvelteKit** (lightweight, fast, good DX for this scale) or **Next.js** (if you want more ecosystem). Either works.

### Caching Strategy

- `GET /topics` — cache 5 minutes (infrequently changes)
- `GET /notes` — cache 30 seconds (new notes come in frequently via Telegram)
- `POST /search` — no cache
- `GET /facets` — cache 5 minutes
- `GET /graph-data` — cache 30 seconds (user might add notes while browsing)
- `GET /auth/me` — cache until page reload

### API Client Pattern

Create a shared API client:

```typescript
// api/client.ts
const API_BASE = 'https://grain-backend.com';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const token = localStorage.getItem('session_token');
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options?.headers,
    },
  });
  if (res.status === 401) {
    localStorage.removeItem('session_token');
    window.location.href = '/login';
    throw new Error('Unauthorized');
  }
  return res.json();
}

export const api = {
  login: (data: any) => request<LoginResponse>('/auth/telegram-login', { method: 'POST', body: JSON.stringify(data) }),
  me: () => request<UserInfo>('/auth/me'),
  search: (query: string, limit = 10) => request<SearchResult[]>('/search', { method: 'POST', body: JSON.stringify({ query, limit }) }),
  notes: (params?: NoteListParams) => request<NoteListResponse>(`/notes?${new URLSearchParams(params)}`),
  note: (id: string) => request<NoteDetail>(`/notes/${id}`),
  relatedNotes: (id: string) => request<RelatedNotesResponse>(`/related-notes/${id}`),
  topics: () => request<Topic[]>('/topics'),
  facets: () => request<Record<string, string[]>>('/facets'),
  graphData: () => request<GraphData>('/graph-data'),
};
```

### Routing Structure

```
/            → LandingPage
/login       → LoginPage
/dashboard   → DashboardPage (protected)
/topics      → TopicsPage (protected)
/topics/{id} → TopicDetailPage (protected)
/notes/{id}  → NoteDetailPage (protected)
/search      → SearchPage (protected)
/graph       → GraphPage (protected)
/entities    → EntitiesPage (protected)
/entities/{id} → EntityDetailPage (protected)
/facets      → FacetsPage (protected)
/settings    → SettingsPage (protected)
```

### Backend Endpoints to Add

These are needed for the dashboard and not yet built in the FastAPI backend:

1. **`GET /notes`** — Paginated note listing with filters:
   - Query params: `?topic_id=&entity_id=&facet_key=&facet_value=&search=&status=&sort=created_at&order=desc&page=1&per_page=20`
   - Response: `{ notes: NoteOutput[], total: int, page: int, per_page: int }`

2. **`GET /notes/{id}`** — Single note detail (use `get_current_user` for user scoping)

3. **`GET /topics`** — All topics for user, with note count:
   - Response: `[{ id, name, parent_id, description, note_count }]`

4. **`GET /topics/{id}/notes`** — Notes under a specific topic

5. **`GET /graph-data`** — All nodes + edges for the graph visualization:
   - Response: `{ nodes: [{ id, title, topic_name, entity_count }], links: [{ source, target, relation_type, score }] }`

6. **`PUT /notes/{id}`** — Update note fields (title, summary, topic_id, status, facets)

7. **`DELETE /notes/{id}`** — Delete note

8. **`GET /stats`** — Dashboard stats: `{ note_count, topic_count, entity_count, last_note_at }`

These should all use `get_current_user` dependency to scope data to the authenticated user.

---

## Order of Implementation

1. **Backend security fixes** — `get_note_by_id` user scoping, auth on `/search`, `/facets`, `/related-notes`, `/ingest-note`
2. **Backend new endpoints** — `GET /notes`, `GET /notes/{id}`, `GET /topics`, `GET /graph-data`, `PUT /notes/{id}`, `DELETE /notes/{id}`, `GET /entities`, `GET /stats`, etc.
3. SvelteKit project setup + API client + auth middleware
4. Login page + Telegram widget integration
5. Dashboard / home page with stats + recent notes
6. Topic browser (tree + notes listing)
7. Note detail page (Knowledge Card)
8. Search page
9. Knowledge Graph page (D3.js force graph)
10. Entity browser
11. Facet browser
12. Settings page
13. Polish: loading states, error states, empty states, animations
