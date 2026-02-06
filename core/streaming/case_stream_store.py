"""
Case Stream Store (Prompt C P0)

케이스별 Agent Stream 이벤트를 in-memory ring buffer로 저장.
Last-Event-ID 기반 replay 지원.
"""

import logging
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# 케이스별 최대 이벤트 수 (ring buffer)
DEFAULT_RING_BUFFER_SIZE = 100


@dataclass
class CaseStreamEvent:
    """
    Case Agent Stream 이벤트 (고정 스키마)
    
    event: agent.step | agent.note | agent.error
    """
    id: str
    event: str  # agent.step | agent.note | agent.error
    tenant_id: str
    case_id: str
    trace_id: str
    ts: str  # ISO 8601
    level: str  # INFO, WARN, ERROR
    step_id: str
    message: str
    payload: dict[str, Any]
    user_id: str | None = None

    def to_sse_data(self) -> dict[str, Any]:
        """SSE data payload"""
        return {
            "tenantId": self.tenant_id,
            "caseId": self.case_id,
            "traceId": self.trace_id,
            "ts": self.ts,
            "level": self.level,
            "stepId": self.step_id,
            "message": self.message,
            "payload": self.payload,
            **({"userId": self.user_id} if self.user_id else {}),
        }


class CaseStreamStore:
    """
    케이스별 Agent Stream in-memory ring buffer.
    
    - caseId별 최근 N개 이벤트 저장
    - Last-Event-ID로 replay (해당 id 이후 이벤트만 반환)
    """

    def __init__(self, ring_buffer_size: int = DEFAULT_RING_BUFFER_SIZE):
        self._ring_buffer_size = ring_buffer_size
        # case_id -> deque of (event_id, CaseStreamEvent)
        self._buffers: dict[str, deque[tuple[str, CaseStreamEvent]]] = {}
        # event_id -> (case_id, index) for replay lookup
        self._id_to_case: dict[str, tuple[str, int]] = {}

    def append(
        self,
        case_id: str,
        event_type: str,
        step_id: str,
        message: str,
        *,
        tenant_id: str = "1",
        trace_id: str | None = None,
        level: str = "INFO",
        payload: dict[str, Any] | None = None,
        user_id: str | None = None,
    ) -> CaseStreamEvent:
        """
        이벤트 추가
        
        Returns:
            생성된 CaseStreamEvent (id 포함)
        """
        event_id = str(uuid.uuid4())
        ts = datetime.now(timezone.utc).isoformat()
        ev = CaseStreamEvent(
            id=event_id,
            event=event_type,
            tenant_id=tenant_id,
            case_id=case_id,
            trace_id=trace_id or f"trace-{case_id}-{event_id[:8]}",
            ts=ts,
            level=level,
            step_id=step_id,
            message=message,
            payload=payload or {},
            user_id=user_id,
        )

        if case_id not in self._buffers:
            self._buffers[case_id] = deque(maxlen=self._ring_buffer_size)

        buf = self._buffers[case_id]
        idx = len(buf)
        buf.append((event_id, ev))
        self._id_to_case[event_id] = (case_id, idx)

        return ev

    def get_events_after(
        self,
        case_id: str,
        last_event_id: str | None = None,
    ) -> list[CaseStreamEvent]:
        """
        Last-Event-ID 이후 이벤트 반환 (replay)
        
        last_event_id가 없으면 전체 반환.
        """
        if case_id not in self._buffers:
            return []

        buf = list(self._buffers[case_id])
        if not last_event_id:
            return [ev for _, ev in buf]

        # last_event_id 이후 인덱스 찾기
        start_idx = 0
        for i, (eid, _) in enumerate(buf):
            if eid == last_event_id:
                start_idx = i + 1
                break

        return [ev for _, ev in buf[start_idx:]]

    def get_all_events(self, case_id: str) -> list[CaseStreamEvent]:
        """케이스의 전체 이벤트 반환"""
        return self.get_events_after(case_id, last_event_id=None)

    def generate_sample_events(
        self,
        case_id: str,
        tenant_id: str = "1",
        trace_id: str | None = None,
        user_id: str | None = None,
        count: int = 5,
    ) -> list[CaseStreamEvent]:
        """
        재현 가능한 샘플 스트림 생성 (P0)
        
        케이스 상세 탭에서 3~5개 이벤트가 표시되도록.
        """
        trace = trace_id or f"trace-{case_id}-sample"
        samples = [
            ("extract-evidence", "agent.step", "Extracted 3 evidence items", {"evidenceIds": ["EV-1", "EV-2", "EV-3"], "keys": {"bukrs": "1000", "belnr": "1900000001", "gjahr": "2024"}}),
            ("analyze-risk", "agent.step", "Risk analysis completed: DUPLICATE_INVOICE (0.85)", {"riskType": "DUPLICATE_INVOICE", "score": 0.85}),
            ("rag-query", "agent.step", "RAG queried: 5 docs, topK=10, 120ms", {"docCount": 5, "topK": 10, "latencyMs": 120}),
            ("reasoning", "agent.note", "Reasoning composed for case", {"caseId": case_id}),
            ("plan-ready", "agent.step", "Plan ready: 2 action steps proposed", {"stepCount": 2}),
        ]
        events = []
        for i, (step_id, ev_type, msg, payload) in enumerate(samples[:count]):
            ev = self.append(
                case_id=case_id,
                event_type=ev_type,
                step_id=step_id,
                message=msg,
                tenant_id=tenant_id,
                trace_id=trace,
                level="INFO",
                payload=payload,
                user_id=user_id,
            )
            events.append(ev)
        return events


_case_stream_store: CaseStreamStore | None = None


def get_case_stream_store() -> CaseStreamStore:
    """CaseStreamStore 싱글톤"""
    global _case_stream_store
    if _case_stream_store is None:
        _case_stream_store = CaseStreamStore()
    return _case_stream_store
