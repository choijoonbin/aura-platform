"""
RAG Vector Pipeline API (Phase 6)

Aura는 DB에 INSERT하지 않음. 문서 벡터화 연산(Chunk + Embedding) 결과만 JSON으로 반환.
저장은 백엔드에서 수행. 대용량 방지를 위해 청크를 20~50개 단위 배치로 분할 전송.
"""

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, File, Form, UploadFile, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core.analysis.rag import process_and_vectorize, validate_local_document_path
from core.config import get_settings


class IngestFromPathRequest(BaseModel):
    """백엔드 로컬 경로 기반 벡터화 요청."""

    document_path: str = Field(..., description="로컬 절대 경로 (실제 존재·읽기 가능해야 함)")
    rag_document_id: str = Field(default="", description="dwp_aura.rag_document 문서 ID (매핑용)")
    metadata: str = Field(default="", description='JSON 문자열. 예: {"regulation_article":"제5조"}')


class VectorizeByPathBody(BaseModel):
    """POST /documents/{docId}/vectorize 요청 body (백엔드 호출 규격)."""

    document_path: str = Field(..., description="로컬 절대 경로")
    metadata: str = Field(default="", description='JSON 문자열. 예: {"regulation_article":"제5조"}')

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/aura/rag", tags=["aura-rag"])

UPLOAD_TMP_DIR = Path(os.environ.get("AURA_RAG_UPLOAD_TMP", "./data/rag_upload_tmp"))
_ALLOWED_EXTENSIONS = (".pdf", ".txt", ".md")

# 배치 크기 허용 범위 (메모리·전송 부담 완화)
_BATCH_SIZE_MIN, _BATCH_SIZE_MAX = 20, 50


def _parse_metadata(metadata_str: str | None) -> dict[str, Any]:
    if not metadata_str or not metadata_str.strip():
        return {}
    try:
        return json.loads(metadata_str)
    except json.JSONDecodeError:
        return {}


def _batch_chunks(chunks: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
    """청크 리스트를 batch_size 단위로 분할. batch_size는 20~50으로 클램프."""
    size = max(_BATCH_SIZE_MIN, min(_BATCH_SIZE_MAX, batch_size))
    return [chunks[i : i + size] for i in range(0, len(chunks), size)] if chunks else []


def _send_batches_to_backend(
    rag_document_id: str,
    batches: list[list[dict[str, Any]]],
    save_url_template: str,
    timeout: float = 60.0,
) -> tuple[int, int]:
    """
    백엔드 저장 API에 배치 단위로 POST. URL 내 {doc_id}는 rag_document_id로 치환.
    Returns:
        (batches_sent, total_chunks)
    """
    url = save_url_template.replace("{doc_id}", rag_document_id)
    total = 0
    for batch_index, batch in enumerate(batches):
        body = {
            "rag_document_id": rag_document_id,
            "chunks": batch,
            "batch_index": batch_index,
            "total_batches": len(batches),
        }
        try:
            with httpx.Client(timeout=timeout) as client:
                r = client.post(url, json=body)
                if r.status_code >= 400:
                    logger.warning(
                        "Backend chunks save failed: status=%s body=%s (백엔드에서 400 원인 확인 후 수정)",
                        r.status_code, (r.text or "")[:500],
                    )
                    raise RuntimeError(f"Backend save returned {r.status_code}: {r.text[:200] if r.text else ''}")
        except Exception as e:
            logger.warning("Backend chunks save request failed: %s", e)
            raise
        total += len(batch)
    return len(batches), total


def _build_vectorize_response(
    rag_document_id: str,
    chunks: list[dict[str, Any]],
    batch_size: int,
    save_url: str | None,
) -> JSONResponse:
    """
    배치 단위로 응답 구성 또는 백엔드 저장 API 반복 호출.
    - save_url 설정 시: 배치마다 POST 후 요약만 반환 (전송 경량화).
    - 미설정 시: 응답 body에 batch_size와 batches(배치 배열) 반환. 순수 JSON(숫자 배열·텍스트만).
    """
    batches = _batch_chunks(chunks, batch_size)
    if save_url:
        try:
            sent, total = _send_batches_to_backend(rag_document_id, batches, save_url)
            payload = {
                "rag_document_id": rag_document_id,
                "total_chunks": total,
                "batches_sent": sent,
                "batch_size": batch_size,
            }
            logger.info(
                "RAG vectorize response (save_url used): rag_document_id=%s total_chunks=%s batches_sent=%s batch_size=%s keys=%s",
                rag_document_id, total, sent, batch_size, list(payload.keys()),
            )
            return JSONResponse(status_code=200, content=payload)
        except Exception as e:
            return JSONResponse(
                status_code=502,
                content={"error": f"Backend chunks save failed: {e}"},
            )
    payload = {
        "rag_document_id": rag_document_id,
        "batch_size": batch_size,
        "batches": batches,
    }
    first_chunk_keys = list(batches[0][0].keys()) if batches and batches[0] else []
    logger.info(
        "RAG vectorize response (body): rag_document_id=%s batch_size=%s num_batches=%s first_chunk_keys=%s response_top_keys=%s",
        rag_document_id, batch_size, len(batches), first_chunk_keys, list(payload.keys()),
    )
    return JSONResponse(status_code=200, content=payload)


@router.post(
    "/documents/{doc_id}/vectorize",
    summary="RAG 문서 벡터화 (배치 단위 반환 또는 백엔드 저장 API 호출)",
    description="Chunk → Embedding 연산 후, 20~50개 단위 배치로 분할해 응답하거나 백엔드 저장 API에 반복 POST. 순수 JSON(float[]·텍스트)만 전달.",
)
async def rag_documents_vectorize(
    doc_id: str,
    body: VectorizeByPathBody,
    batch_size: int = Query(default=30, ge=20, le=50, description="배치당 청크 수 (20~50)"),
) -> JSONResponse:
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
    metadata = _parse_metadata(body.metadata.strip() or None)
    logger.info(
        "RAG vectorize start: doc_id=%s rag_document_id=%s document_path=%s batch_size=%s",
        doc_id, rag_document_id, document_path, batch_size,
    )
    result = process_and_vectorize(valid_path, rag_document_id, metadata or None)
    if not result.get("ok"):
        logger.warning("RAG vectorize failed: doc_id=%s error=%s", doc_id, result.get("error"))
        return JSONResponse(
            status_code=422,
            content={"error": result.get("error", "Vectorization failed")},
        )
    chunks = result["chunks"]
    save_url = getattr(settings, "backend_rag_chunks_save_url", None) or None
    logger.info(
        "RAG vectorize chunks ready: doc_id=%s num_chunks=%s save_url_set=%s (BE expects response keys: rag_document_id, total_chunks|batches, batches_sent, batch_size)",
        doc_id, len(chunks), bool(save_url),
    )
    return _build_vectorize_response(rag_document_id, chunks, batch_size, save_url)


@router.post(
    "/ingest-from-path",
    summary="RAG 문서 벡터화 (로컬 경로, 배치 단위 반환 또는 백엔드 저장 API 호출)",
    description="로컬 경로 파일 Chunk → Embedding 후 20~50개 단위 배치로 응답하거나 백엔드 저장 API에 반복 POST.",
)
async def rag_ingest_from_path(body: IngestFromPathRequest) -> JSONResponse:
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
    metadata = _parse_metadata(body.metadata.strip() or None)
    result = process_and_vectorize(valid_path, doc_id, metadata or None)
    if not result.get("ok"):
        return JSONResponse(
            status_code=422,
            content={"error": result.get("error", "Vectorization failed")},
        )
    batch_size = getattr(settings, "rag_chunk_batch_size", 30)
    save_url = getattr(settings, "backend_rag_chunks_save_url", None) or None
    return _build_vectorize_response(result["rag_document_id"], result["chunks"], batch_size, save_url)


@router.post(
    "/ingest",
    summary="RAG 문서 벡터화 (파일 업로드, 배치 단위 반환 또는 백엔드 저장 API 호출)",
    description="PDF/Text 업로드 → Chunk → Embedding 후 20~50개 단위 배치로 응답하거나 백엔드 저장 API에 반복 POST.",
)
async def rag_ingest(
    file: UploadFile = File(..., description="PDF 또는 텍스트 파일"),
    rag_document_id: str = Form(default="", description="dwp_aura.rag_document 문서 ID (매핑용)"),
    metadata: str = Form(
        default="",
        description='JSON 문자열. 규정 인용용 메타데이터 (예: {"regulation_article":"제5조"})',
    ),
) -> JSONResponse:
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
    tmp_path = UPLOAD_TMP_DIR / f"{doc_id}{suffix}"
    try:
        content = await file.read()
        tmp_path.write_bytes(content)
    except Exception as e:
        logger.warning("rag_ingest write temp failed: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})
    try:
        meta = _parse_metadata(metadata.strip() or None)
        result = process_and_vectorize(tmp_path, doc_id, meta or None)
        if not result.get("ok"):
            return JSONResponse(
                status_code=422,
                content={"error": result.get("error", "Vectorization failed")},
            )
        settings = get_settings()
        batch_size = getattr(settings, "rag_chunk_batch_size", 30)
        save_url = getattr(settings, "backend_rag_chunks_save_url", None) or None
        return _build_vectorize_response(result["rag_document_id"], result["chunks"], batch_size, save_url)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError as e:
            logger.warning("Failed to remove temp file %s: %s", tmp_path, e)
