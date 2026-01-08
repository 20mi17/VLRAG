from typing import Optional, Dict, List
from supabase_client import get_supabase_client

CHUNKS_TABLE = "chunks"
CHUNK_TEXT_COL = "content"
CHUNK_DOC_ID_COL = "document_id"
CHUNK_ID_COL = "id"
CHUNK_HEADING_COL = "section_heading"

def search_chunks(
    query: str,
    top_k: int = 3,
    document_id: Optional[str] = None,
) -> List[Dict]:
    if not query.strip():
        return []

    sb = get_supabase_client()

    qb = (
        sb.table(CHUNKS_TABLE)
        .select(f"{CHUNK_ID_COL},{CHUNK_DOC_ID_COL},{CHUNK_HEADING_COL},{CHUNK_TEXT_COL}")
        .ilike(CHUNK_TEXT_COL, f"%{query}%")
        .limit(top_k)
    )

    if document_id:
        qb = qb.eq(CHUNK_DOC_ID_COL, document_id)

    res = qb.execute()
    return res.data or []
