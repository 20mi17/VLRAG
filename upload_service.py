import io
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from docx import Document
from fastapi import HTTPException, UploadFile
from pypdf import PdfReader

from config import get_settings
from pipeline import (
    chunk_by_headings,
    create_chapter_summary,
    detect_headings,
    summarize_chunk,
)
from supabase_client import get_supabase_client


settings = get_settings()

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_filename(filename: str) -> str:
    keep = {"-", "_", ".", " "}
    cleaned = "".join(ch for ch in filename if ch.isalnum() or ch in keep).strip()
    return cleaned or f"upload-{uuid4()}.txt"


def _validate_extension(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )
    return ext


def _extract_text_from_bytes(file_bytes: bytes, filename: str) -> str:
    ext = Path(filename).suffix.lower()

    if ext in {".txt", ".md"}:
        return file_bytes.decode("utf-8", errors="replace")

    if ext == ".pdf":
        reader = PdfReader(io.BytesIO(file_bytes))
        pages = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        return "\n\n".join(pages).strip()

    if ext == ".docx":
        doc = Document(io.BytesIO(file_bytes))
        return "\n".join(p.text for p in doc.paragraphs).strip()

    raise HTTPException(status_code=400, detail="Unsupported file type")


def _group_chunks_by_chapter(chunks: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    chapters: Dict[str, List[Dict[str, Any]]] = {}
    current_chapter = "General"

    for chunk in chunks:
        if chunk["level"] == 1:
            current_chapter = chunk["heading"]
            chapters[current_chapter] = []
        elif current_chapter not in chapters:
            chapters[current_chapter] = []

        chapters[current_chapter].append(chunk)

    return chapters


def _upload_to_staging_bucket(upload_id: str, filename: str, content: bytes, content_type: Optional[str]) -> str:
    sb = get_supabase_client()
    bucket_name = settings.upload_staging_bucket
    dated_prefix = datetime.now(timezone.utc).strftime("%Y/%m/%d")
    storage_path = f"{dated_prefix}/{upload_id}/{filename}"

    sb.storage.from_(bucket_name).upload(
        storage_path,
        content,
        {
            "content-type": content_type or "application/octet-stream",
            "upsert": "false",
        },
    )
    return storage_path


def _create_upload_session(
    upload_id: str,
    filename: str,
    storage_path: str,
    content_type: Optional[str],
    size_bytes: int,
) -> None:
    sb = get_supabase_client()
    sb.table("upload_sessions").insert(
        {
            "id": upload_id,
            "filename": filename,
            "storage_bucket": settings.upload_staging_bucket,
            "storage_path": storage_path,
            "content_type": content_type,
            "size_bytes": size_bytes,
            "status": "processing",
            "created_at": _utc_now_iso(),
        }
    ).execute()


def _update_upload_session(upload_id: str, patch: Dict[str, Any]) -> None:
    sb = get_supabase_client()
    sb.table("upload_sessions").update(patch).eq("id", upload_id).execute()


def _create_staged_document(upload_id: str, filename: str, source: str, extracted_text: str) -> str:
    sb = get_supabase_client()
    res = (
        sb.table("staged_documents")
        .insert(
            {
                "upload_session_id": upload_id,
                "title": filename,
                "source": source,
                "extracted_text": extracted_text,
                "status": "processing",
                "created_at": _utc_now_iso(),
            }
        )
        .execute()
    )

    if not getattr(res, "data", None):
        raise RuntimeError("Failed to create staged document")

    return res.data[0]["id"]


def _insert_staged_chunks(staged_document_id: str, chunks: List[Dict[str, Any]]) -> None:
    if not chunks:
        return

    sb = get_supabase_client()

    chapters = _group_chunks_by_chapter(chunks)
    rows_to_insert: List[Dict[str, Any]] = []

    for chapter_name, chapter_chunks in chapters.items():
        if not chapter_chunks:
            continue

        section_summaries: List[str] = []

        for chunk in chapter_chunks:
            summary = summarize_chunk(chunk["content"], chunk["heading"])
            section_summaries.append(summary)

            rows_to_insert.append(
                {
                    "staged_document_id": staged_document_id,
                    "section_heading": chunk["heading"],
                    "content": chunk["content"],
                    "summary": summary,
                    "chapter_summary": None,
                    "position_in_doc": chunk["position"],
                }
            )

        chapter_summary = create_chapter_summary(section_summaries, chapter_name) if section_summaries else ""
        for row in rows_to_insert:
            if row["chapter_summary"] is None and any(
                c["heading"] == row["section_heading"] for c in chapter_chunks
            ):
                row["chapter_summary"] = chapter_summary

    if rows_to_insert:
        sb.table("staged_chunks").insert(rows_to_insert).execute()


async def upload_and_stage_document(file: UploadFile) -> Dict[str, Any]:
    sb = get_supabase_client()

    original_filename = file.filename or "uploaded-file.txt"
    safe_name = _safe_filename(original_filename)
    _validate_extension(safe_name)

    content = await file.read()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Max size is {settings.max_upload_size_mb} MB.",
        )

    upload_id = str(uuid4())
    storage_path = _upload_to_staging_bucket(
        upload_id=upload_id,
        filename=safe_name,
        content=content,
        content_type=file.content_type,
    )

    _create_upload_session(
        upload_id=upload_id,
        filename=safe_name,
        storage_path=storage_path,
        content_type=file.content_type,
        size_bytes=len(content),
    )

    source = f"supabase://{settings.upload_staging_bucket}/{storage_path}"

    try:
        extracted_text = _extract_text_from_bytes(content, safe_name).strip()
        if not extracted_text:
            raise HTTPException(status_code=400, detail="Could not extract text from uploaded file")

        staged_document_id = _create_staged_document(
            upload_id=upload_id,
            filename=safe_name,
            source=source,
            extracted_text=extracted_text,
        )

        headings = detect_headings(extracted_text)
        chunks = chunk_by_headings(extracted_text, headings)

        _insert_staged_chunks(staged_document_id, chunks)

        _update_upload_session(
            upload_id,
            {
                "status": "staged",
                "processed_at": _utc_now_iso(),
            },
        )

        sb.table("staged_documents").update({"status": "staged"}).eq("id", staged_document_id).execute()

        return {
            "upload_id": upload_id,
            "staged_document_id": staged_document_id,
            "filename": safe_name,
            "status": "staged",
            "chunk_count": len(chunks),
        }

    except HTTPException as e:
        _update_upload_session(
            upload_id,
            {
                "status": "failed",
                "error_message": str(e.detail),
                "processed_at": _utc_now_iso(),
            },
        )
        raise
    except Exception as e:
        _update_upload_session(
            upload_id,
            {
                "status": "failed",
                "error_message": str(e),
                "processed_at": _utc_now_iso(),
            },
        )
        raise


def list_uploads() -> List[Dict[str, Any]]:
    sb = get_supabase_client()
    res = (
        sb.table("upload_sessions")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []


def get_upload_details(upload_id: str) -> Optional[Dict[str, Any]]:
    sb = get_supabase_client()

    session_res = sb.table("upload_sessions").select("*").eq("id", upload_id).limit(1).execute()
    if not session_res.data:
        return None

    session = session_res.data[0]

    doc_res = (
        sb.table("staged_documents")
        .select("*")
        .eq("upload_session_id", upload_id)
        .limit(1)
        .execute()
    )
    staged_document = doc_res.data[0] if doc_res.data else None

    chunks = []
    if staged_document:
        chunk_res = (
            sb.table("staged_chunks")
            .select("id, section_heading, summary, position_in_doc")
            .eq("staged_document_id", staged_document["id"])
            .order("position_in_doc")
            .execute()
        )
        chunks = chunk_res.data or []

    return {
        "upload_session": session,
        "staged_document": staged_document,
        "chunks": chunks,
    }


def promote_upload(upload_id: str) -> Dict[str, Any]:
    sb = get_supabase_client()

    session_res = sb.table("upload_sessions").select("*").eq("id", upload_id).limit(1).execute()
    if not session_res.data:
        raise HTTPException(status_code=404, detail="Upload not found")

    session = session_res.data[0]
    if session["status"] != "staged":
        raise HTTPException(
            status_code=400,
            detail=f"Only staged uploads can be promoted. Current status: {session['status']}",
        )

    staged_doc_res = (
        sb.table("staged_documents")
        .select("*")
        .eq("upload_session_id", upload_id)
        .limit(1)
        .execute()
    )
    if not staged_doc_res.data:
        raise HTTPException(status_code=400, detail="No staged document found for this upload")

    staged_doc = staged_doc_res.data[0]

    live_doc_res = (
        sb.table("documents")
        .insert(
            {
                "title": staged_doc["title"],
                "source": staged_doc["source"],
                "promoted_from_upload_session_id": upload_id,
            }
        )
        .execute()
    )
    if not live_doc_res.data:
        raise RuntimeError("Failed to create live document")

    live_doc_id = live_doc_res.data[0]["id"]

    staged_chunks_res = (
        sb.table("staged_chunks")
        .select("*")
        .eq("staged_document_id", staged_doc["id"])
        .order("position_in_doc")
        .execute()
    )
    staged_chunks = staged_chunks_res.data or []

    if staged_chunks:
        live_rows = [
            {
                "document_id": live_doc_id,
                "section_heading": chunk["section_heading"],
                "content": chunk["content"],
                "summary": chunk["summary"],
                "chapter_summary": chunk["chapter_summary"],
                "position_in_doc": chunk["position_in_doc"],
            }
            for chunk in staged_chunks
        ]
        sb.table("chunks").insert(live_rows).execute()

    _update_upload_session(
        upload_id,
        {
            "status": "promoted",
            "promoted_document_id": live_doc_id,
            "promoted_at": _utc_now_iso(),
        },
    )
    sb.table("staged_documents").update({"status": "promoted"}).eq("id", staged_doc["id"]).execute()

    return {
        "ok": True,
        "upload_id": upload_id,
        "document_id": live_doc_id,
        "status": "promoted",
        "chunk_count": len(staged_chunks),
    }


def reject_upload(upload_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
    sb = get_supabase_client()

    session_res = sb.table("upload_sessions").select("*").eq("id", upload_id).limit(1).execute()
    if not session_res.data:
        raise HTTPException(status_code=404, detail="Upload not found")

    session = session_res.data[0]
    if session["status"] not in {"staged", "failed"}:
        raise HTTPException(
            status_code=400,
            detail=f"Only staged or failed uploads can be rejected. Current status: {session['status']}",
        )

    _update_upload_session(
        upload_id,
        {
            "status": "rejected",
            "review_notes": reason,
        },
    )

    sb.table("staged_documents").update({"status": "rejected"}).eq("upload_session_id", upload_id).execute()

    return {
        "ok": True,
        "upload_id": upload_id,
        "status": "rejected",
        "reason": reason,
    }


def rollback_upload(upload_id: str) -> Dict[str, Any]:
    sb = get_supabase_client()

    session_res = sb.table("upload_sessions").select("*").eq("id", upload_id).limit(1).execute()
    if not session_res.data:
        raise HTTPException(status_code=404, detail="Upload not found")

    session = session_res.data[0]
    if session["status"] != "promoted":
        raise HTTPException(
            status_code=400,
            detail=f"Only promoted uploads can be rolled back. Current status: {session['status']}",
        )

    promoted_document_id = session.get("promoted_document_id")
    if not promoted_document_id:
        raise HTTPException(status_code=400, detail="This upload has no promoted document ID")

    sb.table("chunks").delete().eq("document_id", promoted_document_id).execute()
    sb.table("documents").delete().eq("id", promoted_document_id).execute()

    _update_upload_session(
        upload_id,
        {
            "status": "rolled_back",
            "rolled_back_at": _utc_now_iso(),
        },
    )

    return {
        "ok": True,
        "upload_id": upload_id,
        "rolled_back_document_id": promoted_document_id,
        "status": "rolled_back",
    }