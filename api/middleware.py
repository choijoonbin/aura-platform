"""
API Middleware Module

FastAPI 미들웨어를 구현합니다.
- JWT 인증
- X-Tenant-ID 헤더 처리
- 로깅 (raw ASGI: SSE 스트림 본문을 건드리지 않음, BE 중계 0바이트 방지)
- 예외 처리
"""

import logging
import time
import uuid
from typing import Callable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

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


# 분석 스트림 경로: BaseHTTPMiddleware 미경유 시 사용 (스트림 취소 방지)
ANALYSIS_STREAM_PATH_PREFIX = "/aura/cases/"
ANALYSIS_STREAM_PATH_SUFFIX = "/analysis/stream"


class StreamBypassMiddleware:
    """
    GET /aura/cases/{id}/analysis/stream 요청을 BaseHTTPMiddleware 없이 처리하는 raw ASGI 미들웨어.
    Starlette BaseHTTPMiddleware가 스트리밍 응답 body 태스크를 취소하는 문제를 피하기 위해
    해당 경로만 별도 서브앱(stream_app)으로 넘겨 응답 본문이 그대로 전달되도록 함.
    """

    def __init__(self, app: ASGIApp, stream_app: ASGIApp) -> None:
        self.app = app
        self.stream_app = stream_app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        method = scope.get("method", "GET")
        if (
            method == "GET"
            and path.startswith(ANALYSIS_STREAM_PATH_PREFIX)
            and path.endswith(ANALYSIS_STREAM_PATH_SUFFIX)
        ):
            logger.debug("Stream bypass: delegating to stream_app path=%s", path)
            await self.stream_app(scope, receive, send)
            return
        await self.app(scope, receive, send)


class RawRequestLoggingMiddleware:
    """
    로깅만 수행하는 raw ASGI 미들웨어.
    응답 본문을 읽거나 버퍼링하지 않아 SSE 스트림이 그대로 BE/클라이언트로 전달됩니다.
    (BaseHTTPMiddleware는 StreamingResponse와 궁합 문제로 0바이트 전달될 수 있음)
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        request_id = str(uuid.uuid4())
        scope["request_id"] = request_id
        start_time = time.time()
        method = scope.get("method", "")
        path = scope.get("path", "")
        client = scope.get("client")
        client_host = client[0] if client else "unknown"
        logger.info(f"[{request_id}] {method} {path} - Client: {client_host}")
        status_code: int | None = None

        async def send_wrapper(message: dict) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 0)
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", True):
                duration = time.time() - start_time
                logger.info(
                    f"[{request_id}] {method} {path} - Status: {status_code} - Duration: {duration:.3f}s"
                )

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as e:
            duration = time.time() - start_time
            logger.error(
                f"[{request_id}] Request failed after {duration:.3f}s: {e}",
                exc_info=True,
            )
            raise


class RequestIdStateMiddleware(BaseHTTPMiddleware):
    """scope.request_id → request.state.request_id (get_request_id 등에서 사용)."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request.state.request_id = request.scope.get("request_id") or str(uuid.uuid4())
        if not isinstance(request.state.request_id, str):
            request.state.request_id = str(uuid.uuid4())
        return await call_next(request)


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


def setup_middlewares(app, stream_app: ASGIApp | None = None) -> None:
    """
    FastAPI 앱에 미들웨어 추가.
    로깅은 raw ASGI로 해서 SSE 스트림 본문이 BE까지 전달되도록 함.
    stream_app이 주어지면 GET .../analysis/stream 은 BaseHTTPMiddleware 없이 stream_app으로 처리.
    """
    app.add_middleware(ErrorHandlingMiddleware)
    app.add_middleware(RequestIdStateMiddleware)
    app.add_middleware(TenantMiddleware)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(RawRequestLoggingMiddleware)
    if stream_app is not None:
        app.add_middleware(StreamBypassMiddleware, stream_app=stream_app)
    logger.info("Middlewares configured")
