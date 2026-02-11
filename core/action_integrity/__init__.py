"""
Action Integrity: HITL 조치 확정 시 인사이트·알림 전용 (DB 직접 쓰기 없음).

- Aura는 case_action_history / fi_doc_header에 쓰지 않음 (백엔드 책임).
- 조치 확정 신호 수신 시: HITL 피드백 로그(가중치 업데이트용) + Redis 알림만 수행.
"""

from core.action_integrity.service import record_case_action

__all__ = ["record_case_action"]
