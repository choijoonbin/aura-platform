"""
RAG 유틸 (Phase3 및 공통, Phase 6 Vector Pipeline)

- artifacts 청킹, topK retrieve, ragRefs 스키마 생성.
- Vector Ingestion: process_and_vectorize (PDF/Text → Chunk → Embed → Store).
  - vector_store_type=pgvector 시 dwp_aura.rag_chunk Upsert.
  - Chunking: SemanticChunker (langchain_experimental, percentile breakpoint).
  - PDF: PyMuPDF (fitz) + 표(Table) → Markdown 보존.
  - chunk metadata: page_number, file_path (출처 보기/Citation).
- Hybrid Search: hybrid_retrieve (벡터 + 메타데이터, Article/Clause 보존).

Hardening (Robustness):
- [Abstraction] pgvector 접근은 PgVectorRagStore 추상화를 통해서만 수행.
  향후 langchain-postgres / langchain_community PGVector 연동 시 이 레이어만 교체.
- [Standardization] PostgreSQL 고유 문법 `::type` 금지. 모든 타입 캐스팅은
  표준 SQL `CAST(:param AS type)` 로만 수행하여 SQLAlchemy/psycopg2 바인딩 간섭 방지.
- [Validation] 벡터화 전 preprocess_document_text() 로 UTF-8·특수문자 검증 및 정규화.
"""

import json
import logging
import os
import re
import unicodedata
import uuid
from pathlib import Path
from typing import Any

from core.config import get_settings

logger = logging.getLogger(__name__)

# SQL 표준화: PostgreSQL ::type 사용 금지. CAST(:param AS type) 만 사용.
_SQL_CAST_VECTOR = "CAST(:embedding AS vector)"
_SQL_CAST_JSONB = "CAST(:metadata_json AS jsonb)"
_SQL_CAST_JSONB_FILTER = "CAST(:filter_json AS jsonb)"

# 청크 본문 내 페이지 마커 (PDF 로드 시 삽입 → 청크별 page_number 추출용)
_PAGE_MARKER_PATTERN = re.compile(r"\[PAGE=(\d+)\]")

# 제어문자·널 등 DB/임베딩 오염 방지 (공백으로 치환)
_CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# pgvector 상수
PGVECTOR_SCHEMA = "dwp_aura"
PGVECTOR_TABLE = "rag_chunk"
EMBEDDING_DIM = 1536

# ---------------------------------------------------------------------------
# Phase 6: Embedding & Vector Store (optional deps: pypdf, langchain-text-splitters, chromadb, langchain-chroma)
# ---------------------------------------------------------------------------

_embedding_client: Any = None
_vector_store: Any = None


def _get_embedding_client():
    """OpenAI 또는 Azure Embedding 클라이언트 (싱글톤)."""
    global _embedding_client
    if _embedding_client is not None:
        return _embedding_client
    settings = get_settings()
    try:
        if settings.use_azure_openai and (settings.azure_openai_embedding_deployment or settings.openai_embedding_model):
            from langchain_openai import AzureOpenAIEmbeddings
            _embedding_client = AzureOpenAIEmbeddings(
                azure_endpoint=settings.azure_openai_endpoint,
                api_key=settings.azure_openai_api_key,
                azure_deployment=settings.azure_openai_embedding_deployment or settings.openai_embedding_model,
                api_version=settings.azure_openai_api_version,
            )
        elif getattr(settings, "openai_api_key", None):
            from langchain_openai import OpenAIEmbeddings
            _embedding_client = OpenAIEmbeddings(
                model=settings.openai_embedding_model,
                openai_api_key=settings.openai_api_key,
            )
        else:
            _embedding_client = None
    except Exception as e:
        logger.warning("Embedding client init failed (install langchain-openai): %s", e)
        _embedding_client = None
    return _embedding_client


def get_vector_store():
    """
    설정에 따른 벡터 스토어 반환 (Chroma). vector_store_type=chroma 이고 의존성 설치 시에만 동작.
    """
    global _vector_store
    if _vector_store is not None:
        return _vector_store
    settings = get_settings()
    if (getattr(settings, "vector_store_type", "none") or "").lower() != "chroma":
        return None
    try:
        from langchain_chroma import Chroma
        from langchain_core.documents import Document
        emb = _get_embedding_client()
        if emb is None:
            return None
        persist_dir = getattr(settings, "chroma_persist_dir", "./data/chroma") or "./data/chroma"
        os.makedirs(persist_dir, exist_ok=True)
        collection = getattr(settings, "chroma_collection_name", "aura_rag") or "aura_rag"
        _vector_store = Chroma(
            collection_name=collection,
            embedding_function=emb,
            persist_directory=persist_dir,
        )
    except ImportError as e:
        logger.warning("Chroma not available (pip install chromadb langchain-chroma): %s", e)
        _vector_store = None
    except Exception as e:
        logger.warning("Vector store init failed: %s", e)
        _vector_store = None
    return _vector_store


def validate_local_document_path(
    document_path: str | Path,
    *,
    allowed_base: str | Path | None = None,
) -> Path:
    """
    백엔드에서 전달한 로컬 절대 경로가 존재·읽기 가능한지 검사.
    allowed_base가 설정된 경우, document_path는 해당 경로 하위여야 함 (realpath 기준).

    Returns:
        검증된 Path (실제 파일).

    Raises:
        FileNotFoundError: 경로가 없거나 파일이 아님.
        PermissionError: 읽기 권한 없음.
        ValueError: allowed_base 하위가 아님.
    """
    path = Path(document_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Document path does not exist: {document_path}")
    if not path.is_file():
        raise FileNotFoundError(f"Document path is not a file: {path}")
    if not os.access(path, os.R_OK):
        raise PermissionError(f"Document path not readable: {path}")
    if allowed_base is not None:
        base = Path(allowed_base).resolve()
        try:
            path.relative_to(base)
        except ValueError:
            raise ValueError(
                f"Document path must be under allowed base {base}: {path}"
            )
    return path


def _table_to_markdown(table: Any) -> str:
    """PyMuPDF Table → Markdown 문자열 (표 데이터 깨짐 방지)."""
    try:
        rows = table.extract()
        if not rows:
            return ""
        lines = []
        for i, row in enumerate(rows):
            cells = [str(c or "").replace("|", "\\|") for c in row]
            lines.append("| " + " | ".join(cells) + " |")
        if lines:
            # 헤더 구분선
            lines.insert(1, "| " + " | ".join("---" for _ in rows[0]) + " |")
        return "\n".join(lines)
    except Exception as e:
        logger.debug("Table to markdown skipped: %s", e)
        return ""


def _load_pdf_pymupdf(file_path: Path) -> str:
    """
    PyMuPDF(fitz)로 PDF 추출. 레이아웃·표 보존을 위해 표는 Markdown으로 변환.
    페이지 구분을 위해 각 페이지 앞에 [PAGE=n] 마커 삽입 (청크별 page_number 추출용).
    """
    try:
        import fitz
    except ImportError:
        raise RuntimeError("PDF support requires: pip install pymupdf")
    parts: list[str] = []
    with fitz.open(file_path) as doc:
        for page_num in range(len(doc)):
            page = doc[page_num]
            part = f"[PAGE={page_num + 1}]\n\n"
            # 본문 텍스트 (기본 추출)
            part += page.get_text() or ""
            # 표 추출 → Markdown (find_tables 지원 시)
            if hasattr(page, "find_tables"):
                try:
                    tables = page.find_tables()
                    if tables:
                        for tbl in tables:
                            md = _table_to_markdown(tbl)
                            if md:
                                part += "\n\n" + md + "\n\n"
                except Exception as e:
                    logger.debug("Page %s find_tables skipped: %s", page_num + 1, e)
            parts.append(part)
    return preprocess_document_text("\n\n".join(parts))


def _extract_page_from_chunk(content: str) -> int:
    """청크 본문에서 첫 [PAGE=n] 마커로 page_number 추출. 없으면 0."""
    m = _PAGE_MARKER_PATTERN.search(content)
    return int(m.group(1)) if m else 0


def _load_text_from_file(file_path: str | Path) -> str:
    """
    PDF 또는 텍스트 파일에서 본문 추출.
    PDF: PyMuPDF(fitz) 사용, 표는 Markdown 보존, [PAGE=n] 마커 포함.
    호출 전 경로 존재·읽기 권한은 validate_local_document_path 등으로 검사 권장.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    if not os.access(path, os.R_OK):
        raise PermissionError(f"File not readable: {path}")
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _load_pdf_pymupdf(path)
    # .txt, .md, etc. (단일 페이지로 간주, 마커 없음)
    raw = path.read_text(encoding="utf-8", errors="replace")
    return preprocess_document_text(raw)


def _notify_backend_rag_completed(doc_id: str) -> None:
    """벡터화 완료 후 Backend RagController에 processing_status=COMPLETED 전달."""
    settings = get_settings()
    url = getattr(settings, "backend_rag_callback_url", None) or ""
    if not url or not doc_id:
        return
    base = url.rstrip("/")
    callback_url = f"{base}/rag/documents/{doc_id}/processing-status"
    try:
        import httpx
        with httpx.Client(timeout=10.0) as client:
            r = client.post(
                callback_url,
                json={"processing_status": "COMPLETED", "doc_id": doc_id},
            )
            if r.status_code >= 400:
                logger.warning("Backend RAG callback failed: %s %s", r.status_code, r.text)
    except Exception as e:
        logger.warning("Backend RAG callback error: %s", e)


def _embedding_to_pgvector(embedding: list[float]) -> str:
    """[0.1, -0.2, ...] → '[0.1,-0.2,...]' for PostgreSQL vector literal."""
    return "[" + ",".join(str(float(x)) for x in embedding) + "]"


def preprocess_document_text(content: str) -> str:
    """
    벡터화 전단계 전처리: UTF-8 검증, 특수문자·제어문자 정리로 데이터 오염 방지.

    - 유효한 UTF-8로 정규화 (손상 바이트는 대체 문자로).
    - 유니코드 NFC 정규화로 동일 문자 표현 통일.
    - 널·제어문자 제거(공백 치환)로 DB/임베딩 오류 방지.
    """
    if not content or not isinstance(content, str):
        return ""
    # 이미 str이어도 손상된 서로게이트 등이 있을 수 있음 → encode/decode로 정리
    try:
        normalized = content.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
    except Exception:
        normalized = content
    normalized = unicodedata.normalize("NFC", normalized)
    return _CONTROL_CHAR_PATTERN.sub(" ", normalized)


# ---------------------------------------------------------------------------
# pgvector 저장소 추상화 (CAST-only SQL. Raw `::type` 사용 금지.)
# ---------------------------------------------------------------------------


def _pgvector_delete_by_doc_id(session: Any, full_table: str, doc_id: str) -> None:
    """문서별 기존 청크 삭제. 바인딩만 사용."""
    from sqlalchemy import text
    session.execute(text(f"DELETE FROM {full_table} WHERE doc_id = :doc_id"), {"doc_id": doc_id})


def _pgvector_insert_chunk(
    session: Any,
    full_table: str,
    *,
    doc_id: str,
    chunk_index: int,
    content: str,
    embedding: str,
    regulation_article: str | None,
    regulation_clause: str | None,
    location: str | None,
    title: str | None,
    doc_type: str,
    metadata_json: str,
) -> None:
    """단일 청크 삽입. vector/jsonb 는 CAST(:param AS type) 만 사용."""
    from sqlalchemy import text
    session.execute(
        text(f"""
            INSERT INTO {full_table}
            (doc_id, chunk_index, content, embedding, regulation_article, regulation_clause, location, title, doc_type, metadata_json)
            VALUES (:doc_id, :chunk_index, :content, {_SQL_CAST_VECTOR}, :regulation_article, :regulation_clause, :location, :title, :doc_type, {_SQL_CAST_JSONB})
        """),
        {
            "doc_id": doc_id,
            "chunk_index": chunk_index,
            "content": content,
            "embedding": embedding,
            "regulation_article": regulation_article,
            "regulation_clause": regulation_clause,
            "location": location,
            "title": title,
            "doc_type": doc_type,
            "metadata_json": metadata_json,
        },
    )


def _pgvector_search(
    session: Any,
    full_table: str,
    *,
    embedding: str,
    k: int,
    max_distance: float,
    doc_type_filter: str | None,
    metadata_filter: dict[str, Any] | None,
    prioritize_chapters: tuple[str, ...],
) -> list[Any]:
    """코사인 거리 기반 검색. CAST(:embedding AS vector), CAST(:filter_json AS jsonb) 만 사용."""
    from sqlalchemy import text
    sql = f"""
            SELECT id, doc_id, chunk_index, content, regulation_article, regulation_clause, location, title,
                   metadata_json,
                   1 - (embedding <=> {_SQL_CAST_VECTOR}) AS score
            FROM {full_table}
            WHERE (embedding <=> {_SQL_CAST_VECTOR}) <= :max_distance
        """
    params: dict[str, Any] = {"embedding": embedding, "k": k, "max_distance": max_distance}
    if doc_type_filter:
        sql += " AND doc_type = :doc_type"
        params["doc_type"] = doc_type_filter
    if metadata_filter and isinstance(metadata_filter, dict):
        sql += f" AND metadata_json @> {_SQL_CAST_JSONB_FILTER}"
        params["filter_json"] = json.dumps(metadata_filter, ensure_ascii=False)
    if prioritize_chapters:
        placeholders = ", ".join(f":ch{i}" for i in range(len(prioritize_chapters)))
        sql += f" ORDER BY ((metadata_json->>'chapter') IN ({placeholders})) DESC, embedding <=> {_SQL_CAST_VECTOR} LIMIT :k"
        for i, ch in enumerate(prioritize_chapters):
            params[f"ch{i}"] = ch
    else:
        sql += f" ORDER BY embedding <=> {_SQL_CAST_VECTOR} LIMIT :k"
    return list(session.execute(text(sql), params).fetchall())


def process_and_vectorize_pgvector(
    file_path: str | Path,
    rag_document_id: str,
    metadata: dict[str, Any] | None = None,
    *,
    chunk_size: int = 800,
    chunk_overlap: int = 120,
    doc_type: str = "REGULATION",
) -> dict[str, Any]:
    """
    PDF/Text → SemanticChunker(percentile) → OpenAI text-embedding-3-small (1536) → dwp_aura.rag_chunk Upsert.
    chunk_metadata에 page_number, file_path 포함 (출처 보기/Citation).
    """
    path = Path(file_path)
    emb = _get_embedding_client()
    if emb is None:
        return {"ok": False, "error": "Embedding client not available"}
    try:
        text_content = _load_text_from_file(path)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    try:
        from langchain_experimental.text_splitter import SemanticChunker
    except ImportError:
        return {"ok": False, "error": "pip install langchain-experimental"}
    splitter = SemanticChunker(
        embeddings=emb,
        breakpoint_threshold_type="percentile",
    )
    try:
        chunks_text = splitter.split_text(text_content)
    except Exception as e:
        logger.warning("SemanticChunker failed, fallback to RecursiveCharacterTextSplitter: %s", e)
        try:
            from langchain_text_splitters import RecursiveCharacterTextSplitter
            fallback = RecursiveCharacterTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                length_function=len,
            )
            chunks_text = fallback.split_text(text_content)
        except ImportError:
            return {"ok": False, "error": "pip install langchain-text-splitters (fallback)"}
    if not chunks_text:
        return {"ok": True, "rag_document_id": rag_document_id, "chunks_added": 0}
    meta = dict(metadata or {})
    regulation_article = meta.get("regulation_article") or meta.get("regulationArticle")
    regulation_clause = meta.get("regulation_clause") or meta.get("regulationClause")
    location = meta.get("location") or meta.get("regulationLocation")
    title = meta.get("title")
    if not location and (regulation_article or regulation_clause):
        location = f"규정 {regulation_article or ''} {regulation_clause or ''}".strip()

    file_path_str = str(path.resolve())
    is_pdf = path.suffix.lower() == ".pdf"

    from database.engine import get_engine, get_session
    from database.models.rag_chunk import FULL_TABLE, create_rag_chunk_table_if_not_exists

    engine = get_engine()
    create_rag_chunk_table_if_not_exists(engine)

    embeddings = emb.embed_documents(chunks_text)
    if len(embeddings) != len(chunks_text):
        return {"ok": False, "error": "Embedding count mismatch"}
    if embeddings and len(embeddings[0]) != EMBEDDING_DIM:
        return {"ok": False, "error": f"Embedding dim must be {EMBEDDING_DIM}"}

    with get_session() as session:
        _pgvector_delete_by_doc_id(session, FULL_TABLE, rag_document_id)
        for i, (content, vec) in enumerate(zip(chunks_text, embeddings)):
            page_number = _extract_page_from_chunk(content) if is_pdf else 1
            chunk_meta = {
                **meta,
                "page_number": page_number,
                "file_path": file_path_str,
            }
            vec_str = _embedding_to_pgvector(vec)
            _pgvector_insert_chunk(
                session,
                FULL_TABLE,
                doc_id=rag_document_id,
                chunk_index=i,
                content=content,
                embedding=vec_str,
                regulation_article=regulation_article,
                regulation_clause=regulation_clause,
                location=location,
                title=title,
                doc_type=doc_type,
                metadata_json=json.dumps(chunk_meta, ensure_ascii=False),
            )
    _notify_backend_rag_completed(rag_document_id)
    # Redis: workbench:rag:status 채널로 학습 완료 알림 (통일 포맷)
    try:
        from core.notifications import (
            publish_workbench_notification_sync,
            NOTIFICATION_CATEGORY_RAG_STATUS,
            REDIS_CHANNEL_WORKBENCH_RAG_STATUS,
        )
        settings = get_settings()
        channel = getattr(settings, "workbench_rag_status_channel", REDIS_CHANNEL_WORKBENCH_RAG_STATUS)
        publish_workbench_notification_sync(
            channel, NOTIFICATION_CATEGORY_RAG_STATUS, "학습 완료",
            rag_document_id=rag_document_id, chunks_added=len(chunks_text),
        )
    except Exception as e:
        logger.debug("RAG status notification publish skipped: %s", e)
    return {"ok": True, "rag_document_id": rag_document_id, "chunks_added": len(chunks_text)}


def retrieve_rag_pgvector(
    query: str,
    top_k: int = 10,
    *,
    bukrs: str | None = None,
    belnr: str | None = None,
    metadata_filter: dict[str, Any] | None = None,
    include_article_clause: bool = True,
    similarity_threshold: float = 0.75,
    doc_type_filter: str | None = "REGULATION",
    prioritize_chapters: tuple[str, ...] = ("제5장", "제6장"),
) -> list[dict[str, Any]]:
    """
    코사인 유사도(<=>) 기반 벡터 검색.
    - similarity_threshold 이상만 반환(무관한 규정 인용 방지).
    - doc_type_filter: 파일명이 아닌 doc_type 컬럼으로 필터. 회계 규정 분석 시 반드시 'REGULATION' 사용하여
      일반 매뉴얼(doc_type='GENERAL')이 회계 규정 분석에 혼입되지 않도록 격리. None이면 doc_type 조건 미적용.
    - prioritize_chapters: metadata_json.chapter가 이 값이면 최우선 정렬(제5장 부정 탐지, 제6장 정상 집행 기준 등).
    """
    emb = _get_embedding_client()
    if emb is None:
        return []
    from database.engine import get_engine, get_session
    from database.models.rag_chunk import FULL_TABLE, create_rag_chunk_table_if_not_exists

    engine = get_engine()
    create_rag_chunk_table_if_not_exists(engine)
    query_embedding = emb.embed_query(query)
    if len(query_embedding) != EMBEDDING_DIM:
        return []
    vec_str = _embedding_to_pgvector(query_embedding)
    k = max(1, min(top_k, 50))
    max_distance = 1.0 - max(0.0, min(1.0, float(similarity_threshold)))

    try:
        with get_session() as session:
            rows = _pgvector_search(
                session,
                FULL_TABLE,
                embedding=vec_str,
                k=k,
                max_distance=max_distance,
                doc_type_filter=doc_type_filter,
                metadata_filter=metadata_filter,
                prioritize_chapters=prioritize_chapters or (),
            )
    except Exception as e:
        logger.warning("retrieve_rag_pgvector query failed: %s", e)
        return []
    out: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        content = row[3] if len(row) > 3 else ""
        regulation_article = row[4] if len(row) > 4 else None
        regulation_clause = row[5] if len(row) > 5 else None
        location = row[6] if len(row) > 6 else None
        title = row[7] if len(row) > 7 else None
        metadata_json = row[8] if len(row) > 8 else None
        score = float(row[9]) if len(row) > 9 else (0.9 - i * 0.05)
        item = {
            "content": content,
            "excerpt": (content[:400] if len(content) > 400 else content),
            "score": round(score, 2),
            "rag_document_id": row[1] if len(row) > 1 else None,
            "sourceType": "DOCUMENT",
            "sourceKey": row[1] if len(row) > 1 else f"vec-{i}",
        }
        if isinstance(metadata_json, dict):
            if metadata_json.get("page_number") is not None:
                item["page_number"] = metadata_json["page_number"]
            if metadata_json.get("file_path"):
                item["file_path"] = metadata_json["file_path"]
        elif isinstance(metadata_json, str):
            try:
                meta = json.loads(metadata_json)
                if meta.get("page_number") is not None:
                    item["page_number"] = meta["page_number"]
                if meta.get("file_path"):
                    item["file_path"] = meta["file_path"]
            except (json.JSONDecodeError, TypeError):
                pass
        if include_article_clause:
            item["regulation_article"] = regulation_article
            item["regulation_clause"] = regulation_clause
            item["location"] = location or (f"규정 {regulation_article or ''} {regulation_clause or ''}".strip() or None)
            item["title"] = title
        out.append(item)
    return out


def process_and_vectorize(
    file_path: str | Path,
    rag_document_id: str,
    metadata: dict[str, Any] | None = None,
    *,
    chunk_size: int = 800,
    chunk_overlap: int = 120,
) -> dict[str, Any]:
    """
    PDF/Text 파일 수신 → Chunking → Embedding → Vector Store 저장.
    vector_store_type=pgvector 시 SemanticChunker(percentile) + dwp_aura.rag_chunk Upsert (page_number, file_path 포함).
    그 외 chroma 시 SemanticChunker 또는 CharacterTextSplitter + Chroma.

    Returns:
        {"ok": True, "rag_document_id": str, "chunks_added": int} 또는 {"ok": False, "error": str}.
    """
    settings = get_settings()
    vs_type = (getattr(settings, "vector_store_type", "none") or "").strip().lower()
    if vs_type == "pgvector":
        return process_and_vectorize_pgvector(
            file_path, rag_document_id, metadata,
            chunk_size=chunk_size, chunk_overlap=chunk_overlap,
        )
    store = get_vector_store()
    if store is None:
        return {"ok": False, "error": "Vector store not configured (vector_store_type=chroma or pgvector, deps installed)"}
    emb = _get_embedding_client()
    if emb is None:
        return {"ok": False, "error": "Embedding client not available"}
    path = Path(file_path)
    try:
        text = _load_text_from_file(path)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    try:
        from langchain_experimental.text_splitter import SemanticChunker
        splitter = SemanticChunker(embeddings=emb, breakpoint_threshold_type="percentile")
        chunks_text = splitter.split_text(text)
    except Exception as e:
        logger.debug("SemanticChunker for chroma failed, using CharacterTextSplitter: %s", e)
        try:
            from langchain_text_splitters import CharacterTextSplitter
            splitter = CharacterTextSplitter(
                separator="\n\n",
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                length_function=len,
            )
            chunks_text = splitter.split_text(text)
        except ImportError:
            return {"ok": False, "error": "pip install langchain-text-splitters"}
    file_path_str = str(path.resolve())
    is_pdf = path.suffix.lower() == ".pdf"
    meta_base = dict(metadata or {})
    meta_base["rag_document_id"] = rag_document_id
    meta_base["file_path"] = file_path_str
    from langchain_core.documents import Document
    documents = []
    for i, t in enumerate(chunks_text):
        page_number = _extract_page_from_chunk(t) if is_pdf else 1
        documents.append(
            Document(
                page_content=t,
                metadata={**meta_base, "chunk_index": i, "page_number": page_number},
            )
        )
    if not documents:
        return {"ok": True, "rag_document_id": rag_document_id, "chunks_added": 0}
    try:
        ids = [f"{rag_document_id}#{i}" for i in range(len(documents))]
        store.add_documents(documents, ids=ids)
    except Exception as e:
        logger.exception("Vector store add_documents failed")
        return {"ok": False, "error": str(e)}
    return {"ok": True, "rag_document_id": rag_document_id, "chunks_added": len(documents)}


# 회계 규정 분석 시 사용할 doc_type. 일반 매뉴얼(GENERAL)이 혼입되지 않도록 격리.
FINANCE_REGULATION_DOC_TYPE = "REGULATION"


def hybrid_retrieve(
    query: str,
    top_k: int = 10,
    metadata_filter: dict[str, Any] | None = None,
    *,
    include_article_clause: bool = True,
    bukrs: str | None = None,
    belnr: str | None = None,
    doc_type_filter: str | None = FINANCE_REGULATION_DOC_TYPE,
) -> list[dict[str, Any]]:
    """
    하이브리드 검색. vector_store_type=pgvector 시 코사인 유사도(<=>) + 전표 맥락(bukrs, belnr) 반영.
    검색 결과에 인용 정보(Article/Clause/location) 보존.

    doc_type_filter: 업로드된 문서의 doc_type으로 격리. 회계 규정 분석 시 'REGULATION'만 검색하여
    일반 매뉴얼(GENERAL)이 혼입되지 않도록 함. None이면 pgvector에서 doc_type 조건 미적용(다른 용도용).

    Returns:
        [{ "content", "excerpt", "score", "rag_document_id", "regulation_article", "regulation_clause", "location", "title", ... }]
    """
    settings = get_settings()
    vs_type = (getattr(settings, "vector_store_type", "none") or "").strip().lower()
    if vs_type == "pgvector":
        context_parts = [query]
        if bukrs:
            context_parts.append(f"bukrs {bukrs}")
        if belnr:
            context_parts.append(f"belnr {belnr}")
        sim_threshold = getattr(settings, "rag_similarity_threshold", 0.75)
        return retrieve_rag_pgvector(
            " ".join(context_parts),
            top_k,
            bukrs=bukrs,
            belnr=belnr,
            metadata_filter=metadata_filter,
            include_article_clause=include_article_clause,
            similarity_threshold=sim_threshold,
            doc_type_filter=doc_type_filter,
            prioritize_chapters=("제5장", "제6장"),
        )
    store = get_vector_store()
    if store is None:
        return []
    k = max(1, min(top_k, 50))
    try:
        # Chroma: similarity_search_with_score + filter
        if metadata_filter:
            results = store.similarity_search_with_score(query, k=k, filter=metadata_filter)
        else:
            results = store.similarity_search_with_score(query, k=k)
    except Exception as e:
        logger.warning("hybrid_retrieve similarity_search failed: %s", e)
        return []
    out: list[dict[str, Any]] = []
    for i, (doc, score) in enumerate(results):
        meta = getattr(doc, "metadata", {}) or {}
        content = getattr(doc, "page_content", "") or ""
        # 점수: Chroma는 거리(작을수록 유사)이므로 유사도로 변환 (1 / (1 + distance) 등)
        sim = 1.0 / (1.0 + float(score)) if score is not None else 0.9 - i * 0.05
        item = {
            "content": content,
            "excerpt": content[:400] if len(content) > 400 else content,
            "score": round(sim, 2),
            "rag_document_id": meta.get("rag_document_id"),
            "sourceType": "DOCUMENT",
            "sourceKey": meta.get("rag_document_id") or meta.get("docKey") or f"vec-{i}",
        }
        if include_article_clause:
            item["regulation_article"] = meta.get("regulation_article")
            item["regulation_clause"] = meta.get("regulation_clause")
            item["location"] = meta.get("location") or (
                f"규정 {meta.get('regulation_article') or ''} {meta.get('regulation_clause') or ''}".strip()
                or None
            )
            item["title"] = meta.get("title")
        out.append(item)
    return out


def chunk_artifacts(artifacts: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    """
    artifacts → (sourceType, sourceKey, excerpt, full_text) 리스트.

    policies, documents, openItems, fiDocument 순으로 추출.
    """
    chunks: list[tuple[str, str, str, str]] = []
    if not artifacts or not isinstance(artifacts, dict):
        return chunks

    for i, p in enumerate((artifacts.get("policies") or [])[:20]):
        if isinstance(p, dict):
            text = json.dumps(p, ensure_ascii=False)[:2000]
            key = p.get("id") or p.get("key") or f"POLICY-{i}"
            chunks.append(("POLICY", str(key), text[:500], text))
        elif isinstance(p, str):
            chunks.append(("POLICY", f"POLICY-{i}", p[:500], p))

    for i, d in enumerate((artifacts.get("documents") or [])[:20]):
        if isinstance(d, dict):
            text = json.dumps(d, ensure_ascii=False)[:2000]
            key = d.get("id") or d.get("docKey") or d.get("key") or f"DOC-{i}"
            chunks.append(("DOCUMENT", str(key), text[:500], text))
        elif isinstance(d, str):
            chunks.append(("DOCUMENT", f"DOC-{i}", d[:500], d))

    for i, o in enumerate((artifacts.get("openItems") or [])[:15]):
        if isinstance(o, dict):
            text = json.dumps(o, ensure_ascii=False)[:1500]
            key = o.get("id") or o.get("key") or f"OPEN-{i}"
            chunks.append(("OPEN_ITEM", str(key), text[:500], text))

    fi = artifacts.get("fiDocument") or {}
    if isinstance(fi, dict) and fi:
        text = json.dumps(fi, ensure_ascii=False)[:2000]
        key = fi.get("docKey") or fi.get("id") or "FI-DOC"
        chunks.append(("FI_DOCUMENT", str(key), text[:500], text))

    return chunks


def retrieve_rag(
    chunks: list[tuple[str, str, str, str]],
    top_k: int,
    *,
    min_refs_when_available: int = 2,
) -> list[dict[str, Any]]:
    """
    topK개 선택 후 ragRefs 형식으로 반환.

    refId, sourceType, sourceKey, excerpt, score. 정상 케이스(청크 2개 이상) 시
    min_refs_when_available 건 이상 반환.
    """
    k = (
        max(min_refs_when_available, min(top_k, len(chunks)))
        if len(chunks) >= min_refs_when_available
        else min(1, len(chunks))
    )
    refs: list[dict[str, Any]] = []
    for i, (stype, skey, excerpt, _) in enumerate(chunks[:k]):
        refs.append({
            "refId": f"ref-{i+1}",
            "sourceType": stype,
            "sourceKey": skey,
            "excerpt": excerpt[:400],
            "score": round(0.9 - i * 0.05, 2),
        })
    if not refs and chunks:
        refs.append({
            "refId": "ref-1",
            "sourceType": chunks[0][0],
            "sourceKey": chunks[0][1],
            "excerpt": chunks[0][2][:400],
            "score": 0.85,
        })
    return refs
