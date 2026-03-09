from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from lang_pipeline import run_pipeline

router = APIRouter(tags=["rag"])

class RagRequest(BaseModel):
    query: str = Field(..., min_length=1)
    document_id: Optional[str] = None

@router.post("/rag")
def rag(req: RagRequest):
    try:
        out = run_pipeline(req.query, req.document_id)
        return out
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"RAG failed: {str(e)}")
