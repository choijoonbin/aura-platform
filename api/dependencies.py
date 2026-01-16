"""
API Dependencies Module

FastAPI 의존성 주입을 위한 함수들을 정의합니다.
"""

import logging
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from core.config import settings
from core.security.auth import User, extract_bearer_token, get_user_from_token
from core.security.permissions import Permission, has_permission
from core.memory.redis_store import RedisStore, get_redis_store
from core.memory.conversation import ConversationHistory, get_conversation_history

logger = logging.getLogger(__name__)


async def get_current_user(request: Request) -> User:
    """
    현재 인증된 사용자 반환
    
    미들웨어에서 이미 검증된 사용자 정보를 request.state에서 가져옵니다.
    미들웨어에서 설정되지 않은 경우, Authorization 헤더에서 직접 토큰을 확인합니다.
    
    Args:
        request: FastAPI Request 객체
        
    Returns:
        User 객체
        
    Raises:
        HTTPException: 인증되지 않은 경우
    """
    # 미들웨어에서 설정된 사용자 정보 확인
    if hasattr(request.state, "user") and request.state.user is not None:
        return request.state.user
    
    # 미들웨어를 통과하지 못한 경우, 직접 토큰 확인 (fallback)
    authorization = request.headers.get("Authorization")
    if authorization:
        token = extract_bearer_token(authorization)
        if token:
            user = get_user_from_token(token)
            if user:
                # request.state에 저장 (다음 요청을 위해)
                request.state.user = user
                request.state.tenant_id = user.tenant_id
                logger.debug(f"User authenticated via fallback: {user.user_id}")
                return user
    
    # 인증 실패
    logger.warning(f"Authentication failed for path: {request.url.path}")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_tenant_id(request: Request) -> str | None:
    """
    현재 테넌트 ID 반환
    
    Args:
        request: FastAPI Request 객체
        
    Returns:
        테넌트 ID 또는 None
    """
    return getattr(request.state, "tenant_id", None)


async def require_permission(
    user: Annotated[User, Depends(get_current_user)],
    permission: Permission,
) -> User:
    """
    특정 권한을 요구하는 의존성
    
    Args:
        user: 현재 사용자
        permission: 필요한 권한
        
    Returns:
        User 객체
        
    Raises:
        HTTPException: 권한이 없는 경우
    """
    if not has_permission(user, permission):
        logger.warning(
            f"User {user.user_id} lacks permission: {permission.value}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied: {permission.value}",
        )
    
    return user


async def require_agent_execute_permission(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """에이전트 실행 권한 확인"""
    return await require_permission(user, Permission.AGENT_EXECUTE)


async def require_admin_permission(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """관리자 권한 확인"""
    return await require_permission(user, Permission.SYSTEM_ADMIN)


async def get_redis_dependency() -> RedisStore:
    """
    Redis Store 의존성
    
    Returns:
        RedisStore 인스턴스
    """
    return await get_redis_store()


async def get_conversation_dependency() -> ConversationHistory:
    """
    ConversationHistory 의존성
    
    Returns:
        ConversationHistory 인스턴스
    """
    return await get_conversation_history()


def get_request_id(request: Request) -> str:
    """
    요청 ID 반환
    
    Args:
        request: FastAPI Request 객체
        
    Returns:
        요청 ID
    """
    return getattr(request.state, "request_id", "unknown")


# 타입 별칭 (편의성)
CurrentUser = Annotated[User, Depends(get_current_user)]
TenantId = Annotated[str | None, Depends(get_tenant_id)]
RedisStoreDep = Annotated[RedisStore, Depends(get_redis_dependency)]
ConversationDep = Annotated[ConversationHistory, Depends(get_conversation_dependency)]
AgentExecutor = Annotated[User, Depends(require_agent_execute_permission)]
AdminUser = Annotated[User, Depends(require_admin_permission)]


# 선택적 인증 (개발 모드용)
async def get_optional_user(request: Request) -> User | None:
    """
    선택적 사용자 인증
    
    인증이 없어도 None을 반환하고 계속 진행합니다.
    
    Args:
        request: FastAPI Request 객체
        
    Returns:
        User 객체 또는 None
    """
    if hasattr(request.state, "user"):
        return request.state.user
    
    # 헤더에서 직접 토큰 확인 시도
    authorization = request.headers.get("Authorization")
    if authorization:
        token = extract_bearer_token(authorization)
        if token:
            return get_user_from_token(token)
    
    return None


OptionalUser = Annotated[User | None, Depends(get_optional_user)]
