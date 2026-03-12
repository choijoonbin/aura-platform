"""
Core Configuration Module

환경변수 및 전역 설정을 관리하는 모듈.
Pydantic Settings를 사용하여 타입 안전성과 검증을 보장합니다.
"""

from functools import lru_cache
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    애플리케이션 전역 설정 클래스
    
    환경변수에서 값을 로드하며, .env 파일을 지원합니다.
    모든 설정은 타입 안전하며 자동으로 검증됩니다.
    """
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        # JWT_SECRET 환경 변수도 SECRET_KEY로 매핑 (dwp_backend 호환성)
        env_prefix="",
    )
    
    # ==================== LLM Configuration ====================
    # OpenAI (직접 연결) 또는 Azure OpenAI 중 하나 사용
    openai_api_key: str | None = Field(
        default=None,
        description="OpenAI API Key (Azure 미사용 시 필수)",
        json_schema_extra={"env": "OPENAI_API_KEY"},
    )
    openai_model: str = Field(
        default="gpt-4o-mini",
        description="OpenAI 모델 이름 (또는 Azure deployment name)",
    )
    model_version_pin: str | None = Field(
        default=None,
        description="모델 버전 핀 (설정 시 openai_model 대신 우선 사용). 예: gpt-4.1-2025-04-14",
    )
    openai_temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="LLM 응답의 창의성 제어 (0.0-2.0)",
    )
    openai_max_tokens: int = Field(
        default=2000,
        gt=0,
        description="LLM 응답의 최대 토큰 수",
    )
    # Azure OpenAI (설정 시 우선 사용)
    azure_openai_endpoint: str | None = Field(
        default=None,
        description="Azure OpenAI Endpoint (예: https://xxx.openai.azure.com/)",
    )
    azure_openai_api_key: str | None = Field(
        default=None,
        description="Azure OpenAI API Key",
    )
    azure_openai_deployment: str | None = Field(
        default=None,
        description="Azure deployment name (예: gpt-4o-mini). 미지정 시 openai_model 사용",
    )
    azure_openai_api_version: str = Field(
        default="2024-02-15-preview",
        description="Azure OpenAI API version",
    )
    prompt_version_pin: str = Field(
        default="aura-auditor-v1",
        description="프롬프트 버전 태그(실험/롤백 추적용)",
    )
    experiment_tag: str | None = Field(
        default=None,
        description="실험/AB 태그(로그·관측성용)",
    )
    # Embedding (Phase 6 RAG vector pipeline)
    openai_embedding_model: str = Field(
        default="text-embedding-3-small",
        description="OpenAI embedding model (OpenAI 직접 연결 시)",
    )
    azure_openai_embedding_deployment: str | None = Field(
        default=None,
        description="Azure OpenAI embedding deployment (설정 시 Azure 사용)",
    )
    # Vector store (Phase 6): "pgvector" | "chroma" | "pinecone" | "none"
    vector_store_type: str = Field(
        default="none",
        description="Vector store: pgvector (dwp_aura.rag_chunk), chroma, pinecone, none",
    )
    # Backend relay: 벡터화 완료 후 RagController에 processing_status 갱신 요청
    backend_rag_callback_url: str | None = Field(
        default=None,
        description="Backend RagController URL (예: POST {url}/rag/documents/{doc_id}/processing-status). 벡터화 완료 시 COMPLETED 전달",
    )
    # 로컬 공유 경로: 백엔드가 저장한 파일 경로로 수집 시, 이 경로 하위만 허용 (None이면 검사 생략)
    rag_allowed_document_base_path: str | None = Field(
        default=None,
        description="백엔드 document_path 수집 시 허용 기준 경로 (절대 경로). 설정 시 document_path는 이 경로 하위여야 함.",
    )
    # ── RAG Query Rewriter (검색 정합성 강화) ────────────────────────────────
    # retrieve_rag_pgvector 호출 전 SAP 코드·줄임말을 의미어로 자동 확장합니다.
    # 이미 명확한 한국어 쿼리는 LLM 호출 없이 그대로 통과 (비용 없음).
    # 재작성 쿼리로 0건이면 원본 쿼리로 자동 재시도 (안전망).
    rag_query_rewrite_enabled: bool = Field(
        default=True,
        description=(
            "RAG 검색 질의 재작성기 활성화.\n"
            "true(권장): SAP 코드(PA0030 등)·줄임말(법카·전표)·짧은 질의를\n"
            "  LLM이 의미어로 확장하여 벡터 검색 정확도를 향상시킵니다.\n"
            "  이미 명확한 한국어 질의는 LLM 호출 없이 그대로 통과합니다.\n"
            "  재작성 후 0건이면 원본 쿼리로 자동 재시도합니다.\n"
            "false: 질의를 그대로 벡터 검색. LLM 비용 최소화 환경에서 사용."
        ),
    )

    # RAG 검색: 무관한 규정 인용 방지 (pgvector)
    rag_similarity_threshold: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description="pgvector 유사도 하한. 이 값 미만 결과는 제외 (기본 0.75)",
    )
    rag_index_version: str | None = Field(
        default=None,
        description="RAG 지식 인덱스 버전 핀 (예: 2026Q1). 설정 시 metadata.index_version 필터로 검색 범위 고정",
    )
    rag_effective_date_override: str | None = Field(
        default=None,
        description="규정 효력일 강제값(YYYY-MM-DD). 미설정 시 case 발생일 기준",
    )
    rag_diag_disable_doc_ids_once: bool = Field(
        default=True,
        description="RAG 0건 시 동일 run에서 doc_ids 필터를 1회 해제해 원인 진단 로그를 남김(결과 반영 없음, 로그 전용).",
    )
    # MCP adapter (Aura-side) - 단계적 전환용
    mcp_enabled: bool = Field(
        default=True,
        description="Aura MCP adapter 활성화 여부. false면 기존 payload-only 로직만 사용.",
    )
    mcp_mode: str = Field(
        default="payload_only",
        description="MCP 동작 모드(payload_only | hybrid | remote). 현재 payload_only/hybrid 사용.",
    )
    mcp_base_url: str | None = Field(
        default=None,
        description="MCP tool 서버 base URL. 예: http://localhost:8086 또는 http://localhost:8080/api/synapse",
    )
    mcp_timeout_seconds: float = Field(
        default=5.0,
        ge=0.5,
        le=30.0,
        description="MCP tool HTTP timeout(초).",
    )
    mcp_require_fact_for_violation: bool = Field(
        default=True,
        description="사실(Fact) 컨텍스트가 부족하면 확정 위반 문구를 제한하는 보수 게이트.",
    )
    agentic_v2_enabled: bool = Field(
        default=False,
        description=(
            "finance_aura_v2_agentic 경로 활성화 여부.\n"
            "true면 v2를 우선 선택하고, false면 legacy(finance_aura)를 사용.\n"
            "주의: 변경 후 서버 재기동 필요."
        ),
    )
    agentic_v2_primary_agent_key: str = Field(
        default="finance_aura_v2_agentic",
        description="Agentic v2 주 경로 agent key.",
    )
    agentic_v2_legacy_agent_key: str = Field(
        default="finance_aura",
        description="레거시 분석 파이프라인 agent key.",
    )
    agentic_shadow_run_enabled: bool = Field(
        default=False,
        description=(
            "Shadow Run 활성화 여부.\n"
            "true면 primary 실행과 함께 shadow 비교 실행(정확도/재현성 비교용).\n"
            "주의: 호출량/지연/비용이 증가할 수 있으므로 운영 기본은 단계적으로 조정."
        ),
    )
    agentic_shadow_agent_key: str = Field(
        default="finance_aura_v2_agentic",
        description=(
            "Shadow Run 비교 실행용 agent key.\n"
            "권장: primary와 다른 key를 넣어 비교(예: primary=v2, shadow=legacy).\n"
            "primary와 동일 key면 비교 효용이 낮아짐."
        ),
    )
    agentic_shadow_sample_ratio: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description=(
            "Shadow Run 샘플 비율(0.0~1.0).\n"
            "1.0: 전건 비교, 0.2: 20% 샘플 비교.\n"
            "운영 부하를 보며 점진 조정 권장."
        ),
    )
    agentic_shadow_case_types: str = Field(
        default="HOLIDAY_USAGE",
        description=(
            "Shadow Run 대상 case_type 목록(쉼표 구분).\n"
            "예: HOLIDAY_USAGE,LIMIT_EXCEED\n"
            "목표 리스크 유형부터 제한적으로 켜고 확대 권장."
        ),
    )
    agentic_v2_emit_agent_stream: bool = Field(
        default=False,
        description=(
            "v2(primary)에서 AGENT_STREAM(설명형 문장) 이벤트 발행 여부.\n"
            "false(권장): AGENT_EVENT/step 중심 운영(실제 실행 이벤트 기반, 노이즈 최소화).\n"
            "true(디버그/시연용): AGENT_STREAM 문장 노출. 화면 중복/과다 문구가 발생할 수 있음.\n"
            "주의: 운영 기본값은 false 유지 권장."
        ),
    )
    # ── RAG 품질 게이트 (청킹 결과 검증) ────────────────────────────────────
    # 청킹이 완료된 직후 결과물을 자동으로 검사하는 품질 게이트입니다.
    # 메타데이터 누락 청크 제거 / 노이즈 청크 제거 / 중복 청크 제거 / 품질 리포트 생성을 수행합니다.
    rag_quality_gate_enabled: bool = Field(
        default=True,
        description=(
            "RAG 청킹 품질 게이트 활성화 여부.\n"
            "true(권장): 청킹 직후 노이즈 제거·중복 제거·필수 메타 검증·품질 리포트를 자동 수행.\n"
            "false: 품질 검증 없이 모든 청크를 그대로 반환. 디버깅 목적 외 비권장."
        ),
    )
    rag_quality_strict_mode: bool = Field(
        default=True,
        description=(
            "품질 게이트 strict 모드.\n"
            "true(권장): 필수 메타(regulation_article 등) 누락 또는 유효 청크 0건이면 청킹 자체를 실패 처리.\n"
            "  → 빈 인덱스나 불완전한 청크가 벡터 DB에 저장되는 것을 원천 차단.\n"
            "false: 경고 로그만 남기고 결과를 그대로 반환. 테스트·비표준 문서 처리 시 임시로 사용 가능."
        ),
    )
    rag_chunk_min_chars: int = Field(
        default=80,
        ge=1,
        description=(
            "품질 게이트: 청크의 최소 텍스트 길이(char).\n"
            "이 값 미만인 청크(예: '제1장', '부칙' 등 제목만 있는 청크)는 노이즈로 분류되어 제거됩니다.\n"
            "줄이면: 짧은 제목·번호 청크도 살아남아 검색 품질이 떨어질 수 있음.\n"
            "늘리면: 짧지만 의미 있는 단일 조항 청크까지 제거될 수 있음. 80자가 적절한 균형점."
        ),
    )
    rag_chunk_article_coverage_threshold: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description=(
            "품질 게이트: REGULATION/HIERARCHICAL 문서의 regulation_article 최소 커버리지.\n"
            "전체 청크 중 regulation_article 메타가 채워진 비율이 이 값 미만이면 품질 경고가 발생합니다.\n"
            "0.8(기본): 80% 이상 청크에 조항 번호가 붙어야 정상.\n"
            "줄이면: 조항 추출 실패율이 높아도 경고가 발생하지 않아 검색 품질 저하를 모르고 넘어갈 수 있음.\n"
            "늘리면: 비표준 문서(1.1.1 체계 등)에서 잦은 경고 발생. strict 모드와 함께 사용 시 자주 실패할 수 있음."
        ),
    )
    rag_chunk_max_noise_rate: float = Field(
        default=0.35,
        ge=0.0,
        le=1.0,
        description=(
            "품질 게이트: 최대 허용 노이즈 청크 비율.\n"
            "전체 청크 중 rag_chunk_min_chars 미만(너무 짧음) 또는 의미 없는 청크의 비율이\n"
            "이 값을 초과하면 품질 게이트 경고 또는 실패(strict 모드)로 처리됩니다.\n"
            "0.35(기본): 35% 이상이 노이즈이면 문제 있다고 판단.\n"
            "줄이면: 기준이 엄격해져 조금만 노이즈가 많아도 실패. 고품질 문서 전용 환경에 적합.\n"
            "늘리면: 기준이 느슨해져 노이즈가 많은 문서도 통과. 스캔 PDF 등 저품질 문서 처리 시 임시 사용."
        ),
    )
    rag_chunk_max_duplicate_rate: float = Field(
        default=0.20,
        ge=0.0,
        le=1.0,
        description=(
            "품질 게이트: 최대 허용 중복 청크 비율.\n"
            "내용이 동일하거나 매우 유사한 청크가 전체 대비 이 비율을 초과하면 경고/실패.\n"
            "중복 청크는 벡터 DB에서 같은 내용이 반복 검색되어 응답 품질을 낮춥니다.\n"
            "0.20(기본): 20% 이상 중복이면 문제로 판단.\n"
            "줄이면: 조금의 중복도 허용하지 않음. contextual injection(요약 삽입) 적용 후에는\n"
            "  내용이 비슷한 청크가 생길 수 있어 너무 낮으면 오탐 가능.\n"
            "늘리면: 중복 청크가 많아도 통과. 비권장."
        ),
    )
    rag_chunk_max_short_chunk_rate: float = Field(
        default=0.20,
        ge=0.0,
        le=1.0,
        description=(
            "품질 게이트: 최대 허용 저정보 청크(짧거나 제목만 있는 청크) 비율.\n"
            "rag_chunk_min_chars 이상이지만 실질적 내용이 없는 heading-only 청크 포함.\n"
            "0.20(기본): 전체의 20% 이상이 저정보 청크이면 경고/실패.\n"
            "줄이면: 더 엄격하게 저정보 청크를 허용하지 않음.\n"
            "늘리면: 목차 구조가 많은 문서(부칙·별표 등이 많은 규정집)에서 잦은 실패를 방지."
        ),
    )

    # ── v1 계층형 2차 세분화 (Hybrid Sub-chunking) ───────────────────────────
    # HIERARCHICAL(계층형) 문서에서 '장-조-항-호' 1차 분할 후,
    # 길이가 긴 조항 내부를 다시 잘게 쪼개는 2차 청킹 설정입니다.
    rag_hybrid_subchunk_enabled: bool = Field(
        default=True,
        description=(
            "계층형 문서(HIERARCHICAL) 2차 세분화 활성화.\n"
            "true(권장): 1차 분할로 생긴 큰 청크(예: 긴 제9조 전체) 내부를\n"
            "  rag_hybrid_subchunk_size 기준으로 다시 잘게 쪼개 검색 정밀도 향상.\n"
            "false: 1차 분할(장·조 단위)만 수행. 청크 크기가 불균일해져\n"
            "  LLM 컨텍스트 윈도우를 초과하는 대형 청크가 생길 수 있음."
        ),
    )
    rag_hybrid_subchunk_size: int = Field(
        default=420,
        ge=120,
        le=1200,
        description=(
            "계층형 2차 세분화 목표 청크 크기(char).\n"
            "1차 분할 후 이 크기를 초과하는 청크를 다시 분할하는 기준값.\n"
            "줄이면(예: 200~300): 더 세밀하게 분할 → 검색 정밀도 ↑, 컨텍스트 손실 가능성 ↑.\n"
            "늘리면(예: 600~800): 청크가 더 길어짐 → 컨텍스트 보존 ↑, 검색 노이즈 가능성 ↑.\n"
            "420자(기본)는 GPT-4o의 최적 청크 크기 연구 기준값(~100 token)에 근거."
        ),
    )
    rag_hybrid_subchunk_overlap: int = Field(
        default=80,
        ge=0,
        le=300,
        description=(
            "계층형 2차 세분화 청크 간 중첩(overlap) 크기(char).\n"
            "연속된 두 청크가 이 크기만큼 내용을 공유하여, 청크 경계에서 의미 단절을 방지합니다.\n"
            "줄이면(예: 0~40): 청크 경계에서 문맥 단절 위험 증가. 총 청크 수 감소.\n"
            "늘리면(예: 120~200): 경계 단절 방지 효과 ↑, 중복 내용 ↑. 벡터 DB 저장 용량 증가."
        ),
    )
    rag_hybrid_subchunk_min_chars: int = Field(
        default=140,
        ge=20,
        le=400,
        description=(
            "계층형 2차 세분화 후 하위 청크 최소 길이(char).\n"
            "분할 결과 이 길이보다 짧은 청크는 이전 청크와 합쳐(merge)집니다.\n"
            "줄이면: 짧은 단독 문장도 별도 청크로 허용 → 청크 수 증가, 노이즈 가능.\n"
            "늘리면: 더 많은 짧은 청크가 합쳐짐 → 청크 수 감소, 개별 청크 내용이 더 풍부해짐."
        ),
    )

    # ── Agentic 청킹 버전 전환 ────────────────────────────────────────────────
    # 환경변수 RAG_CHUNKING_VERSION=v1 또는 v2 로 즉시 전환 가능합니다.
    # v2가 기본값이며, 문제 발생 시 v1으로 즉시 롤백할 수 있습니다.
    rag_chunking_version: str = Field(
        default="v2",
        description=(
            "RAG 청킹 엔진 버전 선택.\n"
            "v1: 기존 rule-based 청킹. 정규식 기반 장·조·항·호 분리. 빠르고 안정적. LLM 비용 없음.\n"
            "v2(기본): 에이전트형 LLM 보강 청킹. 4단계 파이프라인(프로파일링→청킹→보강→자기교정).\n"
            "  → 비표준 문서, 복잡한 표 포함 문서, 혼합 구조 문서에서 검색 품질이 크게 향상됨.\n"
            "롤백 방법: 환경변수 RAG_CHUNKING_VERSION=v1 설정 후 서버 재시작 (코드 변경 불필요)."
        ),
    )

    # ── Agentic Chunking v2: 4단계 파이프라인 기능 플래그 ────────────────────
    # 각 단계를 개별적으로 켜고 끌 수 있습니다.
    # 문제 원인 추적 시: 하나씩 false로 변경하여 어느 단계가 문제인지 격리할 수 있습니다.
    # 전체 비활성화 시: rag_chunking_version=v1 을 사용하는 것이 더 간단합니다.
    rag_chunking_v2_profiling_enabled: bool = Field(
        default=True,
        description=(
            "[v2 Step 1] LLM 문서 프로파일링 활성화.\n"
            "true(권장): 청킹 시작 전 LLM이 문서 전체를 분석하여\n"
            "  - 구조 유형(표준 법령 체계 / 1.1.1 비표준 / 혼합형)\n"
            "  - 문서 성격(규정집 / 매뉴얼 / 지침)\n"
            "  - 최적 청킹 전략(hierarchical / outline / semantic)\n"
            "  - 커스텀 앵커 패턴(이 문서 고유의 구분자) 을 결정합니다.\n"
            "false: 기본 전략(hierarchical)으로 고정. 비표준 구조 문서에서 품질 저하 가능.\n"
            "  LLM API 비용을 절감하려는 경우 또는 모든 문서가 표준 체계일 때 사용."
        ),
    )
    rag_chunking_v2_layout_aware_enabled: bool = Field(
        default=True,
        description=(
            "[v2 Step 2] Layout-Aware 전처리 활성화.\n"
            "true(권장): 청킹 전에 문서의 표(Table)·리스트 블록을 감지하여\n"
            "  해당 구간에 특수 마커를 삽입, 청킹 중 표 내부가 잘리지 않도록 보호합니다.\n"
            "  → '1일 2회 | 5만원 이하 | ...' 같은 표 데이터가 세로로 깨지는 현상 방지.\n"
            "false: 표·리스트 보호 없이 일반 텍스트로 처리. 표가 없는 순수 텍스트 문서에서는 불필요."
        ),
    )
    rag_chunking_v2_semantic_hybrid_enabled: bool = Field(
        default=True,
        description=(
            "[v2 Step 2] Semantic Hybrid Sub-chunking 활성화.\n"
            "true(권장): 1차 청킹으로 생성된 대형 청크 내부에\n"
            "  임베딩 유사도 계산을 통해 의미 경계를 탐지하고 추가 분할합니다.\n"
            "  → '제9조(여비 종류)' 안에 5가지 여비가 섞여 있을 때, 각 항목별로 분리.\n"
            "  → 단순 글자 수가 아닌 의미 변화 지점에서 분할하므로 검색 정밀도 향상.\n"
            "false: 의미 기반 세분화 없이 크기 기반 분할만 수행. Embedding API 호출 횟수 감소.\n"
            "  주의: OpenAI Embedding API를 추가로 호출하므로 비용·시간이 소폭 증가."
        ),
    )
    rag_chunking_v2_context_inject_enabled: bool = Field(
        default=True,
        description=(
            "[v2 Step 3] 상위 컨텍스트 텍스트 본문 주입(Contextual Retrieval) 활성화.\n"
            "true(권장): 각 청크 본문 맨 앞에 '[문서 요약: ...][경로: 제3장 > 제9조]' 형태의\n"
            "  상위 컨텍스트를 직접 삽입합니다(메타데이터 X, 실제 텍스트 O).\n"
            "  → LLM이 '제9조' 청크만 보고도 이것이 여비 규정의 어느 부분인지 바로 파악.\n"
            "  → Anthropic 연구 기준 RAG 검색 정확도 35~50% 향상 효과.\n"
            "false: 컨텍스트 없이 원본 텍스트만 청크에 포함. 메타데이터만 활용하는 검색 방식과 동일."
        ),
    )
    rag_chunking_v2_llm_enrich_enabled: bool = Field(
        default=True,
        description=(
            "[v2 Step 3] LLM 기반 메타데이터 보강 활성화.\n"
            "true(권장): 청킹 후 regulation_article·location 등이 비어 있는 청크에 대해\n"
            "  LLM이 내용을 분석하여 누락된 메타데이터를 자동으로 채워 넣습니다.\n"
            "  → 정규식으로 추출 실패한 비표준 조항 번호(예: '3-1-나') 등을 LLM이 보완.\n"
            "false: 규칙 기반 추출 실패 시 해당 메타데이터가 빈 채로 저장됨.\n"
            "  메타데이터 필터링 검색을 사용하지 않는다면 false로도 무방."
        ),
    )
    rag_chunking_v2_llm_verify_enabled: bool = Field(
        default=True,
        description=(
            "[v2 Step 4] Self-Correction Loop(LLM 자기교정) 활성화.\n"
            "true(권장): 최종 청크 목록을 LLM이 검토하여\n"
            "  - 의미가 단절된 두 청크 → 병합(merge)\n"
            "  - 서로 다른 조항이 합쳐진 청크 → 분리(split)\n"
            "  작업을 실제 청크에 적용합니다. v2의 핵심 고도화 기능.\n"
            "false: LLM 검토 없이 청킹 결과를 그대로 사용.\n"
            "  비용 절감이 최우선이거나 빠른 처리가 필요한 경우 사용.\n"
            "  주의: LLM API 추가 호출이 발생하며, 문서 크기에 따라 처리 시간이 늘어날 수 있음."
        ),
    )
    rag_chunking_v2_feedback_enabled: bool = Field(
        default=True,
        description=(
            "[v2 Feedback] LLM Quality Feedback Loop 활성화.\n"
            "true(권장): Self-Correction 이후 샘플 청크를 LLM이 RAG 검색 적합성 기준으로 평가.\n"
            "  - 'poor' 판정을 받은 청크는 인접 청크와 자동 병합하여 품질을 끌어올립니다.\n"
            "  - 이 단계는 LLM 주관 평가이므로 아래 score 기반 피드백 루프와 상호 보완적입니다.\n"
            "false: 내용 기반 LLM 품질 평가 생략. 처리 속도 향상, LLM 비용 절감.\n"
            "  score 기반 피드백 루프(rag_score_tracking_enabled)만으로 충분한 경우 비활성화 가능."
        ),
    )

    # ── RAG 자동 재청킹 트리거 (품질 게이트 미달 시) ──────────────────────────
    # v1으로 청킹한 결과가 품질 게이트 기준에 미달하면, 백그라운드에서 자동으로 v2 재청킹을 시도합니다.
    # 재청킹은 비동기 백그라운드 작업으로 실행되므로, 최초 응답은 v1 결과를 그대로 반환합니다.
    rag_reindex_auto_trigger_enabled: bool = Field(
        default=True,
        description=(
            "v1 청킹 품질 미달 시 v2 재청킹 자동 트리거 활성화.\n"
            "true(권장): rag_chunking_version=v1인 경우, 청킹 완료 후 품질 리포트를 확인하여\n"
            "  아래 기준(article_coverage / noise_rate / short_chunk_rate)에 미달하면\n"
            "  백그라운드에서 자동으로 v2 재청킹을 실행합니다.\n"
            "  → 운영자 개입 없이 저품질 인덱스를 자동 복구.\n"
            "false: 품질 미달이어도 재청킹하지 않음. v2를 기본값(rag_chunking_version=v2)으로\n"
            "  사용하거나, 수동 재청킹 엔드포인트를 활용하는 환경에서 사용."
        ),
    )
    rag_reindex_article_coverage_min: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description=(
            "자동 재청킹 트리거 기준: regulation_article 커버리지 최솟값.\n"
            "v1 청킹 결과의 article_coverage(조항 번호가 붙은 청크 비율)가\n"
            "이 값 미만이면 자동 재청킹 트리거가 발동됩니다.\n"
            "0.6(기본): 60% 이상 조항 번호가 없으면 v2로 재청킹.\n"
            "줄이면: 트리거 기준이 느슨해져 재청킹 빈도 감소.\n"
            "늘리면: 기준이 엄격해져 재청킹을 더 자주 실행. 비용·처리 시간 증가."
        ),
    )
    rag_reindex_noise_rate_max: float = Field(
        default=0.4,
        ge=0.0,
        le=1.0,
        description=(
            "자동 재청킹 트리거 기준: 최대 허용 노이즈 비율.\n"
            "v1 청킹 결과의 noise_rate(짧거나 의미 없는 청크 비율)가\n"
            "이 값을 초과하면 자동 재청킹을 실행합니다.\n"
            "0.4(기본): 40% 이상이 노이즈면 v2로 재청킹.\n"
            "줄이면: 조금만 노이즈가 많아도 즉시 재청킹. v2 비용 증가.\n"
            "늘리면: 많은 노이즈를 허용하고 재청킹하지 않음. 검색 품질 저하 가능."
        ),
    )
    rag_reindex_short_chunk_rate_max: float = Field(
        default=0.4,
        ge=0.0,
        le=1.0,
        description=(
            "자동 재청킹 트리거 기준: 최대 허용 저정보 청크 비율.\n"
            "v1 청킹 결과의 short_chunk_rate(짧은/제목만 있는 청크 비율)가\n"
            "이 값을 초과하면 자동 재청킹을 실행합니다.\n"
            "0.4(기본): 40% 이상이 저정보 청크면 v2로 재청킹.\n"
            "줄이면: 저정보 청크가 조금만 있어도 재청킹. v2 처리 빈도 증가.\n"
            "늘리면: 저정보 청크가 많아도 재청킹하지 않음. 목차·부칙 비중이 높은 문서에서 완화 가능."
        ),
    )

    # ── RAG Score 기반 피드백 루프 (진짜 피드백 루프) ────────────────────────
    # 사용자가 실제로 검색할 때마다 각 문서(doc_id)의 유사도 점수(score)를 Redis에 누적합니다.
    # 롤링 평균이 임계값 아래로 내려가면 → 재청킹 대기 큐에 등록 → 백그라운드 워커가 v2 재청킹 실행.
    # 이 방식은 LLM 주관 평가가 아닌, 실제 사용자 검색 결과에 기반한 객관적 품질 측정입니다.
    #
    # 동작 흐름:
    #   retrieve_rag_pgvector 호출
    #     → 검색 결과의 score를 Redis(rag:score_stats:{doc_id})에 누적
    #     → 누적 횟수 >= rag_score_min_searches_before_reindex AND
    #        평균 score < rag_score_avg_threshold
    #     → rag:reindex_queue에 재청킹 태스크 적재
    #     → _score_based_reindex_worker 가 rag_score_worker_poll_seconds 마다 폴링
    #     → process_and_vectorize_v2 자동 실행 → 완료 후 통계 초기화
    rag_score_tracking_enabled: bool = Field(
        default=True,
        description=(
            "RAG Score 기반 피드백 루프 활성화.\n"
            "true(권장): 모든 retrieve_rag_pgvector 호출 시 doc_id별 유사도 점수를 Redis에 자동 누적.\n"
            "  누적 데이터가 쌓이면 평균 score를 계산하여 재청킹 필요 여부를 자동 판단합니다.\n"
            "false: score 누적 없음. 품질 피드백 루프 비활성화.\n"
            "  Redis 미사용 환경 또는 인프라 비용 최소화 환경에서 사용.\n"
            "  주의: Redis 연결 실패 시에도 graceful fallback으로 검색에는 영향 없음."
        ),
    )
    rag_score_avg_threshold: float = Field(
        default=0.65,
        ge=0.0,
        le=1.0,
        description=(
            "재청킹 트리거 기준: 롤링 평균 유사도 점수 임계값.\n"
            "특정 문서의 누적 평균 score(코사인 유사도)가 이 값 미만이 되면\n"
            "재청킹 대기 큐에 등록합니다.\n"
            "0.65(기본): 평균 65% 이하 유사도는 청크 품질이 낮다고 판단.\n"
            "줄이면(예: 0.5): 매우 낮은 품질의 문서만 재청킹. 재청킹 빈도 감소.\n"
            "늘리면(예: 0.75): 조금만 낮아도 재청킹 시도. 품질에 더 민감하게 반응하지만\n"
            "  잦은 재청킹으로 LLM 비용 및 서버 부하 증가."
        ),
    )
    rag_score_min_searches_before_reindex: int = Field(
        default=5,
        ge=1,
        le=100,
        description=(
            "재청킹 판정 전 최소 누적 검색 횟수.\n"
            "이 횟수만큼 검색이 누적되어야 비로소 평균 score를 계산하고 재청킹 여부를 판단합니다.\n"
            "5(기본): 5번 이상 검색된 문서만 판정. 1~2번 검색된 이상치에 의한 오작동 방지.\n"
            "줄이면(예: 2~3): 적은 검색 이력으로도 빠르게 재청킹. 통계적 신뢰도 낮음.\n"
            "늘리면(예: 10~20): 충분한 데이터로 판정하여 오탐 감소.\n"
            "  신규 문서는 충분히 검색된 후에야 피드백이 반영됨."
        ),
    )
    rag_score_worker_poll_seconds: int = Field(
        default=30,
        ge=5,
        le=300,
        description=(
            "재청킹 큐 워커(백그라운드)의 폴링 간격(초).\n"
            "앱 시작 시 생성된 백그라운드 워커가 이 주기마다 rag:reindex_queue를 확인하여\n"
            "대기 중인 재청킹 태스크를 꺼내 v2 재청킹을 실행합니다.\n"
            "30초(기본): 큐에 태스크가 쌓이면 최대 30초 내에 처리 시작.\n"
            "줄이면(예: 5~10초): 더 빠르게 재청킹 시작. Redis poll 빈도 증가 (미미한 수준).\n"
            "늘리면(예: 60~300초): 즉각성이 낮아지지만 서버 부하 감소.\n"
            "  재청킹은 즉시성이 중요하지 않으므로 서버 부하에 따라 자유롭게 조정 가능."
        ),
    )
    # RAG 벡터화 응답: 청크 배치 크기 (20~50). 대용량 시 메모리·전송 부담 완화.
    rag_chunk_batch_size: int = Field(
        default=30,
        ge=20,
        le=50,
        description="청크를 끊어서 전달할 단위 개수 (20~50). 응답 batches 또는 백엔드 저장 API 호출 단위.",
    )
    # 백엔드 청크 저장 API (설정 시 Aura가 배치 단위로 POST. 미설정 시 응답 body에 batches 반환)
    backend_rag_chunks_save_url: str | None = Field(
        default=None,
        description="청크 배치 저장 URL. {doc_id} 플레이스홀더 사용 가능. 예: https://backend/api/rag/documents/{doc_id}/chunks",
    )
    # 청킹/벡터화 완료 시 Synapse에 상태 전달 (POST /api/synapse/rag/status, 진행 중은 백엔드 관리)
    synapse_rag_status_url: str | None = Field(
        default=None,
        description="RAG 상태 전달 URL (미지정 시 dwp_gateway_url + /api/synapse/rag/status). 청킹 종료 시 COMPLETED 1회만 호출.",
    )
    chroma_persist_dir: str = Field(
        default="./data/chroma",
        description="Chroma persistence directory (vector_store_type=chroma)",
    )
    chroma_collection_name: str = Field(
        default="aura_rag",
        description="Chroma collection name",
    )
    pinecone_api_key: str | None = Field(default=None, description="Pinecone API key")
    pinecone_index_name: str = Field(
        default="aura-rag",
        description="Pinecone index name",
    )
    pinecone_namespace: str = Field(
        default="default",
        description="Pinecone namespace",
    )

    # ==================== Application Configuration ====================
    app_env: str = Field(
        default="development",
        description="애플리케이션 환경 (development, staging, production)"
    )
    app_name: str = Field(
        default="Aura-Platform",
        description="애플리케이션 이름"
    )
    app_version: str = Field(
        default="0.1.0",
        description="애플리케이션 버전"
    )
    debug: bool = Field(
        default=True,
        description="디버그 모드 활성화 여부"
    )
    
    # ==================== API Configuration ====================
    api_host: str = Field(
        default="0.0.0.0",
        description="API 서버 호스트"
    )
    api_port: int = Field(
        default=9000,
        gt=0,
        lt=65536,
        description="API 서버 포트"
    )
    api_reload: bool = Field(
        default=True,
        description="자동 리로드 활성화 (개발 모드용)"
    )
    
    # ==================== Database Configuration ====================
    database_url: str = Field(
        default="postgresql://user:password@localhost:5432/aura_platform",
        description="PostgreSQL 데이터베이스 URL"
    )
    database_pool_size: int = Field(
        default=10,
        gt=0,
        description="데이터베이스 연결 풀 크기"
    )
    database_max_overflow: int = Field(
        default=20,
        gt=0,
        description="데이터베이스 연결 풀 최대 오버플로우"
    )
    
    # ==================== Redis Configuration ====================
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis 서버 URL"
    )
    redis_max_connections: int = Field(
        default=10,
        gt=0,
        description="Redis 최대 연결 수"
    )
    redis_ttl: int = Field(
        default=86400,
        gt=0,
        description="Redis 키 기본 TTL (초, 기본: 24시간)"
    )
    redis_checkpoint_ttl: int = Field(
        default=604800,
        gt=0,
        description="LangGraph Checkpoint TTL (초, 기본: 7일)"
    )
    
    # ==================== Security Configuration ====================
    # SECRET_KEY 또는 JWT_SECRET 환경 변수 지원 (dwp_backend 호환성)
    secret_key: str | None = Field(
        default=None,
        min_length=32,
        description="JWT 토큰 서명용 비밀 키 (dwp_backend와 동일해야 함, 최소 32바이트). SECRET_KEY 또는 JWT_SECRET 환경 변수 사용"
    )
    jwt_secret: str | None = Field(
        default=None,
        min_length=32,
        description="JWT_SECRET 환경 변수 (secret_key가 없을 때 사용)"
    )
    algorithm: str = Field(
        default="HS256",
        description="JWT 알고리즘"
    )

    @model_validator(mode="after")
    def validate_secret_key(self) -> "Settings":
        """
        SECRET_KEY 또는 JWT_SECRET 환경 변수 중 하나는 필수입니다.
        JWT_SECRET이 있으면 secret_key에 할당합니다.
        """
        if not self.secret_key and self.jwt_secret:
            self.secret_key = self.jwt_secret

        if not self.secret_key:
            raise ValueError(
                "SECRET_KEY or JWT_SECRET environment variable is required "
                "(minimum 32 bytes for HS256 algorithm)"
            )

        if len(self.secret_key) < 32:
            raise ValueError(
                f"SECRET_KEY must be at least 32 bytes (current: {len(self.secret_key)} bytes). "
                "For HS256 algorithm, 256-bit (32-byte) key is required."
            )

        return self

    @model_validator(mode="after")
    def validate_llm_config(self) -> "Settings":
        """OpenAI 또는 Azure OpenAI 중 하나는 설정되어야 합니다."""
        use_azure = bool(self.azure_openai_endpoint and self.azure_openai_api_key)
        use_openai = bool(self.openai_api_key)
        if not use_azure and not use_openai:
            raise ValueError(
                "LLM 설정 필요: OPENAI_API_KEY 또는 (AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY)"
            )
        return self
    access_token_expire_minutes: int = Field(
        default=30,
        gt=0,
        description="액세스 토큰 만료 시간 (분)"
    )
    allowed_origins: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:8001"],
        description="CORS 허용 Origin (dwp_frontend, dwp_backend)"
    )
    require_auth: bool = Field(
        default=True,
        description="JWT 인증 필수 여부 (개발 시 false 가능)"
    )
    # S2S(서비스 간) 인증: BE 등 신뢰 서버가 X-Internal-Service-Key로 호출 시 JWT 없이 허용. 내부 네트워크에서만 사용 권장.
    aura_internal_api_key: str | None = Field(
        default=None,
        description="내부 서비스 전용 API Key (X-Internal-Service-Key와 일치 시 인증 통과). 미설정 시 비활성.",
    )
    
    # ==================== Logging Configuration ====================
    log_level: str = Field(
        default="DEBUG",
        description="로그 레벨 (DEBUG, INFO, WARNING, ERROR, CRITICAL). 환경변수 LOG_LEVEL로 오버라이드 가능.",
    )
    log_format: str = Field(
        default="json",
        description="로그 포맷 (json, text)"
    )
    
    # ==================== Domain Configuration ====================
    dev_domain_enabled: bool = Field(
        default=True,
        description="Dev Domain 활성화 여부"
    )
    finance_domain_enabled: bool = Field(
        default=True,
        description="Finance Domain 활성화 여부"
    )
    hr_domain_enabled: bool = Field(
        default=False,
        description="HR Domain 활성화 여부"
    )
    
    # ==================== Synapse Backend (Finance Tool API) ====================
    synapse_base_url: str = Field(
        default="http://localhost:8080/api/synapse/agent-tools",
        description="Synapse Agent Tool API Base URL (Gateway 8080 경유, Finance 도메인용)",
    )
    synapse_timeout: float = Field(
        default=30.0,
        gt=0,
        description="Synapse HTTP 요청 타임아웃 (초)",
    )
    synapse_max_retries: int = Field(
        default=3,
        ge=0,
        description="5xx/timeout 시 최대 재시도 횟수",
    )
    hitl_timeout_seconds: int = Field(
        default=300,
        gt=0,
        description="HITL 승인 대기 타임아웃 (초, 기본 5분)",
    )
    audit_events_enabled: bool = Field(
        default=True,
        description="Audit 이벤트 발행 활성화 (Synapse audit_event_log 연동)",
    )
    audit_delivery_mode: str = Field(
        default="redis",
        description="전달 방식: redis(2안, 권장) | http(1안). redis=Redis Pub/Sub, Synapse가 구독하여 audit_event_log 저장",
    )
    audit_redis_channel: str = Field(
        default="audit:events:ingest",
        description="Redis Pub/Sub 채널 (audit_delivery_mode=redis 시 사용)",
    )
    case_action_redis_channel: str = Field(
        default="workbench:case:action",
        description="승인/거절 조치 완료 시 Redis Pub/Sub 채널 (워크벤치/에이전트 Refetch 알림)",
    )
    workbench_rag_status_channel: str = Field(
        default="workbench:rag:status",
        description="RAG 벡터화 완료 시 Redis Pub/Sub 채널 (학습 완료 알림)",
    )
    workbench_alert_channel: str = Field(
        default="workbench:alert",
        description="신규 고위험 케이스 탐지 시 Redis Pub/Sub 채널 (AI_DETECT 알림)",
    )
    hitl_feedback_log_path: str | None = Field(
        default=None,
        description="HITL 피드백 JSONL 파일 경로 (설정 시 가중치 업데이트용 로그 적재, 예: data/hitl_feedback.jsonl)",
    )
    audit_ingest_url: str | None = Field(
        default=None,
        description="Audit API URL (audit_delivery_mode=http 시, 미지정 시 synapse_base_url + /api/synapse/audit/events/ingest)",
    )
    agent_stream_events_enabled: bool = Field(
        default=True,
        description="Agent Stream 이벤트 push 활성화 (Prompt C: Dashboard Agent Execution Stream)",
    )
    agent_stream_push_url: str | None = Field(
        default=None,
        description="Agent Stream push URL (미지정 시 http://localhost:8080/api/synapse/agent/events)",
    )

    # ==================== Audit Analysis BE Callback ====================
    dwp_gateway_url: str = Field(
        default="http://localhost:8080",
        description="Gateway Base URL (BE 콜백용, 예: http://localhost:8080)",
    )
    callback_path: str = Field(
        default="/api/synapse/internal/aura/callback",
        description="BE 콜백 경로 (DWP_GATEWAY_URL과 결합)",
    )
    agent_config_path: str | None = Field(
        default=None,
        description="에이전트 설정 조회 경로 (기본: api/v1/agents/config). Query: agent_key, Header: X-Tenant-ID 필수.",
    )
    agent_config_cache_ttl_seconds: int = Field(
        default=300,
        ge=0,
        description="에이전트 설정 캐시 TTL (초). 기본 300초(5분). 0이면 캐시 비활성화 (매번 API 호출). Backend에서 docIds 변경 시 최대 이 시간 후 반영.",
    )
    web_search_max_calls_per_run: int = Field(
        default=5,
        ge=0,
        description="run당 web_search 호출 상한 (백엔드 가드레일과 동기화 권장). 0=제한 없음",
    )
    # RAG 우선순위: 내부 규정 유사도가 이 값 미만일 때만 외부 검색 수행 (임시 0.7)
    web_search_rag_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="내부 RAG 유사도가 이 값 미만일 때만 web_search 실행. 0.7 = 내부 규정 불충분 시에만 외부 검색",
    )

    # ==================== Trigger (Phase B) ====================
    trigger_webhook_secret: str | None = Field(
        default=None,
        description="웹훅 인증용 시크릿 (X-Trigger-Secret). 미설정 시 검증 스킵",
    )
    trigger_auto_start_severity_min: str = Field(
        default="HIGH",
        description="Auto-start 최소 severity (HIGH, CRITICAL)",
    )
    trigger_auto_start_statuses: str = Field(
        default="NEW,ACTION_REQUIRED",
        description="Auto-start status 목록 (쉼표 구분)",
    )

    # ==================== Integration Settings ====================
    github_token: str | None = Field(
        default=None,
        description="GitHub Personal Access Token"
    )
    jira_url: str | None = Field(
        default=None,
        description="Jira 서버 URL"
    )
    jira_username: str | None = Field(
        default=None,
        description="Jira 사용자명"
    )
    jira_api_token: str | None = Field(
        default=None,
        description="Jira API 토큰"
    )
    slack_bot_token: str | None = Field(
        default=None,
        description="Slack Bot Token"
    )
    slack_signing_secret: str | None = Field(
        default=None,
        description="Slack Signing Secret"
    )
    
    @field_validator("app_env")
    @classmethod
    def validate_app_env(cls, v: str) -> str:
        """애플리케이션 환경 검증"""
        allowed_envs = {"development", "staging", "production"}
        if v.lower() not in allowed_envs:
            raise ValueError(f"app_env must be one of {allowed_envs}")
        return v.lower()
    
    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """로그 레벨 검증"""
        allowed_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v_upper = v.upper()
        if v_upper not in allowed_levels:
            raise ValueError(f"log_level must be one of {allowed_levels}")
        return v_upper
    
    @property
    def is_production(self) -> bool:
        """프로덕션 환경 여부 확인"""
        return self.app_env == "production"
    
    @property
    def is_development(self) -> bool:
        """개발 환경 여부 확인"""
        return self.app_env == "development"
    
    @property
    def use_azure_openai(self) -> bool:
        """Azure OpenAI 사용 여부"""
        return bool(self.azure_openai_endpoint and self.azure_openai_api_key)

    @property
    def openai_config(self) -> dict[str, Any]:
        """OpenAI/Azure 설정을 딕셔너리로 반환"""
        effective_model = self.model_version_pin or self.azure_openai_deployment or self.openai_model
        base = {
            "model": effective_model,
            "temperature": self.openai_temperature,
            "max_tokens": self.openai_max_tokens,
        }
        if self.use_azure_openai:
            base["azure_endpoint"] = self.azure_openai_endpoint
            base["api_key"] = self.azure_openai_api_key
            base["api_version"] = self.azure_openai_api_version
        else:
            base["api_key"] = self.openai_api_key
        return base
    
    @property
    def database_config(self) -> dict[str, Any]:
        """데이터베이스 설정을 딕셔너리로 반환"""
        return {
            "url": self.database_url,
            "pool_size": self.database_pool_size,
            "max_overflow": self.database_max_overflow,
        }
    
    def get_integration_config(self, integration: str) -> dict[str, Any] | None:
        """
        특정 통합 서비스의 설정을 반환
        
        Args:
            integration: 통합 서비스 이름 (github, jira, slack)
            
        Returns:
            설정 딕셔너리 또는 None
        """
        integration = integration.lower()
        
        if integration == "github":
            if not self.github_token:
                return None
            return {"token": self.github_token}
        
        elif integration == "jira":
            if not all([self.jira_url, self.jira_username, self.jira_api_token]):
                return None
            return {
                "url": self.jira_url,
                "username": self.jira_username,
                "api_token": self.jira_api_token,
            }
        
        elif integration == "slack":
            if not all([self.slack_bot_token, self.slack_signing_secret]):
                return None
            return {
                "bot_token": self.slack_bot_token,
                "signing_secret": self.slack_signing_secret,
            }
        
        return None


@lru_cache()
def get_settings() -> Settings:
    """
    Settings 인스턴스를 반환하는 캐시된 함수
    
    이 함수는 애플리케이션 전체에서 단일 Settings 인스턴스를 공유합니다.
    FastAPI의 의존성 주입에서 사용됩니다.
    
    Returns:
        Settings 인스턴스
    """
    return Settings()


# 전역 설정 인스턴스
settings = get_settings()
