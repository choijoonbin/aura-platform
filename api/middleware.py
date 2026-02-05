"""
API Middleware Module

FastAPI 미들웨어를 구현합니다.
- JWT 인증
- X-Tenant-ID 헤더 처리
- 로깅
- 예외 처리
"""

import logging
import time
import uuid
from typing import Callable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from core.config import settings
from core.security.auth import extract_bearer_token, get_user_from_token

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseHTTPMiddleware):
    """
    JWT 인증 미들웨어
    
    Authorization 헤더에서 JWT를 추출하고 검증합니다.
    검증된 사용자 정보를 request.state에 저장합니다.
    """
    
    # 인증이 필요 없는 경로
    EXEMPT_PATHS = [
        "/",
        "/health",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/agents/health",  # 에이전트 헬스체크는 공개
        "/aura/triggers/case-updated",  # Phase B: 배치 웹훅 (X-Trigger-Secret으로 검증)
    ]
    
    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """미들웨어 처리"""
        
        # 인증 제외 경로 확인 (정확한 경로 매칭 또는 시작 경로 확인)
        path = request.url.path
        is_exempt = (
            path in self.EXEMPT_PATHS or
            any(path.startswith(exempt) for exempt in self.EXEMPT_PATHS if exempt.endswith("*"))
        )
        
        if is_exempt:
            logger.debug(f"Path {path} is exempt from authentication")
            return await call_next(request)
        
        # 개발 모드에서 인증 비활성화 옵션
        if not settings.require_auth:
            logger.debug("Authentication disabled in development mode")
            request.state.user = None
            request.state.tenant_id = None
            return await call_next(request)
        
        # Authorization 헤더 확인
        authorization = request.headers.get("Authorization")
        
        if not authorization:
            logger.warning(f"Missing Authorization header: {request.url.path}")
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Missing authorization header"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Bearer 토큰 추출
        token = extract_bearer_token(authorization)
        
        if not token:
            logger.warning("Invalid authorization header format")
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Invalid authorization header format"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # 토큰 검증 및 사용자 정보 추출
        user = get_user_from_token(token)
        
        if user is None:
            logger.warning("Invalid or expired token")
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Invalid or expired token"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # 사용자 정보를 request.state에 저장
        request.state.user = user
        request.state.tenant_id = user.tenant_id
        
        logger.debug(
            f"Authenticated user: {user.user_id} (tenant: {user.tenant_id})"
        )
        
        return await call_next(request)


class TenantMiddleware(BaseHTTPMiddleware):
    """
    X-Tenant-ID 헤더 처리 미들웨어
    
    멀티테넌시를 위한 테넌트 ID를 헤더에서 추출합니다.
    """
    
    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """미들웨어 처리"""
        
        # X-Tenant-ID 헤더 확인
        tenant_id = request.headers.get("X-Tenant-ID")
        
        if tenant_id:
            # request.state에 이미 tenant_id가 있으면 (JWT에서 추출)
            # 헤더 값과 비교하여 일치 여부 확인
            if hasattr(request.state, "tenant_id") and request.state.tenant_id:
                if request.state.tenant_id != tenant_id:
                    logger.warning(
                        f"Tenant ID mismatch: JWT={request.state.tenant_id}, "
                        f"Header={tenant_id}"
                    )
                    return JSONResponse(
                        status_code=status.HTTP_403_FORBIDDEN,
                        content={"detail": "Tenant ID mismatch"},
                    )
            else:
                request.state.tenant_id = tenant_id
            
            logger.debug(f"Tenant ID: {tenant_id}")
        
        return await call_next(request)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    요청 로깅 미들웨어
    
    모든 API 요청을 로깅합니다.
    """
    
    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """미들웨어 처리"""
        
        # 요청 ID 생성
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        
        # 시작 시간
        start_time = time.time()
        
        # 요청 정보 로깅
        logger.info(
            f"[{request_id}] {request.method} {request.url.path} "
            f"- Client: {request.client.host if request.client else 'unknown'}"
        )
        
        # 요청 처리
        try:
            response = await call_next(request)
        except Exception as e:
            # 예외 발생 시 로깅
            duration = time.time() - start_time
            logger.error(
                f"[{request_id}] Request failed after {duration:.3f}s: {e}",
                exc_info=True,
            )
            raise
        
        # 처리 시간 계산
        duration = time.time() - start_time
        
        # 응답 정보 로깅
        logger.info(
            f"[{request_id}] {request.method} {request.url.path} "
            f"- Status: {response.status_code} - Duration: {duration:.3f}s"
        )
        
        # 응답 헤더에 request_id 추가
        response.headers["X-Request-ID"] = request_id
        
        return response


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """
    에러 처리 미들웨어
    
    예외를 캐치하고 일관된 형식의 에러 응답을 반환합니다.
    """
    
    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """미들웨어 처리"""
        
        try:
            response = await call_next(request)
            return response
            
        except PermissionError as e:
            logger.warning(f"Permission denied: {e}")
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "detail": str(e),
                    "error_type": "permission_error",
                },
            )
        
        except ValueError as e:
            logger.warning(f"Validation error: {e}")
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "detail": str(e),
                    "error_type": "validation_error",
                },
            )
        
        except Exception as e:
            logger.error(f"Unhandled exception: {e}", exc_info=True)
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "detail": "Internal server error",
                    "error_type": "server_error",
                },
            )


def setup_middlewares(app) -> None:
    """
    FastAPI 앱에 미들웨어 추가
    
    Args:
        app: FastAPI 애플리케이션 인스턴스
    """
    # 순서가 중요합니다 (역순으로 적용됨)
    # 1. 에러 처리 (가장 바깥)
    app.add_middleware(ErrorHandlingMiddleware)
    
    # 2. 요청 로깅
    app.add_middleware(RequestLoggingMiddleware)
    
    # 3. 테넌트 처리
    app.add_middleware(TenantMiddleware)
    
    # 4. 인증 (가장 안쪽)
    app.add_middleware(AuthMiddleware)
    
    logger.info("Middlewares configured")
