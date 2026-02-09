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
    
    # ==================== Logging Configuration ====================
    log_level: str = Field(
        default="INFO",
        description="로그 레벨 (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
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
        base = {
            "model": self.azure_openai_deployment or self.openai_model,
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
