# 🌾 Grain — Personal Knowledge Operating System (PKOS)

> **"Dump first. Grain understands the rest."**

Grain is an AI-powered Personal Knowledge Operating System that transforms scattered, fragmented information — Telegram messages, links, PDFs, screenshots — into structured, connected, and searchable memory.

It is **not** a notes app. It is **not** a RAG chatbot. It is a system that *understands* what you capture and organizes it intelligently over time.

---

## 🧠 The Core Problem

Your knowledge is fragmented across:

- Telegram saved messages
- Random web links
- PDF research papers
- Screenshots
- Project notes (GATE, VLSI, ODAS, EV/PINN)
- Research ideas
- Japanese study notes
- Resume thoughts
- Random insights at 2AM

You **capture** things — but they never become **connected knowledge**.

Grain fixes this: turning small "grains" of information into a structured, living memory graph.

---

## 💡 What Grain Does

**Input:**
You send text, links, files, or screenshots to a Telegram bot.

**Grain then:**

1. Ingests the raw content
2. Extracts full content from URLs (web scraping)
3. Detects any inline routing instructions ("save to EV batteries")
4. Preserves personal annotations ("this might be true in 30 yrs")
5. Summarizes and classifies into topics
6. Applies **Semantic Topic Snapping** — prevents duplicate/messy categories
7. Extracts named entities (concepts, projects, technologies)
8. Creates vector embeddings (free, local model)
9. Builds relationship edges between notes (memory graph)
10. Syncs structured summaries to Notion
11. Makes everything semantically searchable

---

## 🏗️ System Architecture

```
[You] ──→ [Telegram Bot]
               │
               ▼
        [FastAPI Backend]
         ┌────┴─────┐
         │  Ingest  │
         └────┬─────┘
              │
    ┌─────────▼──────────┐
    │  Understanding     │
    │  Engine            │
    │  (consolidated     │
    │   LLM pipeline)    │
    │  ├── summarize     │
    │  ├── classify      │
    │  ├── detect intent │
    │  ├── extract       │
    │  │   entities      │
    │  ├── route links   │
    │  │   to scrapers   │
    │  └── extract       │
    │      facets        │
    └─────────┬──────────┘
              │
    ┌─────────▼──────────┐
    │  Semantic Snapping │
    │  (Topic Dedup)     │
    └─────────┬──────────┘
              │
    ┌─────────▼──────────┐
    │  Embedding Engine  │
    │  (local, free)     │
    │  BAAI/bge-small    │
    └─────────┬──────────┘
              │
    ┌─────────▼──────────────────────────┐
    │           Supabase (Brain)         │
    │  ├── notes                         │
    │  ├── topics                        │
    │  ├── entities                      │
    │  ├── relations (graph edges)       │
    │  ├── note_entities                 │
    │  └── notion_map                    │
    └─────────┬──────────────────────────┘
              │
    ┌─────────▼──────────┐
    │   Enrichment       │
    │   Engine           │
    │   (merge/improve)  │
    └─────────┬──────────┘
              │
    ┌─────────▼──────────┐
    │   Notion Sync      │
    │   (with Polling    │
    │   for Two-Way Sync)│
    └────────────────────┘
```

---

## 🔑 Mental Model

| Component | Role |
|---|---|
| **Supabase** | The Brain — source of truth. Stores notes, vectors, graph, metadata |
| **Notion** | The Knowledge UI — browsable, organized, human-readable |
| **Telegram** | The Capture Pipe — frictionless input, zero context switching |
| **FastAPI** | The Orchestrator — connects all systems |
| **sentence-transformers** | Free local embedding model (BAAI/bge-small-en-v1.5) |
| **Gemini/Mistral** | LLM for understanding, classification, summarization |

---

## ✨ What Makes Grain Different

| Generic RAG Tools | **Grain** |
|---|---|
| Store → Retrieve | Store → Understand → Relate → Enrich → Retrieve |
| Single vector search | Vector + Entity + Graph hybrid retrieval |
| Topic tags = user's job | **Semantic Topic Snapping** — auto-dedup categories |
| Link saved as-is | Link scraped, content extracted, personal note preserved |
| No two-way sync | Notion polling for two-way edit sync |
| Paid embeddings | Local, free `sentence-transformers` |
| Notes grow forever | Enrichment Engine merges & evolves knowledge nodes |

---

## 🛠️ Tech Stack

| Layer | Technology | Why |
|---|---|---|
| Backend | FastAPI (async) | Fast, async, Pydantic validation |
| Database | Supabase (PostgreSQL) | Relational + cloud + auth + easy API |
| Vector Search | pgvector | Semantic similarity, built into Supabase |
| LLM | Google Gemini Flash / Mistral | Free tier, classification & summarization |
| Embeddings | `BAAI/bge-small-en-v1.5` (local) | **Zero cost**, runs on CPU |
| Input | Telegram Bot API | Frictionless capture |
| Knowledge UI | Notion API | Human-readable organization |
| Web Scraping | `httpx` + `BeautifulSoup4` | Link content extraction |
| Hosting | Railway / Render | Simple, free tier available |

---

## 🔧 Core Modules

### 1. Ingestion Engine
Handles all incoming content. Detects: plain text, links, files, voice (later). For links, routes to the scrapers module (Jina → trafilatura → BS4 fallback chain) and separates the article from any user annotation.

### 2. Understanding Engine
Consolidated AI pipeline that:
- Summarizes content
- Classifies into topic
- Detects routing intent ("save to EV batteries")
- Preserves personal annotations/insights
- Extracts named entities
- Extracts facets (projects, domains, statuses, sentiments)
- Routes URLs to the appropriate scraper

### 3. Semantic Topic Snapping
Before saving a new topic classification, the system embeds the proposed topic name and compares it to all existing topics in Supabase. If cosine similarity > 0.90, it snaps to the existing topic (no duplicate). Otherwise, creates a new topic.

### 4. Memory Engine
Supabase + pgvector + graph logic. Stores semantic and structural memory.

### 5. Retrieval Engine
Answers: "What do I know about memristor PUF?"
Uses: vector similarity → entity overlap (LLM-extracted entities for query) → graph expansion → ranking

### 6. Notion Sync Engine
Creates/updates Notion pages from Supabase. Also runs a background **polling task** to detect Notion-side edits and write them back to Supabase. Notion's `last_edited_time` is tracked per block.

### 7. Enrichment Engine
Before creating a new note, checks if a highly similar note already exists (similarity > 0.88). If yes, prompts LLM to rewrite the old note with the new context merged in, rather than creating a duplicate.

---

## 📡 API Endpoints

```
GET  /health               → System health check
POST /webhook              → Telegram bot webhook receiver
POST /ingest-note          → Ingest text, link, or file manually
POST /search               → Semantic search across all notes
GET  /related-notes/{id}   → Graph traversal from a given note
GET  /facets               → Aggregate facet values across notes
```

---

## 🗃️ Database Schema (Supabase)

### `notes`
```sql
id                UUID PRIMARY KEY
raw_text          TEXT
summary           TEXT
source_url        TEXT          -- URL if the input was a link
source_type       TEXT          -- 'telegram_text' | 'link' | 'pdf' | 'screenshot'
personal_insight  TEXT          -- User's annotation attached to the note
topic_id          UUID REFERENCES topics
embedding         vector(384)   -- From bge-small
importance_score  FLOAT
created_at        TIMESTAMPTZ
notion_page_id    TEXT
notion_block_id   TEXT
notion_last_edited TIMESTAMPTZ  -- For two-way sync polling
```

### `topics`
```sql
id                UUID PRIMARY KEY
name              TEXT UNIQUE
parent_id         UUID REFERENCES topics  -- Subtopics
description       TEXT
embedding         vector(384)
notion_page_id    TEXT
```

### `entities`
```sql
id     UUID PRIMARY KEY
name   TEXT
type   TEXT  -- 'concept' | 'project' | 'technology' | 'person'
embedding vector(384)
```

### `note_entities`
```sql
note_id     UUID REFERENCES notes
entity_id   UUID REFERENCES entities
confidence  FLOAT
```

### `relations`
```sql
id              UUID PRIMARY KEY
source_note_id  UUID REFERENCES notes
target_note_id  UUID REFERENCES notes
relation_type   TEXT  -- 'related_to' | 'extends' | 'contradicts' | 'depends_on'
score           FLOAT
```

### `notion_map`
```sql
topic_id        UUID REFERENCES topics
notion_page_id  TEXT
last_sync       TIMESTAMPTZ
```

---

## 📂 Project Structure

```
grain/
│
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app entry point
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py              # Environment variables & settings
│   │   └── logger.py              # Logging setup
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── health.py              # GET /health
│   │   ├── ingest.py              # POST /webhook, POST /ingest-note
│   │   ├── search.py              # POST /search
│   │   ├── graph.py               # GET /related-notes/{id}
│   │   └── facets.py              # GET /facets
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── understand.py          # Consolidated LLM understanding engine
│   │   ├── embedder.py            # Local sentence-transformers (BAAI/bge-small)
│   │   ├── entity_extractor.py    # Named entity extraction (LLM)
│   │   ├── topic_snapper.py       # Semantic topic deduplication
│   │   ├── retrieval_engine.py    # Hybrid search (vector + entities + graph)
│   │   ├── relation_engine.py     # Build graph edges between notes
│   │   ├── enrichment_engine.py   # Merge/evolve existing notes
│   │   ├── notion_sync.py         # Notion create/append + polling
│   │   └── scrapers/              # Web scraping package
│   │       ├── __init__.py        # URL detection + scraper router
│   │       ├── base.py            # Abstract BaseScraper
│   │       ├── twitter.py         # Nitter/Jina Twitter scraper
│   │       ├── youtube.py         # YouTube transcript scraper
│   │       ├── reddit.py          # Old Reddit/Jina scraper
│   │       ├── rss.py             # RSS feed scraper
│   │       ├── web.py             # Jina → trafilatura → BS4 fallback
│   │       └── search.py          # Brave search integration
│   │
│   ├── db/
│   │   ├── __init__.py
│   │   ├── supabase.py            # Supabase client init
│   │   ├── queries.py             # Reusable DB queries
│   │   └── migrations/
│   │       ├── 001_init.sql       # topics + notes tables
│   │       ├── 002_vectors.sql    # pgvector + embedding columns
│   │       ├── 003_graph.sql      # entities + note_entities + relations
│   │       ├── 004_search.sql     # match_notes pgvector function
│   │       ├── 005_notion_cols.sql# Notion sync tracking columns
│   │       └── 006_facets.sql     # JSONB facets column
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── note.py                # Pydantic: NoteInput, NoteOutput
│   │   ├── entity.py              # Pydantic: EntitySchema
│   │   ├── relation.py            # Pydantic: RelationOutput
│   │   └── topic.py               # Pydantic: TopicSchema
│   │
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── similarity.py          # Cosine similarity helpers
│   │   └── ranking.py             # Result ranking logic
│   │
│   └── integrations/
│       ├── __init__.py
│       ├── telegram.py            # Telegram Bot webhook handler
│       ├── notion.py              # Notion API client wrapper
│       └── gemini.py              # Unified LLM router (Gemini/Groq/NVIDIA)
│
├── tests/
│   ├── __init__.py
│   ├── test_ingest.py
│   ├── test_search.py
│   ├── test_notion_sync.py
│   └── test_scrapers.py           # Tests for scrapers module
│
├── .env.example                   # Environment variable template
├── .gitignore
├── requirements.txt
├── README.md
├── action_plan.md
├── srs.md
└── idea.md
```

---

## 🚀 Getting Started (after MVP is built)

```bash
# Clone the repo
git clone <your-repo-url>
cd grain

# Install dependencies
pip install -r requirements.txt

# Copy and fill environment variables
cp .env.example .env

# Run the server
uvicorn app.main:app --reload
```

---

## 📋 Roadmap

See [`action_plan.md`](./action_plan.md) for the full MVP and phased execution plan.

---

## 📄 License

Personal project. Not licensed for redistribution.
