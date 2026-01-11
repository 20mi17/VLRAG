from typing import Optional, Dict, List
from supabase_client import get_supabase_client

RPC_NAME = "search_chunks"

def search_chunks(
    query: str,
    top_k: int = 3,
    document_id: Optional[str] = None,
) -> List[Dict]:
    if not query.strip():
        return []

    sb = get_supabase_client()
    
    # 1. Run the vector/hybrid search RPC
    params = {"q": query, "k": top_k, "doc": document_id}
    res = sb.rpc(RPC_NAME, params).execute()
    results = res.data or []

    if not results:
        return []

    # 2. Extract unique Document IDs from the search results
    doc_ids = list(set(r['document_id'] for r in results if r.get('document_id')))

    if not doc_ids:
        return results

    # 3. Fetch Document Titles (file_names) from the 'documents' table
    # We need the title because 'Document URL Mapping' uses file_name, not UUID
    docs_res = sb.table("documents").select("id, title").in_("id", doc_ids).execute()
    
    # Map UUID -> Filename (e.g. "uuid-123" -> "page_1.txt")
    id_to_filename = {d['id']: d['title'] for d in docs_res.data}
    
    # 4. Fetch URLs from 'Document URL Mapping' table
    # Note: Using exact table name from your image
    filenames = list(id_to_filename.values())
    if filenames:
        url_res = sb.table("Document URL Mapping").select("file_name, url").in_("file_name", filenames).execute()
        
        # Map Filename -> URL
        filename_to_url = {u['file_name']: u['url'] for u in url_res.data}
    else:
        filename_to_url = {}

    # 5. Attach the URL to each search result
    for r in results:
        doc_uuid = r.get('document_id')
        filename = id_to_filename.get(doc_uuid)
        # If we found a mapping, attach it. Otherwise None.
        r['url'] = filename_to_url.get(filename)

    return results