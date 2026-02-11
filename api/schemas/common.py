"""
공통 API 스키마 유틸

라우트 간 중복을 줄이기 위한 validator·헬퍼.
"""

from typing import Any


def coerce_case_run_id(v: Any) -> Any:
    """
    BE가 caseId(Long), runId(UUID) 전송 시 JSON 숫자/UUID → str 변환.
    None은 그대로 반환 (caseId optional 시 사용).
    """
    if v is None:
        return None
    return str(v)
