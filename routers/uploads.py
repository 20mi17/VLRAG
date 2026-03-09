from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from upload_service import (
    get_upload_details,
    list_uploads,
    promote_upload,
    reject_upload,
    rollback_upload,
    upload_and_stage_document,
)

router = APIRouter(tags=["uploads"])


class RejectRequest(BaseModel):
    reason: Optional[str] = None


@router.post("/uploads")
async def upload_document(file: UploadFile = File(...)):
    try:
        result = await upload_and_stage_document(file)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@router.get("/uploads")
def get_uploads():
    try:
        return {"uploads": list_uploads()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list uploads: {str(e)}")


@router.get("/uploads/{upload_id}")
def get_upload(upload_id: str):
    try:
        result = get_upload_details(upload_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Upload not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch upload: {str(e)}")


@router.post("/uploads/{upload_id}/promote")
def promote(upload_id: str):
    try:
        return promote_upload(upload_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Promotion failed: {str(e)}")


@router.post("/uploads/{upload_id}/reject")
def reject(upload_id: str, req: Optional[RejectRequest] = None):
    try:
        reason = req.reason if req else None
        return reject_upload(upload_id, reason)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reject failed: {str(e)}")


@router.post("/uploads/{upload_id}/rollback")
def rollback(upload_id: str):
    try:
        return rollback_upload(upload_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Rollback failed: {str(e)}")