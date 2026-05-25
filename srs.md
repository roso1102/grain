# 📄 Software Requirements Specification (SRS)

**Project:** Grain — Personal Knowledge Operating System (PKOS)  
**Version:** 1.0  
**Date:** 2026-05-25  
**Status:** Draft

---

## 1. Introduction

### 1.1 Purpose
This document defines the software requirements for Grain, a personal AI-powered knowledge management system. It serves as the authoritative specification for developers building the system.

### 1.2 Scope
Grain enables a single user to capture fragmented information from multiple sources (primarily Telegram), have it automatically understood, classified, stored, and organized — with full semantic retrieval, entity-level memory, and Notion-based knowledge presentation.

### 1.3 Definitions

| Term | Definition |
|---|---|
| **PKOS** | Personal Knowledge Operating System |
| **Grain (note)** | A single unit of captured information |
| **Topic** | A classification category (e.g., "VLSI", "EV Research") |
| **Entity** | A named concept, technology, project, or person extracted from a note |
| **Semantic Snapping** | Auto-deduplication of topics using vector similarity |
| **Enrichment** | Merging a new note into an existing one rather than creating a duplicate |
| **Personal Insight** | A user annotation attached to a shared link or note (e.g., "this might be true in 30 yrs") |
| **Source of Truth** | Supabase. All canonical data lives here. |
| **Knowledge UI** | Notion. A read/write view layer on top of Supabase data. |

---

## 2. Overall Description

### 2.1 Product Perspective
Grain is a personal system with a single user (the owner/developer). It is not a SaaS product. It operates as a backend service that bridges:

```
User (Telegram) ↔ FastAPI ↔ Supabase (Brain) ↔ Notion (UI)
```

### 2.2 User Characteristics
- Single power user (the developer)
- Captures knowledge in short bursts across domains (VLSI, ML, EVs, Japanese, GATE)
- Expects zero friction: send → forget, Grain handles the rest
- Expects to query back: "What do I know about X?"
- Expects Notion to reflect captured knowledge, and edits in Notion to persist

### 2.3 Constraints
- **Cost:** No paid embedding APIs. Embeddings must run locally using `sentence-transformers`.
- **LLM:** Prefer Google Gemini free tier (Flash). Mistral as fallback.
- **Input Channel:** Primary input is Telegram Bot.
- **Storage:** Supabase (PostgreSQL + pgvector).
- **UI:** Notion (not a custom web dashboard — at least in Phase 1-7).

---

## 3. Functional Requirements

### 3.1 Ingestion

#### FR-ING-01: Plain Text Capture
- The system SHALL accept plain text messages sent to the Telegram bot.
- The system SHALL process and store a note within 5 seconds of receiving the message.

#### FR-ING-02: Link Capture with Content Extraction
- When a user sends a message containing a URL, the system SHALL:
  - Detect the URL(s) in the message.
  - Fetch the web page content using `httpx`.
  - Extract main article text using `BeautifulSoup4`.
  - Store the original URL as `source_url`.
- If the web page is inaccessible, the system SHALL log the failure and save only the URL and any user text.

#### FR-ING-03: Routing Instruction Detection
- When a user includes routing text alongside a link (e.g., "save this to EV batteries"), the system SHALL detect this instruction and use it to override the LLM-inferred topic classification.
- Detection is performed by the LLM via `intent_parser.py`.

#### FR-ING-04: Personal Insight Preservation
- When a user includes a personal annotation alongside a link or note (e.g., "this might be true in 30 yrs"), the system SHALL:
  - Detect and extract this annotation separately from the main content.
  - Store it in the `personal_insight` field of the `notes` table.
  - NOT remove or discard the annotation.
- The annotation SHALL appear in retrieval results alongside the note.

#### FR-ING-05: Image Capture (Phase 7)
- The system SHALL accept image files (photos) sent via Telegram.
- The system SHALL send the image to a Vision LLM (Gemini) and extract the textual content.
- Extracted text SHALL be processed through the standard ingestion pipeline.

#### FR-ING-06: PDF Capture (Phase 7)
- The system SHALL accept PDF documents sent via Telegram.
- The system SHALL extract text using `pdfplumber` or `PyMuPDF`.
- Extracted text SHALL be chunked if it exceeds the LLM context window and processed per chunk.

---

### 3.2 Understanding Engine

#### FR-UND-01: Summarization
- The system SHALL generate a 2–3 sentence summary of every ingested note using an LLM.
- For link-based notes, the summary SHALL be based on the scraped content, not the raw URL.

#### FR-UND-02: Classification
- The system SHALL classify every note into a topic name (free-form string) using an LLM.
- If the user provided a routing hint (FR-ING-03), it SHALL be prioritized over the LLM classification.

#### FR-UND-03: Importance Scoring
- The system SHALL assign an `importance_score` (0.0–1.0) to each note based on LLM-inferred relevance and density.

---

### 3.3 Semantic Topic Snapping

#### FR-SNAP-01: Topic Embedding
- Every `topic` in Supabase SHALL have a `vector(384)` embedding generated by the local `BAAI/bge-small-en-v1.5` model.

#### FR-SNAP-02: Deduplication Check
- Before creating a new topic, the system SHALL:
  - Embed the proposed topic name.
  - Compute cosine similarity against all existing topic embeddings.
  - If max similarity ≥ 0.90: use the existing topic (snap).
  - If max similarity < 0.90: create a new topic, save its embedding.

#### FR-SNAP-03: No Hard-coded Categories
- The system SHALL NOT maintain a fixed list of allowed topics.
- Topics are dynamic and resolved via semantic similarity.

---

### 3.4 Embedding Engine

#### FR-EMB-01: Local Embedding Model
- All text embeddings SHALL be generated using the `sentence-transformers` library with model `BAAI/bge-small-en-v1.5`.
- The model SHALL be loaded into memory once at application startup.
- No external paid embedding API SHALL be used.

#### FR-EMB-02: Embedding Targets
- The system SHALL generate and store embeddings for: note summaries, topic names, entity names.

---

### 3.5 Retrieval Engine

#### FR-RET-01: Semantic Search
- The system SHALL support natural language queries via Telegram command `/ask [query]`.
- The system SHALL embed the query and perform ANN search via pgvector.
- The system SHALL return the top-k (default k=5) most similar notes.

#### FR-RET-02: Hybrid Retrieval (Phase 5+)
- After vector search, the system SHALL expand results by:
  - Including notes connected via `relations` edges (1-hop graph traversal).
  - Boosting notes that share named entities with the query.

#### FR-RET-03: Result Format
- Retrieval results returned to the user SHALL include:
  - Note summary
  - Topic label
  - Source URL (if applicable)
  - Personal insight (if present)

---

### 3.6 Notion Sync Engine

#### FR-NOT-01: Auto Page Creation
- When a note is saved under a new topic, the system SHALL automatically create a Notion page for that topic.
- When a note is saved under an existing topic, the system SHALL append the summary as a new block to the existing Notion page.

#### FR-NOT-02: Notion Block Tracking
- The system SHALL store `notion_block_id` and `notion_last_edited` in the `notes` table for every block synced to Notion.

#### FR-NOT-03: Two-Way Sync (Polling)
- A background task SHALL run every 5 minutes.
- It SHALL compare `notes.notion_last_edited` against the current Notion block `last_edited_time` via the Notion API.
- If Notion's timestamp is newer: the edited text SHALL be fetched and written back to `notes.raw_text` in Supabase.

#### FR-NOT-04: Notion Is Not the Source of Truth
- All queries, graph operations, and ML functions SHALL operate against Supabase, not Notion.
- Notion is strictly a presentation and two-way editing layer.

---

### 3.7 Entity Engine (Phase 4)

#### FR-ENT-01: Entity Extraction
- For each ingested note, the system SHALL extract named entities using an LLM prompt.
- Entity types: `concept`, `technology`, `project`, `person`.

#### FR-ENT-02: Entity Deduplication
- Before inserting an entity, the system SHALL check for an exact name match in the `entities` table.
- If match found: reuse the existing entity ID.
- If not: insert new entity with embedding.

#### FR-ENT-03: Note-Entity Links
- The system SHALL store a `confidence` score (0.0–1.0) for each `note_entity` link.

---

### 3.8 Memory Graph (Phase 5)

#### FR-GRP-01: Relation Creation
- After saving a note, the system SHALL compare its embedding against the top-20 most similar existing notes.
- For pairs with similarity > 0.75, the system SHALL use an LLM to classify the relation type: `related_to`, `extends`, `contradicts`, `depends_on`.
- The system SHALL insert a row into the `relations` table.

#### FR-GRP-02: Graph Retrieval API
- The system SHALL expose `GET /related-notes/{id}` returning all notes connected to the given note via `relations`.

---

### 3.9 Enrichment Engine (Phase 6)

#### FR-ENR-01: Pre-Save Similarity Check
- Before inserting a new note, the system SHALL check if any existing note has a cosine similarity > 0.88.

#### FR-ENR-02: Enrichment Instead of Duplication
- If a similar note is found, the system SHALL send both notes to the LLM with instructions to rewrite the existing note incorporating the new information.
- The existing `notes` row SHALL be updated (not a new row inserted).

#### FR-ENR-03: Enrichment Fallback
- If enrichment output is deemed invalid (empty or < 50 chars), the system SHALL fall back to saving as a new note.

#### FR-ENR-04: Enrichment Log
- The system SHALL maintain an `enrichment_log` table recording: `source_note_id`, `merged_at`, `old_summary`, `new_summary`.

---

## 4. Non-Functional Requirements

### 4.1 Performance

| Requirement | Target |
|---|---|
| End-to-end ingestion time (text) | < 5 seconds |
| End-to-end ingestion time (link) | < 10 seconds |
| Search query response time | < 3 seconds |
| Notion polling interval | Every 5 minutes |
| Embedding generation (local) | < 200ms per note |

### 4.2 Reliability
- The system SHALL log all errors with full stack traces using structured logging.
- If any stage of the pipeline fails (LLM, Notion, scraping), the system SHALL save what it has to Supabase and notify the user via Telegram.
- Critical failures SHALL NOT lose the raw input text.

### 4.3 Cost
- Embedding generation cost: $0 (local model).
- LLM cost: $0 (Gemini Flash free tier).
- Hosting cost: $0–$5/month (Railway/Render free tier).
- Database cost: $0 (Supabase free tier).

### 4.4 Maintainability
- Each service SHALL be in its own file with a single responsibility.
- All external API calls SHALL be isolated in `app/integrations/`.
- Configuration SHALL be centralized in `app/core/config.py`.

### 4.5 Security
- All secrets (API keys, DB credentials) SHALL be stored in environment variables only.
- No secrets SHALL appear in committed code.
- The `.env` file SHALL be listed in `.gitignore`.

---

## 5. Data Requirements

### 5.1 Retention
- Notes SHALL be retained indefinitely unless explicitly deleted by the user.
- Enriched notes SHALL maintain history via the `enrichment_log`.

### 5.2 Source Attribution
- Every note SHALL have a `source_type` and, if applicable, a `source_url`.
- Source attribution SHALL always be preserved through enrichment operations.

### 5.3 Personal Insights
- The `personal_insight` field SHALL never be overwritten during enrichment.
- New insights from subsequent messages SHALL be appended (not replaced).

---

## 6. External Interface Requirements

### 6.1 Telegram Bot Interface

| Command | Action |
|---|---|
| `[any text]` | Ingest as a note |
| `[url + text]` | Ingest link with optional routing/insight |
| `/ask [query]` | Semantic search |
| `/related [query or id]` | Show related notes |
| `/think [complex question]` | Conversational recall (Phase 8) |

### 6.2 REST API Interface

| Endpoint | Method | Description |
|---|---|---|
| `/ingest-note` | POST | Ingest a note programmatically |
| `/search` | POST | Semantic search |
| `/sync-notion` | POST | Force sync topic/note to Notion |
| `/related-notes/{id}` | GET | Get related notes by ID |
| `/topic/{name}` | GET | Get all notes under a topic |
| `/health` | GET | Service health check |

### 6.3 Supabase Interface
- All database interactions SHALL use `supabase-py` client.
- Raw SQL for vector operations (pgvector ANN) SHALL be issued via `supabase.rpc()`.

### 6.4 Notion Interface
- All Notion interactions SHALL use the official Notion REST API via `httpx`.
- The integration SHALL require a Notion Internal Integration token with read/write access to the Grain workspace.

---

## 7. Assumptions and Dependencies

- Supabase provides stable pgvector support.
- Gemini Flash free tier remains available.
- Telegram Bot API webhooks work on the chosen hosting platform.
- User has stable internet for Notion polling and LLM calls.
- The `BAAI/bge-small-en-v1.5` model is compatible with the deployment environment's CPU.

---

## 8. Out of Scope (v1.0)

- Multi-user support
- Voice note transcription (Telegram voice messages)
- Web dashboard / custom frontend
- Real-time Notion webhooks (polling used instead)
- Mobile app
- Browser extension (planned for later)

---

*SRS Version 1.0 — Grain PKOS*
