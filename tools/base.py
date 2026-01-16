"""
Base Tool Module

모든 통합 도구의 기본 클래스를 정의합니다.
"""

from abc import ABC, abstractmethod
from typing import Any, Optional
from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """도구 실행 결과"""
    success: bool = Field(..., description="실행 성공 여부")
    data: Any = Field(default=None, description="결과 데이터")
    error: Optional[str] = Field(default=None, description="에러 메시지")
    metadata: dict[str, Any] = Field(default_factory=dict, description="추가 메타데이터")


class BaseTool(ABC):
    """
    통합 도구 기본 클래스
    
    모든 도구는 이 클래스를 상속받아 구현합니다.
    """
    
    def __init__(self, name: str, description: str) -> None:
        """
        BaseTool 초기화
        
        Args:
            name: 도구 이름
            description: 도구 설명
        """
        self.name = name
        self.description = description
    
    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """
        도구 실행 (추상 메서드)
        
        Args:
            **kwargs: 도구별 실행 파라미터
            
        Returns:
            ToolResult 객체
        """
        pass
    
    def _success(
        self,
        data: Any,
        metadata: dict[str, Any] | None = None,
    ) -> ToolResult:
        """성공 결과 생성"""
        return ToolResult(
            success=True,
            data=data,
            metadata=metadata or {},
        )
    
    def _error(
        self,
        error: str,
        metadata: dict[str, Any] | None = None,
    ) -> ToolResult:
        """에러 결과 생성"""
        return ToolResult(
            success=False,
            error=error,
            metadata=metadata or {},
        )
