from fastapi import APIRouter, HTTPException
from documents_service import get_document

router = APIRouter(tags=["documents"])


@router.get("/document/{doc_id}")
def read_document(doc_id: str):
    """
    200: returns document JSON
    404: document not found
    500: internal supabase/other errors (sanitized)
    """
    try:
        doc = get_document(doc_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return doc
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")
