"""
AgentConfigStore - 싱글톤 캐시 스토어 (TTL 지원)

에이전트 설정을 메모리에 캐싱합니다.
- TTL(Time-To-Live) 기반 자동 만료: 설정된 시간 후 자동으로 캐시가 무효화되어 최신 설정을 가져옵니다.
- 수동 무효화: 백엔드에서 refresh 신호를 받으면 즉시 특정 키를 무효화합니다.

환경변수:
- AGENT_CONFIG_CACHE_TTL_SECONDS: 캐시 TTL (초, 기본 300초=5분)
"""
import logging
import time
from threading import Lock
from typing import Any

from core.analysis.agent_config_schema import AgentConfig

logger = logging.getLogger(__name__)


def _get_default_ttl() -> float:
    """config에서 TTL 기본값 가져오기 (순환 import 방지)"""
    try:
        from core.config import get_settings
        return float(getattr(get_settings(), "agent_config_cache_ttl_seconds", 300))
    except Exception:
        return 300.0


class CacheEntry:
    """TTL을 포함한 캐시 엔트리"""
    
    def __init__(self, config: AgentConfig, ttl_seconds: float | None = None):
        self.config = config
        self.created_at = time.time()
        self.ttl_seconds = ttl_seconds if ttl_seconds is not None else _get_default_ttl()
    
    def is_expired(self) -> bool:
        """TTL 초과 여부 확인"""
        return (time.time() - self.created_at) > self.ttl_seconds
    
    def age_seconds(self) -> float:
        """캐시 생성 후 경과 시간 (초)"""
        return time.time() - self.created_at


class AgentConfigStore:
    """
    에이전트 설정 캐시 스토어 (싱글톤, TTL 지원)
    
    캐시 키 형식: "{tenant_id}:{agent_id}"
    멀티테넌시 환경에서 테넌트별 에이전트 설정을 격리하여 관리합니다.
    
    TTL 동작:
    - 캐시 저장 시 TTL(기본 5분) 설정
    - 조회 시 TTL 초과된 엔트리는 None 반환 (자동 만료)
    - Backend 설정 변경 시 최대 5분 내 자동 반영
    """
    _instance: "AgentConfigStore | None" = None
    _lock = Lock()
    
    def __new__(cls) -> "AgentConfigStore":
        """싱글톤 패턴 구현"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._cache: dict[str, CacheEntry] = {}
                    cls._instance._ttl_seconds = _get_default_ttl()
        return cls._instance
    
    def set_ttl(self, ttl_seconds: float) -> None:
        """TTL 설정 변경 (테스트/디버깅용)"""
        self._ttl_seconds = ttl_seconds
        logger.info(f"[AgentConfigStore] TTL changed to {ttl_seconds}s")
    
    def get(self, tenant_id: str | int, agent_id: str) -> AgentConfig | None:
        """
        캐시에서 에이전트 설정 조회 (TTL 확인)
        
        Args:
            tenant_id: 테넌트 ID
            agent_id: 에이전트 ID
            
        Returns:
            캐시된 AgentConfig 또는 None (TTL 만료 시에도 None)
        """
        key = self._make_key(tenant_id, agent_id)
        entry = self._cache.get(key)
        
        if entry is None:
            return None
        
        if entry.is_expired():
            # TTL 만료: 캐시에서 제거하고 None 반환
            del self._cache[key]
            logger.info(f"[AgentConfigStore] Cache expired for {key} (age={entry.age_seconds():.1f}s, ttl={entry.ttl_seconds}s)")
            return None
        
        logger.debug(f"[AgentConfigStore] Cache hit for {key} (age={entry.age_seconds():.1f}s)")
        return entry.config
    
    def set(self, tenant_id: str | int, agent_id: str, config: AgentConfig) -> None:
        """
        캐시에 에이전트 설정 저장 (TTL 적용)
        
        Args:
            tenant_id: 테넌트 ID
            agent_id: 에이전트 ID
            config: 저장할 AgentConfig 인스턴스
        """
        key = self._make_key(tenant_id, agent_id)
        entry = CacheEntry(config, self._ttl_seconds)
        self._cache[key] = entry
        doc_ids_info = f"docIds={len(config.doc_ids)}개" if config.doc_ids else "docIds=없음"
        logger.info(f"[AgentConfigStore] Cached config for {key} (ttl={self._ttl_seconds}s, {doc_ids_info})")
    
    def invalidate(self, tenant_id: str | int, agent_id: str) -> bool:
        """
        캐시에서 특정 에이전트 설정 무효화 (삭제)
        
        멱등성: 존재하지 않는 키를 삭제해도 에러 없이 False 반환.
        
        Args:
            tenant_id: 테넌트 ID
            agent_id: 에이전트 ID
            
        Returns:
            삭제 성공 여부 (키가 존재했으면 True, 없었으면 False)
        """
        key = self._make_key(tenant_id, agent_id)
        if key in self._cache:
            del self._cache[key]
            logger.info(f"[AgentConfigStore] Invalidated cache for {key}")
            return True
        else:
            logger.info(f"[AgentConfigStore] Cache miss for {key}, but handled (idempotent)")
            return False
    
    def clear(self) -> None:
        """전체 캐시 삭제 (테스트/디버깅용)"""
        self._cache.clear()
        logger.info("[AgentConfigStore] Cache cleared")
    
    def stats(self) -> dict[str, Any]:
        """
        캐시 상태 통계 반환 (디버깅/모니터링용)
        
        Returns:
            dict with keys:
            - total_entries: 전체 캐시 엔트리 수
            - valid_entries: 유효한 (TTL 미만료) 엔트리 수
            - expired_entries: 만료된 엔트리 수
            - ttl_seconds: 현재 TTL 설정값
            - entries: 각 엔트리의 상세 정보
        """
        now = time.time()
        entries_info = []
        valid_count = 0
        expired_count = 0
        
        for key, entry in self._cache.items():
            is_expired = entry.is_expired()
            if is_expired:
                expired_count += 1
            else:
                valid_count += 1
            entries_info.append({
                "key": key,
                "age_seconds": round(entry.age_seconds(), 1),
                "ttl_seconds": entry.ttl_seconds,
                "is_expired": is_expired,
                "doc_ids_count": len(entry.config.doc_ids) if entry.config.doc_ids else 0,
            })
        
        return {
            "total_entries": len(self._cache),
            "valid_entries": valid_count,
            "expired_entries": expired_count,
            "ttl_seconds": self._ttl_seconds,
            "entries": entries_info,
        }
    
    def _make_key(self, tenant_id: str | int, agent_id: str) -> str:
        """캐시 키 생성: {tenant_id}:{agent_id}"""
        return f"{tenant_id}:{agent_id}"


def get_config_store() -> AgentConfigStore:
    """AgentConfigStore 싱글톤 인스턴스 반환 (의존성 주입용)"""
    return AgentConfigStore()
