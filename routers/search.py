from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from search_service import search_chunks

router = APIRouter(tags=["search"])

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(3, ge=1, le=20)
    document_id: Optional[str] = None

@router.post("/search")
def search(req: SearchRequest):
    try:
        results = search_chunks(req.query, req.top_k, req.document_id)
        return {"query": req.query, "results": results}
    except Exception:
        raise HTTPException(status_code=500, detail="Search failed")
