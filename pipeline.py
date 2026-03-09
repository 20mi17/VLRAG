import json
from typing import Any, Dict, List, Optional

from openai import OpenAI

from config import get_settings
from supabase_client import get_supabase_client

settings = get_settings()


def _get_openai_client() -> OpenAI:
    """
    Lazily create the OpenAI client only when needed.
    This prevents app startup/import failures when OpenAI is disabled or misconfigured.
    """
    if not settings.has_openai:
        raise RuntimeError("OpenAI is not configured. Missing OPENAI_API_KEY.")
    return OpenAI(api_key=settings.openai_api_key)


def clean_json_response(content: str) -> str:
    """
    Strip markdown code fences if the model wraps JSON in them.
    """
    content = content.strip()

    if content.startswith("```json"):
        content = content[len("```json"):].strip()
    elif content.startswith("```"):
        content = content[len("```"):].strip()

    if content.endswith("```"):
        content = content[:-3].strip()

    return content


def limit_to_first_n_pages(text: str, n_pages: int) -> str:
    """
    Best-effort helper for text files that may already contain page markers.
    If no obvious page markers exist, this just returns the full text.
    """
    if not text or n_pages <= 0:
        return ""

    page_markers = ["\f", "\nPage ", "\nPAGE "]

    marker_positions = []
    for marker in page_markers:
        start = 0
        while True:
            idx = text.find(marker, start)
            if idx == -1:
                break
            marker_positions.append(idx)
            start = idx + len(marker)

    marker_positions = sorted(set(marker_positions))

    if len(marker_positions) < n_pages:
        return text

    cutoff_index = marker_positions[n_pages - 1]
    return text[:cutoff_index].strip()


def detect_headings(text: str) -> List[Dict[str, Any]]:
    """
    Use the LLM to detect headings. If OpenAI is disabled or anything fails,
    return [] so the document becomes a single General chunk.
    """
    if not text.strip():
        return []

    if not settings.has_openai:
        return []

    prompt = f"""
Analyze this clinical document and identify all headings and their hierarchy.
Return a strictly valid JSON array of objects with these exact keys:
"heading_text", "level" (integer 1-3), and "start_position" (integer index).

It's very possible you will encounter an initial list of all chapter headings -
ignore that and look for the actual headings, likely with new lines before and after.

Document:
{text[:5000]}
""".strip()

    try:
        client = _get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content or ""
        cleaned_content = clean_json_response(content)
        data = json.loads(cleaned_content)

        if isinstance(data, dict):
            for _, value in data.items():
                if isinstance(value, list):
                    data = value
                    break

        if not isinstance(data, list):
            return []

        validated_data: List[Dict[str, Any]] = []
        for item in data:
            if (
                isinstance(item, dict)
                and "heading_text" in item
                and "start_position" in item
            ):
                validated_data.append(
                    {
                        "heading_text": str(item.get("heading_text", "Untitled")),
                        "level": int(item.get("level", 1)),
                        "start_position": int(item.get("start_position", 0)),
                    }
                )

        validated_data.sort(key=lambda x: x["start_position"])
        return validated_data

    except Exception as e:
        print(f"Warning: heading detection failed ({e}). Treating as single chunk.")
        return []


def chunk_by_headings(text: str, headings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Split document into chunks based on detected headings.
    Falls back to one General chunk if no headings are available.
    """
    if not text.strip():
        return []

    if not headings:
        return [
            {
                "heading": "General",
                "level": 1,
                "content": text,
                "position": 0,
            }
        ]

    chunks: List[Dict[str, Any]] = []

    for i, heading in enumerate(headings):
        start = max(0, int(heading.get("start_position", 0)))

        if i < len(headings) - 1:
            end = max(start, int(headings[i + 1].get("start_position", len(text))))
        else:
            end = len(text)

        chunk_content = text[start:end].strip()
        if not chunk_content:
            continue

        chunks.append(
            {
                "heading": heading.get("heading_text", "Untitled"),
                "level": int(heading.get("level", 1)),
                "content": chunk_content,
                "position": i,
            }
        )

    if not chunks:
        return [
            {
                "heading": "General",
                "level": 1,
                "content": text,
                "position": 0,
            }
        ]

    return chunks


def summarize_chunk(content: str, heading: str) -> str:
    """
    Generate summary for a section using LLM.
    Falls back to truncated content if OpenAI is unavailable.
    """
    if not content.strip():
        return ""

    if not settings.has_openai:
        return content[:500]

    prompt = f"""
Summarize this clinical guideline section concisely in 2-3 sentences.
Focus on key clinical information, treatments, or recommendations.

Section: {heading}
Content: {content[:2000]}
""".strip()

    try:
        client = _get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
        )
        return (response.choices[0].message.content or "").strip() or content[:500]
    except Exception as e:
        print(f"Warning: chunk summarization failed for '{heading}' ({e}). Using fallback.")
        return content[:500]


def create_chapter_summary(section_summaries: List[str], chapter_name: str) -> str:
    """
    Create chapter-wide summary from section summaries.
    Falls back safely if OpenAI is unavailable.
    """
    cleaned_summaries = [s.strip() for s in section_summaries if s and s.strip()]
    if not cleaned_summaries:
        return ""

    if not settings.has_openai:
        return "\n\n".join(cleaned_summaries)[:1000]

    combined = "\n".join(cleaned_summaries)

    prompt = f"""
Create a concise chapter summary from these section summaries.

Chapter: {chapter_name}
Section summaries:
{combined}
""".strip()

    try:
        client = _get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
        )
        return (response.choices[0].message.content or "").strip() or combined[:1000]
    except Exception as e:
        print(f"Warning: chapter summary failed for '{chapter_name}' ({e}). Using fallback.")
        return combined[:1000]


def process_document(text: str, filename: str, source: str) -> None:
    """
    Main pipeline: process text content and insert it into the production tables.
    """
    print(f"Processing {filename}...")

    sb = get_supabase_client()

    doc_response = sb.table("documents").insert(
        {
            "title": filename,
            "source": source,
        }
    ).execute()

    if not getattr(doc_response, "data", None):
        print(f"Error creating document record for {filename}")
        return

    doc_id = doc_response.data[0]["id"]

    headings = detect_headings(text)
    print(f"  - Detected {len(headings)} headings")

    chunks = chunk_by_headings(text, headings)
    print(f"  - Created {len(chunks)} chunks")

    chapters: Dict[str, List[Dict[str, Any]]] = {}
    current_chapter = "General"

    for chunk in chunks:
        if chunk["level"] == 1:
            current_chapter = chunk["heading"]
            chapters[current_chapter] = []
        elif current_chapter not in chapters:
            chapters[current_chapter] = []

        chapters[current_chapter].append(chunk)

    print("  - Generating summaries...")

    for chapter_name, chapter_chunks in chapters.items():
        if not chapter_chunks:
            continue

        section_summaries: List[str] = []

        for chunk in chapter_chunks:
            try:
                summary = summarize_chunk(chunk["content"], chunk["heading"])
                section_summaries.append(summary)

                sb.table("chunks").insert(
                    {
                        "document_id": doc_id,
                        "section_heading": chunk["heading"],
                        "content": chunk["content"],
                        "summary": summary,
                        "position_in_doc": chunk["position"],
                    }
                ).execute()

            except Exception as e:
                print(f"Error processing chunk '{chunk['heading']}': {e}")

        if section_summaries:
            chapter_summary = create_chapter_summary(section_summaries, chapter_name)

            for chunk in chapter_chunks:
                sb.table("chunks").update(
                    {"chapter_summary": chapter_summary}
                ).match(
                    {
                        "document_id": doc_id,
                        "section_heading": chunk["heading"],
                    }
                ).execute()

    print(f"✓ Processed {filename}")