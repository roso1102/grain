# 📋 Grain — Action Plan

> Execution roadmap for building Grain, the Personal Knowledge Operating System.
> Tasks are numbered as `Phase.Task` (e.g., `1.0`, `1.1`).
> Agents/developers mark completion with `[x]` and the date.

---

## Legend

```
[ ] = Not started
[~] = In progress
[x] = Complete
```

---

## 🏁 MVP — Core Ingestion Pipeline

> **Goal:** Prove the end-to-end pipeline works.
> Text-in → LLM understands → Supabase stores → Bot replies.
> **No vectors, no Notion, no graph yet. Just the spine.**

---

### 0.0 — Project Setup

- [x] **0.1** — Initialize Python project, create `app/` folder structure as defined in README  
  `Completed: 2026-05-25`

- [x] **0.2** — Create `.env.example` with all required keys:  
  `SUPABASE_URL`, `SUPABASE_KEY`, `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`  
  `Completed: 2026-05-25`

- [x] **0.3** — Create `requirements.txt` with initial dependencies:  
  `fastapi`, `uvicorn`, `pydantic`, `httpx`, `supabase-py`, `python-telegram-bot`, `google-generativeai`  
  `Completed: 2026-05-25`

- [x] **0.4** — Setup `app/core/config.py` to load all env variables via Pydantic `BaseSettings`  
  `Completed: 2026-05-25`

- [x] **0.5** — Setup `app/core/logger.py` with structured logging  
  `Completed: 2026-05-25`

- [x] **0.6** — Create `app/main.py` with a barebones FastAPI app and `/health` endpoint  
  `Completed: 2026-05-25`

- [x] **0.7** — Verify server starts: `uvicorn app.main:app --reload`  
  `Completed: 2026-05-25`

---

### 1.0 — Supabase Setup (MVP Schema)

- [x] **1.1** — Create Supabase project, get URL and anon key  
  `Completed: 2026-05-25`

- [x] **1.2** — Write `migrations/001_init.sql`:  
  Create `topics` table (`id`, `name`, `parent_id`, `description`, `notion_page_id`)  
  `Completed: 2026-05-25`

- [x] **1.3** — Write `migrations/001_init.sql` (continued):  
  Create `notes` table (`id`, `raw_text`, `summary`, `source_url`, `source_type`, `personal_insight`, `topic_id`, `created_at`)  
  `Completed: 2026-05-25`

- [x] **1.4** — Run migrations on Supabase SQL editor, verify tables exist  
  `Completed: 2026-05-25`

- [x] **1.5** — Setup `app/db/supabase.py` — initialize and export Supabase client  
  `Completed: 2026-05-25`

- [x] **1.6** — Write basic CRUD helpers in `app/db/queries.py`:  
  `insert_note()`, `get_note_by_id()`, `get_all_topics()`, `insert_topic()`  
  `Completed: 2026-05-25`

---

### 2.0 — Telegram Bot Setup

- [x] **2.1** — Create Telegram bot via BotFather, save token to `.env`  
  `Completed: 2026-05-25`

- [x] **2.2** — Write `app/integrations/telegram.py`:  
  Handle incoming messages, extract text/photo/document/link  
  `Completed: 2026-05-25`

- [x] **2.3** — Register `/webhook` endpoint in FastAPI (`app/api/ingest.py`)  
  `Completed: 2026-05-25`

- [x] **2.4** — Set Telegram webhook URL to your FastAPI server  
  `Completed: 2026-05-25 (Deferred to Phase 9.0 deployment; local testing complete)`

- [x] **2.5** — Test: send a message to the bot, confirm FastAPI receives it  
  `Completed: 2026-05-25 (Tested successfully via local mock webhook script)`

---

### 3.0 — LLM Integration (Understanding Engine, MVP)

- [x] **3.1** — Setup `app/integrations/gemini.py` — Gemini Flash API client with a reusable `call_llm(prompt)` function  
  `Completed: 2026-05-25`

- [x] **3.2** — Write `app/services/summarizer.py`:  
  Takes raw text, returns 2–3 sentence summary via LLM  
  `Completed: 2026-05-25`

- [x] **3.3** — Write `app/services/classifier.py`:  
  Takes raw text + summary, returns a topic name (free-form string)  
  `Completed: 2026-05-25`

- [x] **3.4** — Write `app/services/intent_parser.py`:  
  Detect if the user mentioned a routing instruction ("save to X") or a personal annotation  
  Extract and return: `{ "route_hint": str | None, "personal_insight": str | None }`  
  `Completed: 2026-05-25`

- [x] **3.5** — Write `app/services/link_extractor.py`:  
  Detect URLs in message, fetch page with `httpx`, extract main text using `BeautifulSoup4`  
  Return: `{ "url": str, "content": str, "title": str }`  
  `Completed: 2026-05-25`

- [x] **3.6** — Combine into a unified `understand(raw_input)` function that handles both plain text and links  
  `Completed: 2026-05-25`

---

### 4.0 — Ingestion Pipeline (MVP End-to-End)

- [x] **4.1** — Write `app/api/ingest.py`:  
  `POST /ingest-note` → receives raw message from Telegram webhook  
  `Completed: 2026-05-25`

- [x] **4.2** — In the ingestion handler, call the full pipeline:  
  `parse → link_extractor → intent_parser → summarize → classify`  
  `Completed: 2026-05-25`

- [x] **4.3** — Write Pydantic model `NoteInput` in `app/models/note.py`  
  `Completed: 2026-05-25`

- [x] **4.4** — Save processed note to Supabase `notes` table via `insert_note()`  
  `Completed: 2026-05-25`

- [x] **4.5** — Have the bot reply with a confirmation: topic + 1-line summary  
  `Completed: 2026-05-25`

- [x] **4.6** — Full end-to-end test:  
  Send Telegram message → bot replies with topic + summary → check Supabase row  
  `Completed: 2026-05-25`

---

## 🔵 Phase 1 — Semantic Topic Snapping

> **Goal:** Prevent category duplication. New topics auto-merge with similar existing ones.

- [x] **P1.1** — Add `pgvector` extension to Supabase. Write `migrations/002_vectors.sql`:  
  Add `embedding vector(384)` column to `notes` and `topics`  
  `Completed: 2026-05-25`

- [x] **P1.2** — Add `sentence-transformers` to `requirements.txt`  
  `Completed: 2026-05-25`

- [x] **P1.3** — Write `app/services/embedder.py`:  
  Load `BAAI/bge-small-en-v1.5` model once at startup, expose `embed(text) → List[float]`  
  `Completed: 2026-05-25`

- [x] **P1.4** — Write `app/services/topic_snapper.py`:  
  Embed proposed topic name → cosine similarity against all existing topic embeddings in Supabase →  
  If max similarity > 0.90: return existing topic ID  
  Else: insert new topic with embedding, return new ID  
  `Completed: 2026-05-25`

- [x] **P1.5** — Integrate `topic_snapper` into the ingestion pipeline (replace the raw `classify` step)  
  `Completed: 2026-05-25`

- [x] **P1.6** — Also embed the note summary and save the vector in `notes.embedding`  
  `Completed: 2026-05-25`

- [x] **P1.7** — Test: send similar-topic notes, verify they snap to the same topic in Supabase  
  `Completed: 2026-05-25`

---

## 🔵 Phase 2 — Semantic Search

> **Goal:** Be able to ask "What do I know about X?" via Telegram.

- [x] **P2.1** — Write `app/api/search.py`: `POST /search` endpoint, accepts a natural language query  
  `Completed: 2026-05-25`

- [x] **P2.2** — Write `app/services/retrieval_engine.py`:  
  Embed query → pgvector ANN search → return top-k most similar notes  
  `Completed: 2026-05-25`

- [x] **P2.3** — Add a Telegram command `/ask [query]` that calls the search endpoint  
  `Completed: 2026-05-25`

- [x] **P2.4** — Write `app/utils/ranking.py`: rank results by similarity + importance_score  
  `Completed: 2026-05-25`

- [x] **P2.5** — Format search results for Telegram: return top 3 summaries with topic labels + source URLs  
  `Completed: 2026-05-25`

- [x] **P2.6** — Test: ask about a topic you've previously saved, verify relevant notes surface  
  `Completed: 2026-05-25`

---

## 🔵 Phase 3 — Obsidian Export Engine (replaces Notion)

> **Goal:** See your knowledge organized visually in Obsidian with graph view, backlinks, and tags.

- [x] **P3.0** — Remove Notion: delete `notion.py`, `notion_sync.py`, update config, models, queries; add drop-column migration  
  `Completed: 2026-05-26`

- [x] **P3.1** — Write `app/services/obsidian_sync.py`:
  After every note save, write a `.md` file to the Obsidian vault with:
  - YAML frontmatter: `grain_id` (6-char shortcode), `topic`, `tags[]` (status + facets), `entities[]`, `created`
  - Body: Knowledge Card with `[[wikilinks]]` (from `links_to` and entities)
  - File naming: `{Topic} - {Title 40chars}.md`  
  `Completed: 2026-05-26`

- [x] **P3.2** — Write index generators in `obsidian_sync.py`:
  - `_MOC.md` — Topic-grouped Table of Contents
  - `_entities.md` — All entities grouped by type
  - `_facets.md` — All facet values grouped by key  
  `Completed: 2026-05-26`

- [x] **P3.3** — Add Telegram edit commands in `app/api/ingest.py`:
  - `/note <code>` — show note details
  - `/edit <code> <text>` — full re-process via LLM
  - `/fact <code> <fact>` — append fact (no LLM)
  - `/retitle <code> <title>` — rename
  - `/delete <code>` — remove
  - Shortcodes: 6-char base62 (e.g. `aB3kZ9`), shown in capture reply  
  `Completed: 2026-05-26`

**Setup requirements (out of scope for code):**
- Install Obsidian on desktop/phone
- Point Obsidian vault to `OBSIDIAN_VAULT_PATH`
- Install Syncthing on all devices to sync `.md` files
- Edit notes via Telegram commands — Obsidian is read-only display

---

## 🔵 Phase 4 — Entity Engine

> **Goal:** Extract structured knowledge nodes (concepts, technologies, projects).

- [x] **P4.1** — Write `migrations/003_graph.sql`:  
  Create `entities`, `note_entities`, `relations` tables  
  `Completed: 2026-05-25`

- [x] **P4.2** — Write `app/services/entity_extractor.py`:  
  LLM prompt: extract key concepts/technologies/projects from the summary  
  Return: `[{"name": "memristor", "type": "technology"}, ...]`  
  `Completed: 2026-05-25`

- [x] **P4.3** — Write `app/db/queries.py` additions:  
  `upsert_entity()`, `link_note_to_entity()`  
  `Completed: 2026-05-25`

- [x] **P4.4** — Integrate entity extraction into the ingestion pipeline  
  `Completed: 2026-05-25`

- [x] **P4.5** — Embed entity names and store in `entities.embedding`  
  `Completed: 2026-05-25`

- [x] **P4.6** — Add entity overlap to retrieval engine: boost notes that share entities with the query  
  `Completed: 2026-05-25`

---

## 🔵 Phase 5 — Memory Graph

> **Goal:** Connect notes to each other. Build a relational knowledge web.

- [x] **P5.1** — Write `app/services/relation_engine.py`:  
  After a note is saved: compare its embedding against top-k existing notes →  
  For pairs with similarity > 0.75: use LLM to infer the relation type (`extends`, `related_to`, `contradicts`, `depends_on`)  
  Insert into `relations` table  
  `Completed: 2026-05-25`

- [x] **P5.2** — Write `app/api/graph.py`: `GET /related-notes/{id}` endpoint  
  `Completed: 2026-05-25`

- [x] **P5.3** — Add graph expansion to `retrieval_engine.py`:  
  After vector search, traverse `relations` to pull in 1-hop connected notes  
  `Completed: 2026-05-25`

- [x] **P5.4** — Add a Telegram command `/related [note-id or topic]` to surface connections  
  `Completed: 2026-05-25`

- [x] **P5.5** — Test: save two related notes on different days, verify a relation edge is created  
  `Completed: 2026-05-25`

---

## 🔵 Phase 6 — Enrichment Engine

> **Goal:** Prevent knowledge stagnation. Merge and evolve notes instead of duplicating.

- [x] **P6.1** — Write `app/services/enrichment_engine.py`:  
  Before saving a new note: check if any existing note has similarity > 0.84  
  If yes: send both to LLM with prompt: "Rewrite the existing note incorporating the new information"  
  Update the existing `notes` row instead of inserting a new one  
  `Completed: 2026-05-25`

- [x] **P6.2** — Handle edge case: if enrichment fails or LLM output is nonsensical, fall back to saving as a new note  
  `Completed: 2026-05-25`

- [x] **P6.3** — Add an `enrichment_log` to track merges: `source_note_id`, `merged_at`, `old_summary`, `new_summary`  
  `Completed: 2026-05-25`

- [x] **P6.4** — Update `obsidian_sync` to re-sync the enriched note's `.md` file when a note is merged  
  `Completed: 2026-05-25`

- [x] **P6.5** — Test: save the same conceptual note twice (slightly rephrased), verify enrichment fires  
  `Completed: 2026-05-25`

---

## 🔵 Phase 7 — Multi-modal Capture (Images & PDFs)

> **Goal:** You can send a screenshot or PDF to Telegram and Grain processes it.

- [ ] **P7.1** — In `app/integrations/telegram.py`: detect `photo` and `document` message types  
  `Completed: ___________`

- [ ] **P7.2** — Download the file from Telegram's servers using the file API  
  `Completed: ___________`

- [ ] **P7.3** — For images: send to Gemini Vision API, extract text/context  
  `Completed: ___________`

- [ ] **P7.4** — For PDFs: use `PyMuPDF` or `pdfplumber` to extract text, then pass to understanding engine  
  `Completed: ___________`

- [ ] **P7.5** — Route extracted content through the standard ingestion pipeline  
  `Completed: ___________`

- [ ] **P7.6** — Test: send a screenshot of a paper, verify Grain extracts and saves the content  
  `Completed: ___________`

---

## 🔵 Phase 8 — Conversational Recall

> **Goal:** Ask complex questions. Get back connected, reasoned answers.

- [x] **P8.1** — Implement a conversation mode in Telegram: `/think [complex question]`  
  `Completed: 2026-05-26`

- [x] **P8.2** — Retrieval: use hybrid search (vectors + entity match + graph traversal) to gather context  
  `Completed: 2026-05-26`

- [x] **P8.3** — Send gathered context + question to LLM:  
  "Based on the user's saved knowledge, answer: [question]"  
  `Completed: 2026-05-26`

- [x] **P8.4** — Return the answer with citations (which notes were used, topic labels, source URLs)  
  `Completed: 2026-05-26`

- [x] **P8.5** — Test: ask "What connects ODAS and EV range estimation?" — verify cross-domain answer  
  `Completed: 2026-05-26`

---

## 🔵 Phase 9 — Hosting & Deployment

> **Goal:** Run Grain 24/7 without your laptop.

- [~] **P9.1** — Create `Dockerfile` for the FastAPI app  
  `Completed: 2026-05-27 (Render auto-detects Python — no Dockerfile needed)`

- [x] **P9.2** — Setup Railway or Render project, connect GitHub repo  
  `Completed: 2026-05-27`

- [x] **P9.3** — Configure all environment variables in the cloud dashboard  
  `Completed: 2026-05-27`

- [x] **P9.4** — Point Telegram webhook to the live cloud URL  
  `Completed: 2026-05-27`

- [~] **P9.5** — Smoke test all commands on the live deployed version  
  `Completed: 2026-05-27 (basic: /note, /ask, /think work; full matrix pending)`

---

## 🔵 Phase 10 — Multi-Tenant Migration

> **Goal:** User isolation with sign-up/sign-in. Multiple people can use Grain, each seeing only their own data.

- [ ] **P10.0** — Create `users` table, `UserSchema`, `app/db/users.py` helpers, auto-register on `/start`  
  `Completed: 2026-05-27`

- [x] **P10.1** — Add `user_id` to all data tables (`notes`, `topics`, `entities`, `note_entities`, `relations`, `enrichment_log`, `agent_state`). Drop global UNIQUEs, add per-user `(user_id, name)` UNIQUEs. Add `p_user_id` to `match_notes` RPC. Backfill existing data.  
  `Completed: 2026-05-27`

- [x] **P10.2** — Update all 22 Python files that make Supabase calls to filter by `user_id`. Wire `user_id` through the entire pipeline from webhook entry to every query.  
  `Completed: 2026-05-27`

- [ ] **P10.3** — Telegram auto-auth: verify `X-Telegram-Bot-Api-Secret-Token` header on webhook. Welcome screen on `/start` with user identity.  
  `Completed: ___________`

- [ ] **P10.4** — Supabase Auth for web dashboard: JWT verification middleware, `/auth/*` endpoints. Link `users.supabase_user_id` to `auth.users.id`.  
  `Completed: ___________`

- [ ] **P10.5** — RLS policies on all tables for defense-in-depth. Grace period: remove backward-compat fallbacks, verify no queries bypass `user_id`.  
  `Completed: ___________`

---

## 🟢 Phase 11 — Web Dashboard

> **Goal:** Visual knowledge browser — browse, search, edit, knowledge graph.

- [ ] **P11.0** — Create new repository, set up SvelteKit/Next.js with Supabase JS client  
  `Completed: ___________`

- [ ] **P11.1** — Login/signup page using Supabase Auth  
  `Completed: ___________`

- [ ] **P11.2** — Browse notes by topic, date, entity, facet  
  `Completed: ___________`

- [ ] **P11.3** — Semantic search bar using `match_notes` RPC  
  `Completed: ___________`

- [ ] **P11.4** — Note detail page with full Knowledge Card  
  `Completed: ___________`

- [ ] **P11.5** — Interactive knowledge graph (D3.js / vis.js)  
  `Completed: ___________`

- [ ] **P11.6** — Inline edit: title, summary, facts, status, topic  
  `Completed: ___________`

- [ ] **P11.7** — Topic tree with parent/child hierarchy  
  `Completed: ___________`

- [ ] **P11.8** — Entity browser grouped by type  
  `Completed: ___________`

- [ ] **P11.9** — Deploy to Vercel free tier  
  `Completed: ___________`

---

*Last updated: 2026-05-27*
