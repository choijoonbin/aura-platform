"""
RAG Vector Pipeline API (Phase 6)

파일 업로드 또는 백엔드 로컬 경로(document_path) → 백그라운드 벡터화 → dwp_aura.rag_document ID 매핑.
"""

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, Form, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core.analysis.rag import process_and_vectorize, validate_local_document_path
from core.config import get_settings


class IngestFromPathRequest(BaseModel):
    """백엔드 로컬 경로 기반 RAG 수집 요청."""

    document_path: str = Field(..., description="로컬 절대 경로 (실제 존재·읽기 가능해야 함)")
    rag_document_id: str = Field(default="", description="dwp_aura.rag_document 문서 ID (매핑용)")
    metadata: str = Field(default="", description='JSON 문자열. 예: {"regulation_article":"제5조"}')


class VectorizeByPathBody(BaseModel):
    """POST /documents/{docId}/vectorize 요청 body (백엔드 호출 규격)."""

    document_path: str = Field(..., description="로컬 절대 경로")
    metadata: str = Field(default="", description='JSON 문자열. 예: {"regulation_article":"제5조"}')

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/aura/rag", tags=["aura-rag"])

# 업로드 임시 디렉터리 (벡터화 후 삭제)
UPLOAD_TMP_DIR = Path(os.environ.get("AURA_RAG_UPLOAD_TMP", "./data/rag_upload_tmp"))

_ALLOWED_EXTENSIONS = (".pdf", ".txt", ".md")


def _run_vectorize_and_cleanup(file_path: str, rag_document_id: str, metadata_str: str | None) -> None:
    """백그라운드: 벡터화 실행 후 임시 파일 삭제."""
    path = Path(file_path)
    metadata: dict[str, Any] = {}
    if metadata_str and metadata_str.strip():
        try:
            metadata = json.loads(metadata_str)
        except json.JSONDecodeError:
            pass
    try:
        result = process_and_vectorize(path, rag_document_id, metadata or None)
        if result.get("ok"):
            logger.info("RAG vectorize ok: rag_document_id=%s chunks=%s", rag_document_id, result.get("chunks_added"))
        else:
            logger.warning("RAG vectorize failed: %s", result.get("error"))
    finally:
        try:
            if path.exists():
                path.unlink()
        except OSError as e:
            logger.warning("Failed to remove temp file %s: %s", file_path, e)


def _run_vectorize_from_path(file_path: str, rag_document_id: str, metadata_str: str | None) -> None:
    """백그라운드: 로컬 공유 경로 파일 벡터화. 파일은 삭제하지 않음(백엔드 소유)."""
    path = Path(file_path)
    metadata: dict[str, Any] = {}
    if metadata_str and metadata_str.strip():
        try:
            metadata = json.loads(metadata_str)
        except json.JSONDecodeError:
            pass
    result = process_and_vectorize(path, rag_document_id, metadata or None)
    if result.get("ok"):
        logger.info("RAG vectorize from path ok: rag_document_id=%s chunks=%s", rag_document_id, result.get("chunks_added"))
    else:
        logger.warning("RAG vectorize from path failed: %s", result.get("error"))


@router.post(
    "/ingest",
    summary="RAG 문서 벡터화 수집",
    description="PDF/Text 파일 업로드 후 백그라운드에서 Chunk → Embed → Vector Store 저장. dwp_aura.rag_document ID와 매핑.",
)
async def rag_ingest(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="PDF 또는 텍스트 파일"),
    rag_document_id: str = Form(default="", description="dwp_aura.rag_document 테이블 문서 ID (매핑용)"),
    metadata: str = Form(
        default="",
        description='JSON 문자열. 규정 인용용 메타데이터 (예: {"regulation_article":"제5조","location":"규정 제5조 2항"})',
    ),
) -> JSONResponse:
    """
    파일 업로드 → 202 Accepted + job_id.
    벡터화는 BackgroundTasks로 비동기 수행.
    """
    if not file.filename:
        return JSONResponse(status_code=400, content={"error": "filename required"})
    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".pdf", ".txt", ".md"):
        return JSONResponse(
            status_code=400,
            content={"error": "Only .pdf, .txt, .md are supported"},
        )
    doc_id = (rag_document_id or "").strip() or f"rag-{uuid.uuid4().hex[:12]}"
    UPLOAD_TMP_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = f"{doc_id}{suffix}"
    tmp_path = UPLOAD_TMP_DIR / safe_name
    try:
        content = await file.read()
        tmp_path.write_bytes(content)
    except Exception as e:
        logger.warning("rag_ingest write temp failed: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})
    job_id = f"job-{uuid.uuid4().hex[:16]}"
    background_tasks.add_task(
        _run_vectorize_and_cleanup,
        str(tmp_path),
        doc_id,
        metadata.strip() or None,
    )
    return JSONResponse(
        status_code=202,
        content={
            "job_id": job_id,
            "rag_document_id": doc_id,
            "message": "Vectorization started in background",
        },
    )


@router.post(
    "/documents/{doc_id}/vectorize",
    summary="RAG 문서 벡터화 (백엔드 호출용)",
    description="백엔드가 저장한 로컬 경로(document_path)로 해당 doc_id 문서를 벡터화. Path param doc_id = rag_document_id.",
)
async def rag_documents_vectorize(
    doc_id: str,
    background_tasks: BackgroundTasks,
    body: VectorizeByPathBody,
) -> JSONResponse:
    """
    POST /aura/rag/documents/{docId}/vectorize — 백엔드가 document_path를 body에 넣어 호출.
    doc_id(path) = rag_document_id, body.document_path = 로컬 절대 경로.
    """
    document_path = (body.document_path or "").strip()
    if not document_path:
        return JSONResponse(status_code=400, content={"error": "document_path required"})
    suffix = Path(document_path).suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        return JSONResponse(
            status_code=400,
            content={"error": f"Only {', '.join(_ALLOWED_EXTENSIONS)} are supported"},
        )
    settings = get_settings()
    allowed_base = getattr(settings, "rag_allowed_document_base_path", None)
    try:
        valid_path = validate_local_document_path(
            document_path,
            allowed_base=Path(allowed_base) if allowed_base else None,
        )
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})
    except PermissionError as e:
        return JSONResponse(status_code=403, content={"error": str(e)})
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    rag_document_id = (doc_id or "").strip() or f"rag-{uuid.uuid4().hex[:12]}"
    job_id = f"job-{uuid.uuid4().hex[:16]}"
    background_tasks.add_task(
        _run_vectorize_from_path,
        str(valid_path),
        rag_document_id,
        body.metadata.strip() or None,
    )
    return JSONResponse(
        status_code=202,
        content={
            "job_id": job_id,
            "rag_document_id": rag_document_id,
            "document_path": str(valid_path),
            "message": "Vectorization started in background",
        },
    )


@router.post(
    "/ingest-from-path",
    summary="RAG 문서 벡터화 수집 (로컬 경로)",
    description="백엔드가 저장한 로컬 절대 경로(document_path)의 파일을 읽어 Chunk → Embed → Vector Store 저장. 경로 존재·읽기 권한 검사 후 기존 청킹·벡터화 프로세스 수행.",
)
async def rag_ingest_from_path(
    background_tasks: BackgroundTasks,
    body: IngestFromPathRequest,
) -> JSONResponse:
    """
    Request body (JSON): document_path(필수), rag_document_id, metadata(JSON 문자열).
    document_path: 로컬 절대 경로. rag_allowed_document_base_path 설정 시 해당 하위 경로만 허용.
    """
    document_path = (body.document_path or "").strip()
    if not document_path:
        return JSONResponse(status_code=400, content={"error": "document_path required"})
    suffix = Path(document_path).suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        return JSONResponse(
            status_code=400,
            content={"error": f"Only {', '.join(_ALLOWED_EXTENSIONS)} are supported"},
        )
    settings = get_settings()
    allowed_base = getattr(settings, "rag_allowed_document_base_path", None)
    try:
        valid_path = validate_local_document_path(
            document_path,
            allowed_base=Path(allowed_base) if allowed_base else None,
        )
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})
    except PermissionError as e:
        return JSONResponse(status_code=403, content={"error": str(e)})
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    doc_id = (body.rag_document_id or "").strip() or f"rag-{uuid.uuid4().hex[:12]}"
    job_id = f"job-{uuid.uuid4().hex[:16]}"
    background_tasks.add_task(
        _run_vectorize_from_path,
        str(valid_path),
        doc_id,
        body.metadata.strip() or None,
    )
    return JSONResponse(
        status_code=202,
        content={
            "job_id": job_id,
            "rag_document_id": doc_id,
            "document_path": str(valid_path),
            "message": "Vectorization from local path started in background",
        },
    )
