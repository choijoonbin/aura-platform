"""
LLM Client Module

OpenAI 클라이언트를 관리하고 LangChain과의 통합을 제공합니다.
Streaming 지원을 포함하여 React 프론트엔드로 실시간 응답을 전송할 수 있습니다.
"""

from functools import lru_cache
from typing import Any, AsyncGenerator

from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage

from core.config import settings


class LLMClient:
    """
    LLM 클라이언트 래퍼 클래스
    
    OpenAI 및 기타 LLM 프로바이더와의 통합을 단순화합니다.
    """
    
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> None:
        """
        LLMClient 초기화
        
        Args:
            api_key: OpenAI API 키 (None이면 설정에서 로드)
            model: 모델 이름 (None이면 설정에서 로드)
            temperature: 온도 파라미터 (None이면 설정에서 로드)
            max_tokens: 최대 토큰 수 (None이면 설정에서 로드)
            **kwargs: ChatOpenAI에 전달할 추가 파라미터
        """
        self.api_key = api_key or settings.openai_api_key
        self.model = model or settings.openai_model
        self.temperature = temperature if temperature is not None else settings.openai_temperature
        self.max_tokens = max_tokens or settings.openai_max_tokens
        self.extra_kwargs = kwargs
        
        self._client: BaseChatModel | None = None
    
    @property
    def client(self) -> BaseChatModel:
        """
        LangChain ChatOpenAI 클라이언트 반환
        
        클라이언트는 lazy하게 초기화됩니다.
        
        Returns:
            ChatOpenAI 인스턴스
        """
        if self._client is None:
            self._client = ChatOpenAI(
                api_key=self.api_key,
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                **self.extra_kwargs,
            )
        return self._client
    
    async def ainvoke(
        self,
        messages: list[dict[str, str]] | str,
        **kwargs: Any,
    ) -> str:
        """
        비동기로 LLM을 호출합니다.
        
        Args:
            messages: 메시지 리스트 또는 단일 프롬프트 문자열
            **kwargs: invoke에 전달할 추가 파라미터
            
        Returns:
            LLM 응답 텍스트
        """
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]
        
        response = await self.client.ainvoke(messages, **kwargs)
        return response.content
    
    def invoke(
        self,
        messages: list[dict[str, str]] | str,
        **kwargs: Any,
    ) -> str:
        """
        동기적으로 LLM을 호출합니다.
        
        Args:
            messages: 메시지 리스트 또는 단일 프롬프트 문자열
            **kwargs: invoke에 전달할 추가 파라미터
            
        Returns:
            LLM 응답 텍스트
        """
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]
        
        response = self.client.invoke(messages, **kwargs)
        return response.content
    
    async def astream(
        self,
        messages: list[dict[str, str]] | str,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """
        비동기 스트리밍으로 LLM을 호출합니다.
        
        React 프론트엔드로 실시간 응답을 전송할 때 사용합니다.
        
        Args:
            messages: 메시지 리스트 또는 단일 프롬프트 문자열
            **kwargs: stream에 전달할 추가 파라미터
            
        Yields:
            LLM 응답 텍스트 청크
            
        Example:
            ```python
            async for chunk in client.astream("Hello!"):
                print(chunk, end="", flush=True)
            ```
        """
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]
        
        async for chunk in self.client.astream(messages, **kwargs):
            if hasattr(chunk, "content") and chunk.content:
                yield chunk.content
    
    def _convert_messages(
        self,
        messages: list[dict[str, str]],
    ) -> list[BaseMessage]:
        """
        딕셔너리 메시지를 LangChain 메시지 객체로 변환
        
        Args:
            messages: 메시지 딕셔너리 리스트
            
        Returns:
            LangChain 메시지 객체 리스트
        """
        converted = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            if role == "system":
                converted.append(SystemMessage(content=content))
            elif role == "assistant":
                converted.append(AIMessage(content=content))
            else:  # user or default
                converted.append(HumanMessage(content=content))
        
        return converted
    
    def with_config(
        self,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> "LLMClient":
        """
        새로운 설정으로 LLMClient 인스턴스를 생성합니다.
        
        Args:
            temperature: 온도 파라미터
            max_tokens: 최대 토큰 수
            **kwargs: 추가 파라미터
            
        Returns:
            새로운 LLMClient 인스턴스
        """
        return LLMClient(
            api_key=self.api_key,
            model=self.model,
            temperature=temperature or self.temperature,
            max_tokens=max_tokens or self.max_tokens,
            **{**self.extra_kwargs, **kwargs},
        )


@lru_cache()
def get_llm_client() -> LLMClient:
    """
    전역 LLMClient 인스턴스를 반환합니다.
    
    이 함수는 캐시되어 애플리케이션 전체에서 단일 인스턴스를 공유합니다.
    
    Returns:
        LLMClient 인스턴스
    """
    return LLMClient()
