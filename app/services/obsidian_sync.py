"""
Obsidian Sync — writes Grain notes as .md files to an Obsidian vault folder.

File structure:
  {OBSIDIAN_VAULT_PATH}/Grain/
    ├── {Topic} - {Title 40chars}.md
    ├── _index.md            # Smart index (topic clusters + facets + recent)
    ├── _entities.md
    └── _facets.md

Two-way sync is avoided deliberately: Obsidian is a read-only display layer.
Edits go through Telegram commands (/edit, /fact, /retitle, /delete).
"""

import logging
import os
import re
from pathlib import Path
from uuid import UUID
from datetime import datetime
from typing import List, Dict, Any, Optional

from app.core.config import settings
from app.db.supabase import supabase
from app.db.queries import get_note_by_id
from app.services.topic_snapper import compute_topic_centroid
from app.utils.similarity import cosine_similarity

logger = logging.getLogger("grain.obsidian")

# ── Shortcode helpers ────────────────────────────────────────────────────────

BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

def make_shortcode(note_id: UUID) -> str:
    """Derives a 6-character base62 code from a UUID for easy Telegram commands."""
    val = int(str(note_id).replace("-", "")[:12], 16)
    code = []
    for _ in range(6):
        code.append(BASE62[val % 62])
        val //= 62
    return "".join(reversed(code))

def resolve_shortcode(code: str, user_id: Optional[UUID] = None) -> Optional[UUID]:
    """Resolves a shortcode back to a UUID by checking all notes (O(n), but fast enough for personal use)."""
    try:
        query = supabase.table("notes").select("id")
        if user_id:
            query = query.eq("user_id", str(user_id))
        notes = query.execute()
        for row in (notes.data or []):
            if make_shortcode(UUID(row["id"])) == code:
                return UUID(row["id"])
    except Exception as e:
        logger.error(f"Failed to resolve shortcode {code}: {e}")
    return None

# ── Vault path ───────────────────────────────────────────────────────────────

def vault_dir() -> Path:
    """Returns the Grain subdirectory inside the Obsidian vault, creating it if needed."""
    base = Path(settings.OBSIDIAN_VAULT_PATH) / "Grain"
    base.mkdir(parents=True, exist_ok=True)
    return base

# ── Note filename ────────────────────────────────────────────────────────────

def _get_existing_wikilink_targets(user_id: Optional[UUID] = None) -> dict:
    """Returns a lookup: lowercase target → wikilink target for resolution.
    Only maps to actual note filenames — entities and facets are handled by tags, not separate pages."""
    targets = {}
    try:
        query = supabase.table("notes").select("id, title, topic_id")
        if user_id:
            query = query.eq("user_id", str(user_id))
        result = query.execute()
        topic_cache = {}
        for row in (result.data or []):
            title = row.get("title") or ""
            if not title:
                continue
            tid = row.get("topic_id")
            if tid and tid not in topic_cache:
                t_res = supabase.table("topics").select("name").eq("id", tid).execute()
                topic_cache[tid] = t_res.data[0]["name"] if t_res.data else "General"
            tn = topic_cache.get(tid, "General")
            filename = _note_filename(tn, title).replace(".md", "")
            targets[filename.lower()] = filename
            targets[title.lower()] = filename
    except Exception:
        pass
    return targets

def _sanitize_filename(name: str) -> str:
    """Strips or replaces characters that are invalid in filenames."""
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    name = name.strip(". ")
    return name[:80] or "Untitled"

def _note_filename(topic_name: str, note_title: str) -> str:
    """Returns a clean filename like 'VLSI Design - FinFET vs GAAFET.md'."""
    safe_topic = _sanitize_filename(topic_name)
    safe_title = _sanitize_filename(note_title)[:40]
    return f"{safe_topic} - {safe_title}.md"

# ── Markdown renderer ────────────────────────────────────────────────────────

def _render_markdown(
    note_id: UUID,
    topic_name: str,
    title: str,
    core_claim: Optional[str],
    facts: List[str],
    why_matters: Optional[str],
    status: Optional[str],
    links_to: Optional[str],
    entities: List[Dict[str, str]],
    facets: Dict[str, List[str]],
    source_url: Optional[str],
    source_type: str,
    personal_insight: Optional[str],
    raw_text: str,
    created_at: datetime,
    user_id: Optional[UUID] = None,
) -> str:
    """
    Renders a complete .md file with YAML frontmatter and Knowledge Card body.
    
    Obsidian features leveraged:
      - [[wikilinks]] → graph view, backlinks
      - #status/tags  → color-coded graph nodes, filtering
      - YAML frontmatter → Dataview queries
    """
    shortcode = make_shortcode(note_id)

    # ── Build tags ───────────────────────────────────────────────────────
    tags = []
    if status:
        tags.append(f"status/{status.lower().replace(' ', '-')}")
    for key, values in (facets or {}).items():
        for val in values:
            tags.append(f"{key}/{val.lower().replace(' ', '-')}")

    # ── Build entities list for frontmatter ────────────────────────────────
    entity_names = [e.get("name", "") for e in (entities or []) if e.get("name")]

    # ── Smart backlinking: wikilink targets that exist as notes or entities ──
    existing_targets = _get_existing_wikilink_targets(user_id=user_id)

    # ── Build body ────────────────────────────────────────────────────────
    body_parts = []

    if core_claim:
        body_parts.append(f"**Core:** {core_claim}")

    if facts:
        body_parts.append("\n**Facts:**")
        for f in facts:
            body_parts.append(f"- {f}")

    if why_matters:
        body_parts.append(f"\n**Why This Matters:** {why_matters}")

    if status:
        body_parts.append(f"\n**Status:** {status}")

    # Convert links_to to Obsidian wikilinks — resolve to actual filenames
    if links_to:
        wikilinks = []
        for ref in links_to.split(","):
            ref = ref.strip()
            clean_ref = ref.strip("*")
            target = existing_targets.get(clean_ref.lower())
            if target:
                wikilinks.append(f"[[{target}]]")
            elif ref:
                wikilinks.append(ref)
        if wikilinks:
            body_parts.append(f"\n**Links To:** {', '.join(wikilinks)}")

    if personal_insight:
        body_parts.append(f"\n> 💡 {personal_insight}")

    if source_url:
        body_parts.append(f"\n🔗 **Source:** {source_url}")

    # ── Original content in collapsible callout ─────────────────────────
    if raw_text:
        # Prefix each line with "> " for Obsidian callout syntax
        escaped = raw_text.replace("\n", "\n> ")
        body_parts.append(f"\n> [!note]- 📝 Original\n> *{escaped}*")

    body = "\n".join(body_parts)

    # ── Build YAML frontmatter ────────────────────────────────────────────
    frontmatter_lines = [
        "---",
        f"grain_id: \"{shortcode}\"",
        f"title: \"{title}\"",
        f"aliases: [{shortcode}]",
        f"topic: \"{topic_name}\"",
        f"created: {created_at.isoformat()}",
        f"source_type: {source_type}",
    ]
    if source_url:
        frontmatter_lines.append(f"source_url: \"{source_url}\"")
    if status:
        frontmatter_lines.append(f"status: \"{status}\"")
    if entity_names:
        frontmatter_lines.append(f"entities:")
        for en in entity_names:
            frontmatter_lines.append(f"  - \"{en}\"")
    if tags:
        frontmatter_lines.append(f"tags: [{', '.join(tags)}]")
    frontmatter_lines.append("---")

    return "\n".join(frontmatter_lines) + "\n\n" + body


# ── Main sync function ───────────────────────────────────────────────────────

async def sync_note_to_obsidian(note_id: UUID, user_id: Optional[UUID] = None) -> None:
    """
    Fetches a note from Supabase and writes/overwrites its .md file in the vault.
    Also regenerates indexes (MOC, entities, facets).
    """
    logger.info(f"Syncing note {note_id} to Obsidian...")
    try:
        note = get_note_by_id(note_id)
        if not note:
            logger.error(f"Note {note_id} not found. Skipping Obsidian sync.")
            return

        # Fetch topic
        topic_res = supabase.table("topics").select("name").eq("id", str(note.topic_id)).execute()
        topic_name = topic_res.data[0]["name"] if topic_res.data else "General"

        # Fetch entities linked to this note
        entities_res = supabase.table("note_entities")\
            .select("entities(name, type)")\
            .eq("note_id", str(note_id))\
            .execute()
        entities = []
        for row in (entities_res.data or []):
            if row.get("entities"):
                entities.append({"name": row["entities"]["name"], "type": row["entities"].get("type", "concept")})

        # Strip trailing source line from summary before parsing
        raw_summary = note.summary or ""
        if "\U0001f517" in raw_summary:
            raw_summary = raw_summary.split("\U0001f517")[0].strip()

        # Derive title — use stored title, fall back to **Core:** line, then first line of raw_text
        title = (note.title or "").strip()
        if not title and raw_summary:
            # Try structured **Core:** header first
            for line in raw_summary.split("\n"):
                line = line.strip()
                if line.startswith("**Core:**"):
                    title = line[len("**Core:**"):].strip()[:60]
                    break
            # If no structured card, use first non-empty line of raw_text
            if not title and note.raw_text:
                for line in note.raw_text.split("\n"):
                    line = line.strip()
                    if line and not line.startswith(("http://", "https://")):
                        title = line[:60]
                        break
        if not title:
            title = "Untitled"
        title = title.rstrip(".!?")

        # Parse the Knowledge Card summary into fields
        core_claim = None
        facts = []
        why_matters = None
        note_status = None
        links_to = None
        if raw_summary:
            current_section = None
            for line in raw_summary.split("\n"):
                line = line.strip()
                if line.startswith("**Core:**"):
                    core_claim = line[len("**Core:**"):].strip()
                elif line.startswith("**Facts:**"):
                    current_section = "facts"
                elif line.startswith("**Why This Matters:**"):
                    current_section = "why"
                    why_matters = line[len("**Why This Matters:**"):].strip()
                elif line.startswith("**Status:**"):
                    current_section = "status"
                    note_status = line[len("**Status:**"):].strip()
                elif line.startswith("**Links To:**"):
                    current_section = "links"
                    links_to = line[len("**Links To:**"):].strip()
                elif current_section == "facts" and line and not line.startswith("**"):
                    # Strip bullet markers
                    fact = line.lstrip("•- ").strip()
                    if fact:
                        facts.append(fact)
                else:
                    current_section = None

        # Fallback for plain-text summaries (no Knowledge Card headers)
        if not core_claim and not facts and raw_summary:
            core_claim = raw_summary

        # Write the .md file
        content = _render_markdown(
            note_id=note_id,
            topic_name=topic_name,
            title=title,
            core_claim=core_claim,
            facts=facts,
            why_matters=why_matters,
            status=note_status,
            links_to=links_to,
            entities=entities,
            facets=note.facets or {},
            source_url=note.source_url,
            source_type=note.source_type or "manual",
            personal_insight=note.personal_insight,
            raw_text=note.raw_text,
            created_at=note.created_at,
            user_id=user_id,
        )

        out_path = vault_dir() / _note_filename(topic_name, title)
        out_path.write_text(content, encoding="utf-8")
        logger.info(f"Wrote {len(content)} bytes to {out_path}")

        # Regenerate indexes
        _sync_indexes(user_id=user_id)

    except Exception as e:
        logger.error(f"Obsidian sync failed for note {note_id}: {e}", exc_info=True)


async def delete_note_from_obsidian(note_id: UUID, user_id: Optional[UUID] = None) -> bool:
    """Removes a note's .md file from the vault. Returns True if deleted."""
    try:
        note = get_note_by_id(note_id)
        if not note:
            return False

        topic_res = supabase.table("topics").select("name").eq("id", str(note.topic_id)).execute()
        topic_name = topic_res.data[0]["name"] if topic_res.data else "General"

        title = (note.title or "").strip() or "Untitled"

        out_path = vault_dir() / _note_filename(topic_name, title)
        if out_path.exists():
            out_path.unlink()
            logger.info(f"Deleted Obsidian file {out_path}")
            _sync_indexes()
            return True
    except Exception as e:
        logger.error(f"Failed to delete Obsidian file for note {note_id}: {e}")
    return False


# ── Index generation ─────────────────────────────────────────────────────────

def _get_all_notes() -> List[Dict[str, Any]]:
    """Fetches all notes with their topic name from Supabase."""
    try:
        # Try with facets first, fall back if column doesn't exist
        result = supabase.table("notes").select("id, title, summary, topic_id, facets, created_at, source_type").execute()
        notes = result.data or []
    except Exception:
        try:
            result = supabase.table("notes").select("id, title, summary, topic_id, created_at, source_type").execute()
            notes = result.data or []
        except Exception as e:
            logger.error(f"Failed to fetch notes for index: {e}")
            return []
    try:
        # Enrich with topic names
        topics_cache = {}
        for note in notes:
            tid = note.get("topic_id")
            if tid and tid not in topics_cache:
                t_res = supabase.table("topics").select("name").eq("id", tid).execute()
                topics_cache[tid] = t_res.data[0]["name"] if t_res.data else "General"
            note["topic_name"] = topics_cache.get(tid, "General")
            display = note.get("title") or ""
            if not display:
                summary = note.get("summary", "") or ""
                for line in summary.split("\n"):
                    line = line.strip()
                    if line.startswith("**Core:**"):
                        display = line[len("**Core:**"):].strip()
                        break
                if not display:
                    first_line = summary.split("\n")[0].strip()
                    display = first_line or "No core claim"
            display = display.rstrip(".!?")
            note["display_name"] = display
        return notes
    except Exception as e:
        logger.error(f"Failed to fetch notes for index: {e}")
        return []


def _sync_indexes() -> None:
    """Regenerates _index.md (smart), _entities.md, and _facets.md."""
    try:
        _generate_smart_index()
        logger.info("Regenerated smart index.")
    except Exception as e:
        logger.error(f"Failed to generate smart index: {e}")

    try:
        _generate_entity_index()
        logger.info("Regenerated entity index.")
    except Exception as e:
        logger.error(f"Failed to generate entity index: {e}")

    try:
        _generate_facet_index()
        logger.info("Regenerated facet index.")
    except Exception as e:
        logger.error(f"Failed to generate facet index: {e}")


def _generate_smart_index() -> None:
    """
    Generates _index.md — a smart table of contents.

    Features:
      - Topic clusters: related topics grouped by cosine similarity (threshold ≥ 0.7)
      - Notes listed under their topics within each cluster
      - Facet sections for browsing by subject, category, location
      - Recent notes list (last 20)
    """
    notes = _get_all_notes()

    # Fetch topics with embeddings
    try:
        topics_raw = supabase.table("topics").select("id, name, embedding").execute()
        topics = topics_raw.data or []
    except Exception as e:
        logger.error(f"Failed to fetch topics for smart index: {e}")
        topics = []

    # Resolve the best embedding for each topic:
    #   - 1st choice: centroid of all notes under the topic (semantic content)
    #   - 2nd choice: topic name embedding (fallback for empty topics)
    #   - 3rd choice: None (no data at all)
    for t in topics:
        centroid = compute_topic_centroid(UUID(t["id"])) if t.get("id") else None
        if centroid:
            t["embedding"] = centroid
        else:
            # Fall back to the topic's own name embedding
            if isinstance(t.get("embedding"), str):
                try:
                    raw = t["embedding"].strip("[]")
                    t["embedding"] = [float(x) for x in raw.split(",") if x.strip()]
                except (ValueError, AttributeError):
                    t["embedding"] = None

    def _has_embedding(t):
        return bool(t.get("embedding"))

    # ── Cluster topics by centroid similarity ────────────────────────────
    cluster_threshold = settings.CLUSTER_THRESHOLD
    clusters = []
    visited = set()

    for i, t1 in enumerate(topics):
        if i in visited or not _has_embedding(t1):
            continue
        cluster_topics = [t1]
        visited.add(i)
        for j, t2 in enumerate(topics):
            if j in visited or not _has_embedding(t2):
                continue
            sim = cosine_similarity(t1["embedding"], t2["embedding"])
            if sim >= cluster_threshold:
                cluster_topics.append(t2)
                visited.add(j)
        cluster_topics.sort(key=lambda t: t.get("name", ""))
        clusters.append(cluster_topics)

    clusters.sort(key=lambda c: c[0].get("name", ""))

    # Unclustered topics (no embedding or no match)
    all_clustered_ids = {ct.get("id") for c in clusters for ct in c}
    unclustered = [t for t in topics if t.get("id") and t["id"] not in all_clustered_ids]
    unclustered.sort(key=lambda t: t.get("name", ""))
    no_embedding = [t for t in unclustered if not _has_embedding(t)]
    unclustered_only = [t for t in unclustered if _has_embedding(t)]

    # Build topic_id to notes lookup
    notes_by_topic: Dict[str, List[Dict]] = {}
    for note in notes:
        tid = note.get("topic_id")
        notes_by_topic.setdefault(tid, []).append(note)

    # Build facet lookup
    notes_by_facet: Dict[str, Dict[str, List[Dict]]] = {}
    for note in notes:
        facets = note.get("facets") or {}
        if isinstance(facets, dict):
            for key, values in facets.items():
                if isinstance(values, list):
                    notes_by_facet.setdefault(key, {})
                    for val in values:
                        v = val.strip()
                        if v:
                            notes_by_facet[key].setdefault(v, []).append(note)

    # ── Assemble the index ───────────────────────────────────────────────
    lines = ["# Smart Index\n"]

    def _index_wikilink(note: dict) -> str:
        """Build a wikilink that uses the actual filename so Obsidian can resolve it."""
        tn = note.get("topic_name", "General")
        display = note.get("display_name", "Untitled")
        filename = _note_filename(tn, display).replace(".md", "")
        return f"[[{filename}|{display[:60]}]]"

    # ── Section: Topic Clusters ──────────────────────────────────────────
    lines.append("## 📂 Related Topic Clusters\n")
    lines.append("_Topics grouped by semantic similarity._\n")

    cluster_ids = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]
    for idx, cluster in enumerate(clusters):
        topic_names = [t.get("name", "?") for t in cluster]
        label = cluster_ids[idx] if idx < len(cluster_ids) else f"{idx + 1}"
        lines.append(f"### Cluster {label}: {', '.join(topic_names)}\n")
        for t in cluster:
            t_name = t.get("name", "?")
            lines.append(f"**{t_name}**\n")
            t_notes = notes_by_topic.get(t.get("id"), [])
            t_notes.sort(key=lambda n: n.get("created_at", "") or "", reverse=True)
            for note in t_notes:
                sc = make_shortcode(UUID(note["id"]))
                lines.append(f"  - {_index_wikilink(note)} — `{sc}`\n")
            lines.append("\n")

    if unclustered_only:
        lines.append("### Unclustered Topics\n")
        for t in unclustered_only:
            t_name = t.get("name", "?")
            lines.append(f"**{t_name}**\n")
            t_notes = notes_by_topic.get(t.get("id"), [])
            t_notes.sort(key=lambda n: n.get("created_at", "") or "", reverse=True)
            for note in t_notes:
                sc = make_shortcode(UUID(note["id"]))
                lines.append(f"  - {_index_wikilink(note)} — `{sc}`\n")
            lines.append("\n")

    if no_embedding:
        lines.append("### Other Topics\n")
        for t in no_embedding:
            t_name = t.get("name", "?")
            lines.append(f"**{t_name}**\n")
            t_notes = notes_by_topic.get(t.get("id"), [])
            t_notes.sort(key=lambda n: n.get("created_at", "") or "", reverse=True)
            for note in t_notes:
                sc = make_shortcode(UUID(note["id"]))
                lines.append(f"  - {_index_wikilink(note)} — `{sc}`\n")
            lines.append("\n")

    # ── Section: Facet Browse ────────────────────────────────────────────
    for key in ("subject", "category", "location"):
        if key not in notes_by_facet:
            continue
        lines.append(f"## 🏷️ By {key.capitalize()}\n")
        for val in sorted(notes_by_facet[key].keys()):
            f_notes = notes_by_facet[key][val]
            # Deduplicate notes that may appear under multiple values
            seen = set()
            lines.append(f"**{val}**\n")
            for note in f_notes:
                if note["id"] in seen:
                    continue
                seen.add(note["id"])
                sc = make_shortcode(UUID(note["id"]))
                lines.append(f"  - {_index_wikilink(note)} — `{sc}`\n")
            lines.append("\n")

    # ── Section: Recent Notes ────────────────────────────────────────────
    lines.append("## 🕐 Recent Notes\n")
    all_sorted = sorted(notes, key=lambda n: n.get("created_at", "") or "", reverse=True)
    for note in all_sorted[:20]:
        sc = make_shortcode(UUID(note["id"]))
        tn = note.get("topic_name", "General")
        lines.append(f"- {_index_wikilink(note)} — `{sc}` — *{tn}*\n")

    out_path = vault_dir() / "_index.md"
    out_path.write_text("".join(lines), encoding="utf-8")
    logger.info(f"Wrote smart index ({len(lines)} lines) to {out_path}")


def _generate_entity_index() -> None:
    """Generates _entities.md — all extracted entities grouped by type."""
    try:
        entities_res = supabase.table("entities").select("id, name, type").execute()
        entities = entities_res.data or []

        by_type: Dict[str, List[str]] = {}
        for ent in entities:
            et = ent.get("type", "concept")
            by_type.setdefault(et, []).append(ent.get("name", ""))

        lines = ["# Entity Index\n"]
        for etype in sorted(by_type.keys()):
            lines.append(f"\n## {etype.capitalize()}s\n")
            for name in sorted(by_type[etype]):
                lines.append(f"- [[{name}]]")

        out_path = vault_dir() / "_entities.md"
        out_path.write_text("\n".join(lines), encoding="utf-8")
    except Exception as e:
        logger.error(f"Entity index generation failed: {e}")


def _generate_facet_index() -> None:
    """Generates _facets.md — all facet values grouped by facet key."""
    notes = _get_all_notes()
    by_facet: Dict[str, set] = {}
    for note in notes:
        facets = note.get("facets") or {}
        if isinstance(facets, dict):
            for key, values in facets.items():
                if isinstance(values, list):
                    by_facet.setdefault(key, set()).update(v.strip() for v in values if v)

    lines = ["# Facet Index\n"]
    for key in sorted(by_facet.keys()):
        lines.append(f"\n## {key.capitalize()}\n")
        for val in sorted(by_facet[key]):
            lines.append(f"- [[{val}]]")

    out_path = vault_dir() / "_facets.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")


def _generate_entity_pages() -> None:
    """Generates individual .md files for each entity so [[wikilinks]] resolve."""
    try:
        entities_res = supabase.table("entities").select("id, name, type").execute()
        entities = entities_res.data or []
    except Exception as e:
        logger.error(f"Failed to fetch entities for pages: {e}")
        return

    for ent in entities:
        name = ent.get("name", "")
        ent_type = ent.get("type", "concept")
        if not name:
            continue

        # Fetch notes linked to this entity
        try:
            ne_res = supabase.table("note_entities")\
                .select("note_id")\
                .eq("entity_id", ent["id"])\
                .execute()
            note_ids = [row["note_id"] for row in (ne_res.data or [])]
        except Exception:
            note_ids = []

        # Build note links
        links_block = ""
        if note_ids:
            links_block = "\n## Linked Notes\n\n"
            for nid in note_ids[:20]:
                try:
                    note = supabase.table("notes").select("title, topic_id").eq("id", nid).single().execute()
                    if note.data:
                        title = note.data.get("title") or "Untitled"
                        tid = note.data.get("topic_id")
                        tn = "General"
                        if tid:
                            t_res = supabase.table("topics").select("name").eq("id", tid).execute()
                            tn = t_res.data[0]["name"] if t_res.data else "General"
                        sc = make_shortcode(UUID(nid))
                        filename = _note_filename(tn, title).replace(".md", "")
                        links_block += f"- [[{filename}|{title[:80]}]] — `{sc}`\n"
                except Exception:
                    pass

        content = (
            f"---\n"
            f"entity_name: \"{name}\"\n"
            f"type: \"{ent_type}\"\n"
            f"---\n\n"
            f"# {name}\n\n"
            f"_Entity type: #{ent_type}_\n\n"
            f"{links_block}"
        )

        out_path = vault_dir() / f"{_sanitize_filename(name)}.md"
        try:
            out_path.write_text(content, encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to write entity page {name}: {e}")

    logger.info(f"Generated {len(entities)} entity pages.")


def _generate_facet_pages() -> None:
    """Generates individual .md files for each facet value so [[wikilinks]] resolve."""
    notes = _get_all_notes()
    by_facet: Dict[str, Dict[str, List[str]]] = {}
    for note in notes:
        facets = note.get("facets") or {}
        if isinstance(facets, dict):
            for key, values in facets.items():
                if isinstance(values, list):
                    fm = by_facet.setdefault(key, {})
                    for val in values:
                        v = val.strip()
                        if v:
                            fm.setdefault(v, []).append(note["id"])

    for facet_key, value_map in by_facet.items():
        for val, nids in value_map.items():
            links_block = "\n## Linked Notes\n\n"
            for nid in nids[:20]:
                note = next((n for n in notes if n.get("id") == nid), None)
                if note:
                    sc = make_shortcode(UUID(nid))
                    tn = note.get("topic_name", "General")
                    display = note.get("display_name", "Untitled")
                    filename = _note_filename(tn, display).replace(".md", "")
                    links_block += f"- [[{filename}|{display[:80]}]] — `{sc}`\n"

            content = (
                f"---\n"
                f"facet_key: \"{facet_key}\"\n"
                f"facet_value: \"{val}\"\n"
                f"---\n\n"
                f"# {val}\n\n"
                f"_Facet: #{facet_key}_\n\n"
                f"{links_block}"
            )

            out_path = vault_dir() / f"{_sanitize_filename(val)}.md"
            try:
                out_path.write_text(content, encoding="utf-8")
            except Exception as e:
                logger.warning(f"Failed to write facet page {val}: {e}")

    total = sum(len(vm) for vm in by_facet.values())
    logger.info(f"Generated {total} facet pages.")
