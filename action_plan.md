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

- [ ] **0.1** — Initialize Python project, create `app/` folder structure as defined in README  
  `Completed: ___________`

- [ ] **0.2** — Create `.env.example` with all required keys:  
  `SUPABASE_URL`, `SUPABASE_KEY`, `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`  
  `Completed: ___________`

- [ ] **0.3** — Create `requirements.txt` with initial dependencies:  
  `fastapi`, `uvicorn`, `pydantic`, `httpx`, `supabase-py`, `python-telegram-bot`, `google-generativeai`  
  `Completed: ___________`

- [ ] **0.4** — Setup `app/core/config.py` to load all env variables via Pydantic `BaseSettings`  
  `Completed: ___________`

- [ ] **0.5** — Setup `app/core/logger.py` with structured logging  
  `Completed: ___________`

- [ ] **0.6** — Create `app/main.py` with a barebones FastAPI app and `/health` endpoint  
  `Completed: ___________`

- [ ] **0.7** — Verify server starts: `uvicorn app.main:app --reload`  
  `Completed: ___________`

---

### 1.0 — Supabase Setup (MVP Schema)

- [ ] **1.1** — Create Supabase project, get URL and anon key  
  `Completed: ___________`

- [ ] **1.2** — Write `migrations/001_init.sql`:  
  Create `topics` table (`id`, `name`, `parent_id`, `description`, `notion_page_id`)  
  `Completed: ___________`

- [ ] **1.3** — Write `migrations/001_init.sql` (continued):  
  Create `notes` table (`id`, `raw_text`, `summary`, `source_url`, `source_type`, `personal_insight`, `topic_id`, `created_at`)  
  `Completed: ___________`

- [ ] **1.4** — Run migrations on Supabase SQL editor, verify tables exist  
  `Completed: ___________`

- [ ] **1.5** — Setup `app/db/supabase.py` — initialize and export Supabase client  
  `Completed: ___________`

- [ ] **1.6** — Write basic CRUD helpers in `app/db/queries.py`:  
  `insert_note()`, `get_note_by_id()`, `get_all_topics()`, `insert_topic()`  
  `Completed: ___________`

---

### 2.0 — Telegram Bot Setup

- [ ] **2.1** — Create Telegram bot via BotFather, save token to `.env`  
  `Completed: ___________`

- [ ] **2.2** — Write `app/integrations/telegram.py`:  
  Handle incoming messages, extract text/photo/document/link  
  `Completed: ___________`

- [ ] **2.3** — Register `/webhook` endpoint in FastAPI (`app/api/ingest.py`)  
  `Completed: ___________`

- [ ] **2.4** — Set Telegram webhook URL to your FastAPI server  
  `Completed: ___________`

- [ ] **2.5** — Test: send a message to the bot, confirm FastAPI receives it  
  `Completed: ___________`

---

### 3.0 — LLM Integration (Understanding Engine, MVP)

- [ ] **3.1** — Setup `app/integrations/gemini.py` — Gemini Flash API client with a reusable `call_llm(prompt)` function  
  `Completed: ___________`

- [ ] **3.2** — Write `app/services/summarizer.py`:  
  Takes raw text, returns 2–3 sentence summary via LLM  
  `Completed: ___________`

- [ ] **3.3** — Write `app/services/classifier.py`:  
  Takes raw text + summary, returns a topic name (free-form string)  
  `Completed: ___________`

- [ ] **3.4** — Write `app/services/intent_parser.py`:  
  Detect if the user mentioned a routing instruction ("save to X") or a personal annotation  
  Extract and return: `{ "route_hint": str | None, "personal_insight": str | None }`  
  `Completed: ___________`

- [ ] **3.5** — Write `app/services/link_extractor.py`:  
  Detect URLs in message, fetch page with `httpx`, extract main text using `BeautifulSoup4`  
  Return: `{ "url": str, "content": str, "title": str }`  
  `Completed: ___________`

- [ ] **3.6** — Combine into a unified `understand(raw_input)` function that handles both plain text and links  
  `Completed: ___________`

---

### 4.0 — Ingestion Pipeline (MVP End-to-End)

- [ ] **4.1** — Write `app/api/ingest.py`:  
  `POST /ingest-note` → receives raw message from Telegram webhook  
  `Completed: ___________`

- [ ] **4.2** — In the ingestion handler, call the full pipeline:  
  `parse → link_extractor → intent_parser → summarize → classify`  
  `Completed: ___________`

- [ ] **4.3** — Write Pydantic model `NoteInput` in `app/models/note.py`  
  `Completed: ___________`

- [ ] **4.4** — Save processed note to Supabase `notes` table via `insert_note()`  
  `Completed: ___________`

- [ ] **4.5** — Have the bot reply with a confirmation: topic + 1-line summary  
  `Completed: ___________`

- [ ] **4.6** — Full end-to-end test:  
  Send Telegram message → bot replies with topic + summary → check Supabase row  
  `Completed: ___________`

---

## 🔵 Phase 1 — Semantic Topic Snapping

> **Goal:** Prevent category duplication. New topics auto-merge with similar existing ones.

- [ ] **P1.1** — Add `pgvector` extension to Supabase. Write `migrations/002_vectors.sql`:  
  Add `embedding vector(384)` column to `notes` and `topics`  
  `Completed: ___________`

- [ ] **P1.2** — Add `sentence-transformers` to `requirements.txt`  
  `Completed: ___________`

- [ ] **P1.3** — Write `app/services/embedder.py`:  
  Load `BAAI/bge-small-en-v1.5` model once at startup, expose `embed(text) → List[float]`  
  `Completed: ___________`

- [ ] **P1.4** — Write `app/services/topic_snapper.py`:  
  Embed proposed topic name → cosine similarity against all existing topic embeddings in Supabase →  
  If max similarity > 0.90: return existing topic ID  
  Else: insert new topic with embedding, return new ID  
  `Completed: ___________`

- [ ] **P1.5** — Integrate `topic_snapper` into the ingestion pipeline (replace the raw `classify` step)  
  `Completed: ___________`

- [ ] **P1.6** — Also embed the note summary and save the vector in `notes.embedding`  
  `Completed: ___________`

- [ ] **P1.7** — Test: send similar-topic notes, verify they snap to the same topic in Supabase  
  `Completed: ___________`

---

## 🔵 Phase 2 — Semantic Search

> **Goal:** Be able to ask "What do I know about X?" via Telegram.

- [ ] **P2.1** — Write `app/api/search.py`: `POST /search` endpoint, accepts a natural language query  
  `Completed: ___________`

- [ ] **P2.2** — Write `app/services/retrieval_engine.py`:  
  Embed query → pgvector ANN search → return top-k most similar notes  
  `Completed: ___________`

- [ ] **P2.3** — Add a Telegram command `/ask [query]` that calls the search endpoint  
  `Completed: ___________`

- [ ] **P2.4** — Write `app/utils/ranking.py`: rank results by similarity + importance_score  
  `Completed: ___________`

- [ ] **P2.5** — Format search results for Telegram: return top 3 summaries with topic labels + source URLs  
  `Completed: ___________`

- [ ] **P2.6** — Test: ask about a topic you've previously saved, verify relevant notes surface  
  `Completed: ___________`

---

## 🔵 Phase 3 — Notion Sync Engine

> **Goal:** See your knowledge organized visually in Notion automatically.

- [ ] **P3.1** — Setup Notion integration, create Notion workspace for Grain, get API key  
  `Completed: ___________`

- [ ] **P3.2** — Write `app/integrations/notion.py`:  
  Wrappers for: `create_page()`, `append_block()`, `get_page()`, `search_pages()`, `get_block_last_edited_time()`  
  `Completed: ___________`

- [ ] **P3.3** — Write `app/services/notion_sync.py`:  
  On note save: check `notion_map` for topic page → if exists, append summary block → if not, create page  
  `Completed: ___________`

- [ ] **P3.4** — Save `notion_block_id` and `notion_last_edited` to `notes` table after sync  
  `Completed: ___________`

- [ ] **P3.5** — Implement the **Polling Engine** (two-way sync):  
  Background task running every 5 minutes:  
  Fetch all `notes.notion_block_id` where `notion_last_edited` exists →  
  Call Notion API to get current `last_edited_time` →  
  If Notion's timestamp > Supabase's: fetch edited text, update `notes.raw_text` in Supabase  
  `Completed: ___________`

- [ ] **P3.6** — Test: sync a note to Notion, edit it in Notion, wait 5 min, verify Supabase updated  
  `Completed: ___________`

---

## 🔵 Phase 4 — Entity Engine

> **Goal:** Extract structured knowledge nodes (concepts, technologies, projects).

- [ ] **P4.1** — Write `migrations/003_graph.sql`:  
  Create `entities`, `note_entities`, `relations` tables  
  `Completed: ___________`

- [ ] **P4.2** — Write `app/services/entity_extractor.py`:  
  LLM prompt: extract key concepts/technologies/projects from the summary  
  Return: `[{"name": "memristor", "type": "technology"}, ...]`  
  `Completed: ___________`

- [ ] **P4.3** — Write `app/db/queries.py` additions:  
  `upsert_entity()`, `link_note_to_entity()`  
  `Completed: ___________`

- [ ] **P4.4** — Integrate entity extraction into the ingestion pipeline  
  `Completed: ___________`

- [ ] **P4.5** — Embed entity names and store in `entities.embedding`  
  `Completed: ___________`

- [ ] **P4.6** — Add entity overlap to retrieval engine: boost notes that share entities with the query  
  `Completed: ___________`

---

## 🔵 Phase 5 — Memory Graph

> **Goal:** Connect notes to each other. Build a relational knowledge web.

- [ ] **P5.1** — Write `app/services/relation_engine.py`:  
  After a note is saved: compare its embedding against top-k existing notes →  
  For pairs with similarity > 0.75: use LLM to infer the relation type (`extends`, `related_to`, `contradicts`, `depends_on`)  
  Insert into `relations` table  
  `Completed: ___________`

- [ ] **P5.2** — Write `app/api/graph.py`: `GET /related-notes/{id}` endpoint  
  `Completed: ___________`

- [ ] **P5.3** — Add graph expansion to `retrieval_engine.py`:  
  After vector search, traverse `relations` to pull in 1-hop connected notes  
  `Completed: ___________`

- [ ] **P5.4** — Add a Telegram command `/related [note-id or topic]` to surface connections  
  `Completed: ___________`

- [ ] **P5.5** — Test: save two related notes on different days, verify a relation edge is created  
  `Completed: ___________`

---

## 🔵 Phase 6 — Enrichment Engine

> **Goal:** Prevent knowledge stagnation. Merge and evolve notes instead of duplicating.

- [ ] **P6.1** — Write `app/services/enrichment_engine.py`:  
  Before saving a new note: check if any existing note has similarity > 0.88  
  If yes: send both to LLM with prompt: "Rewrite the existing note incorporating the new information"  
  Update the existing `notes` row instead of inserting a new one  
  `Completed: ___________`

- [ ] **P6.2** — Handle edge case: if enrichment fails or LLM output is nonsensical, fall back to saving as a new note  
  `Completed: ___________`

- [ ] **P6.3** — Add an `enrichment_log` to track merges: `source_note_id`, `merged_at`, `old_summary`, `new_summary`  
  `Completed: ___________`

- [ ] **P6.4** — Update `notion_sync` to re-sync the enriched Notion block when a note is merged  
  `Completed: ___________`

- [ ] **P6.5** — Test: save the same conceptual note twice (slightly rephrased), verify enrichment fires  
  `Completed: ___________`

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

- [ ] **P8.1** — Implement a conversation mode in Telegram: `/think [complex question]`  
  `Completed: ___________`

- [ ] **P8.2** — Retrieval: use hybrid search (vectors + entity match + graph traversal) to gather context  
  `Completed: ___________`

- [ ] **P8.3** — Send gathered context + question to LLM:  
  "Based on the user's saved knowledge, answer: [question]"  
  `Completed: ___________`

- [ ] **P8.4** — Return the answer with citations (which notes were used, topic labels, source URLs)  
  `Completed: ___________`

- [ ] **P8.5** — Test: ask "What connects ODAS and EV range estimation?" — verify cross-domain answer  
  `Completed: ___________`

---

## 🔵 Phase 9 — Hosting & Deployment

> **Goal:** Run Grain 24/7 without your laptop.

- [ ] **P9.1** — Create `Dockerfile` for the FastAPI app  
  `Completed: ___________`

- [ ] **P9.2** — Setup Railway or Render project, connect GitHub repo  
  `Completed: ___________`

- [ ] **P9.3** — Configure all environment variables in the cloud dashboard  
  `Completed: ___________`

- [ ] **P9.4** — Point Telegram webhook to the live cloud URL  
  `Completed: ___________`

- [ ] **P9.5** — Smoke test all commands on the live deployed version  
  `Completed: ___________`

---

*Last updated: 2026-05-25*
