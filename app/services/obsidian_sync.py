"""
Obsidian Sync — writes Grain notes as .md files to an Obsidian vault folder.

File structure:
  {OBSIDIAN_VAULT_PATH}/Grain/
    ├── {Topic} - {Title 40chars}.md
    ├── _MOC.md
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

def resolve_shortcode(code: str) -> Optional[UUID]:
    """Resolves a shortcode back to a UUID by checking all notes (O(n), but fast enough for personal use)."""
    try:
        notes = supabase.table("notes").select("id").execute()
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

    # ── Build body ────────────────────────────────────────────────────────
    body_parts = []

    if core_claim:
        body_parts.append(f"**Core:** {core_claim}")

    if facts:
        body_parts.append("**Facts:**")
        for f in facts:
            body_parts.append(f"- {f}")

    if why_matters:
        body_parts.append(f"**Why This Matters:** {why_matters}")

    if status:
        body_parts.append(f"**Status:** {status}")

    # Convert links_to to Obsidian wikilinks
    if links_to:
        wikilinks = ", ".join(
            f"[[{ref.strip()}]]" for ref in links_to.split(",") if ref.strip()
        )
        body_parts.append(f"**Links To:** {wikilinks}")

    # Convert entities in body to wikilinks too
    for ename in entity_names:
        body_parts.append(f"See also: [[{ename}]]")

    if personal_insight:
        body_parts.append(f"\n> 💡 {personal_insight}")

    if source_url:
        body_parts.append(f"\n🔗 Source: {source_url}")

    body = "\n".join(body_parts)

    # ── Build YAML frontmatter ────────────────────────────────────────────
    # Manual YAML to avoid pyyaml dependency for a simple case
    frontmatter_lines = [
        "---",
        f"grain_id: \"{shortcode}\"",
        f"title: \"{title}\"",
        f"topic: \"{topic_name}\"",
        f"created: {created_at.isoformat()}",
        f"source_type: {source_type}",
    ]
    if source_url:
        frontmatter_lines.append(f"source_url: \"{source_url}\"")
    if entity_names:
        frontmatter_lines.append(f"entities:")
        for en in entity_names:
            frontmatter_lines.append(f"  - \"{en}\"")
    if tags:
        frontmatter_lines.append(f"tags: [{', '.join(tags)}]")
    frontmatter_lines.append("---")

    return "\n".join(frontmatter_lines) + "\n\n" + body


# ── Main sync function ───────────────────────────────────────────────────────

async def sync_note_to_obsidian(note_id: UUID) -> None:
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

        # Derive title from the **Core:** line of the summary
        title = "Untitled"
        if note.summary:
            for line in note.summary.split("\n"):
                line = line.strip()
                if line.startswith("**Core:**"):
                    title = line[len("**Core:**"):].strip()[:60]
                    break
            if not title or title == "Untitled":
                first_line = note.summary.split("\n")[0]
                title = first_line.replace("**Core:**", "").strip()[:60] or "Untitled"
            title = title.rstrip(".!?")

        # Parse the Knowledge Card summary into fields
        core_claim = None
        facts = []
        why_matters = None
        note_status = None
        links_to = None
        if note.summary:
            current_section = None
            for line in note.summary.split("\n"):
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
        )

        out_path = vault_dir() / _note_filename(topic_name, title)
        out_path.write_text(content, encoding="utf-8")
        logger.info(f"Wrote {len(content)} bytes to {out_path}")

        # Regenerate indexes
        _sync_indexes()

    except Exception as e:
        logger.error(f"Obsidian sync failed for note {note_id}: {e}", exc_info=True)


async def delete_note_from_obsidian(note_id: UUID) -> bool:
    """Removes a note's .md file from the vault. Returns True if deleted."""
    try:
        note = get_note_by_id(note_id)
        if not note:
            return False

        topic_res = supabase.table("topics").select("name").eq("id", str(note.topic_id)).execute()
        topic_name = topic_res.data[0]["name"] if topic_res.data else "General"

        title = "Untitled"
        if note.summary:
            first_line = note.summary.split("\n")[0]
            title = first_line.replace("**Core:**", "").strip()[:60]

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
        result = supabase.table("notes").select("id, summary, topic_id, facets, created_at, source_type").execute()
        notes = result.data or []
        # Enrich with topic names
        topics_cache = {}
        for note in notes:
            tid = note.get("topic_id")
            if tid and tid not in topics_cache:
                t_res = supabase.table("topics").select("name").eq("id", tid).execute()
                topics_cache[tid] = t_res.data[0]["name"] if t_res.data else "General"
            note["topic_name"] = topics_cache.get(tid, "General")
            # Extract core claim
            summary = note.get("summary", "") or ""
            core = ""
            for line in summary.split("\n"):
                line = line.strip()
                if line.startswith("**Core:**"):
                    core = line[len("**Core:**"):].strip()
                    break
            note["core"] = core
        return notes
    except Exception as e:
        logger.error(f"Failed to fetch notes for index: {e}")
        return []


def _sync_indexes() -> None:
    """Regenerates _MOC.md, _entities.md, and _facets.md."""
    try:
        _generate_moc()
        logger.info("Regenerated MOC index.")
    except Exception as e:
        logger.error(f"Failed to generate MOC: {e}")

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


def _generate_moc() -> None:
    """Generates _MOC.md — a Table of Contents grouped by topic."""
    notes = _get_all_notes()
    by_topic: Dict[str, List[Dict]] = {}
    for note in notes:
        tn = note.get("topic_name", "General")
        by_topic.setdefault(tn, []).append(note)

    lines = ["# Map of Content (MOC)\n"]
    for topic in sorted(by_topic.keys()):
        lines.append(f"\n## {topic}\n")
        for note in by_topic[topic]:
            core = note.get("core", "") or "No core claim"
            shortcode = make_shortcode(UUID(note["id"]))
            lines.append(f"- [[{core[:60]}]] — `{shortcode}`")

    out_path = vault_dir() / "_MOC.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")


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
