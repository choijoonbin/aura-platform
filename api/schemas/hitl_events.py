"""
HITL Event Schemas

백엔드 연동을 위한 HITL 이벤트 스키마를 정의합니다.
"""

from typing import Any

from pydantic import BaseModel, Field


class HITLEvent(BaseModel):
    """HITL 승인 요청 이벤트"""
    type: str = Field(default="hitl", description="이벤트 타입")
    data: dict[str, Any] = Field(..., description="HITL 데이터")
    
    class DataModel(BaseModel):
        """HITL 데이터 모델"""
        requestId: str = Field(..., description="요청 ID")
        actionType: str = Field(..., description="액션 타입")
        message: str = Field(..., description="승인 요청 메시지")
        context: dict[str, Any] = Field(..., description="액션 컨텍스트")
        requiresApproval: bool = Field(default=True, description="승인 필요 여부")
    
    @classmethod
    def create(
        cls,
        request_id: str,
        action_type: str,
        message: str,
        context: dict[str, Any],
    ) -> "HITLEvent":
        """HITL 이벤트 생성"""
        return cls(
            data={
                "requestId": request_id,
                "actionType": action_type,
                "message": message,
                "context": context,
                "requiresApproval": True,
            }
        )
