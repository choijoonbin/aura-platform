"""
Authentication Module

JWT 기반 인증 시스템을 구현합니다.
dwp_backend에서 발행한 JWT를 검증하고 사용자 정보를 추출합니다.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from jose import JWTError, jwt
from pydantic import BaseModel, Field

from core.config import settings

logger = logging.getLogger(__name__)


class TokenPayload(BaseModel):
    """
    JWT 페이로드 모델
    
    JWT 표준에 따라 exp와 iat는 Unix timestamp (초 단위 정수)입니다.
    """
    sub: str = Field(..., description="사용자 ID (subject)")
    tenant_id: str | None = Field(None, description="테넌트 ID")
    email: str | None = Field(None, description="이메일")
    role: str = Field(default="user", description="사용자 역할")
    exp: int | None = Field(None, description="만료 시간 (Unix timestamp, 초 단위)")
    iat: int | None = Field(None, description="발행 시간 (Unix timestamp, 초 단위)")
    
    @property
    def user_id(self) -> str:
        """사용자 ID"""
        return self.sub


class User(BaseModel):
    """사용자 정보 모델"""
    user_id: str
    tenant_id: str | None = None
    email: str | None = None
    role: str = "user"
    is_authenticated: bool = True


class AuthService:
    """
    인증 서비스 클래스
    
    JWT 생성, 검증 및 사용자 정보 추출을 담당합니다.
    """
    
    def __init__(
        self,
        secret_key: str | None = None,
        algorithm: str | None = None,
    ) -> None:
        """
        AuthService 초기화
        
        Args:
            secret_key: JWT 서명 키 (None이면 설정에서 로드, dwp_backend와 동일해야 함)
            algorithm: JWT 알고리즘
        """
        self.secret_key = secret_key or settings.secret_key
        self.algorithm = algorithm or settings.algorithm
    
    def create_access_token(
        self,
        data: dict[str, Any],
        expires_delta: timedelta | None = None,
    ) -> str:
        """
        JWT Access Token 생성
        
        JWT 표준에 따라 exp와 iat는 Unix timestamp (초 단위 정수)로 저장됩니다.
        이는 Python-Java 호환성을 위해 필수입니다.
        
        Args:
            data: 토큰에 포함할 데이터
            expires_delta: 만료 시간 (None이면 기본값 사용)
            
        Returns:
            JWT 토큰 문자열
        """
        to_encode = data.copy()
        
        # 현재 시간 (UTC)
        now = datetime.now(timezone.utc)
        
        # 만료 시간 계산
        if expires_delta:
            expire = now + expires_delta
        else:
            expire = now + timedelta(
                minutes=settings.access_token_expire_minutes
            )
        
        # JWT 표준: exp와 iat는 Unix timestamp (초 단위 정수)
        to_encode.update({
            "exp": int(expire.timestamp()),  # ✅ Unix timestamp로 변환
            "iat": int(now.timestamp()),     # ✅ Unix timestamp로 변환
        })
        
        encoded_jwt = jwt.encode(
            to_encode,
            self.secret_key,
            algorithm=self.algorithm,
        )
        
        return encoded_jwt
    
    def verify_token(self, token: str) -> TokenPayload | None:
        """
        JWT 토큰 검증 및 페이로드 추출
        
        jwt.decode()가 자동으로 exp 클레임을 검증하므로,
        추가적인 만료 확인 로직은 필요하지 않습니다.
        
        Args:
            token: JWT 토큰 문자열
            
        Returns:
            TokenPayload 또는 None (검증 실패 시)
        """
        try:
            # jwt.decode()는 자동으로 exp, nbf, iat를 검증합니다
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm],
            )
            
            token_data = TokenPayload(**payload)
            return token_data
            
        except JWTError as e:
            logger.error(f"JWT verification failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during token verification: {e}")
            return None
    
    def extract_user_from_token(self, token: str) -> User | None:
        """
        JWT 토큰에서 사용자 정보 추출
        
        Args:
            token: JWT 토큰 문자열
            
        Returns:
            User 객체 또는 None
        """
        token_payload = self.verify_token(token)
        
        if token_payload is None:
            return None
        
        return User(
            user_id=token_payload.user_id,
            tenant_id=token_payload.tenant_id,
            email=token_payload.email,
            role=token_payload.role,
        )
    
    def extract_bearer_token(self, authorization: str) -> str | None:
        """
        Authorization 헤더에서 Bearer 토큰 추출
        
        Args:
            authorization: Authorization 헤더 값 (예: "Bearer eyJ...")
            
        Returns:
            토큰 문자열 또는 None
        """
        if not authorization:
            return None
        
        parts = authorization.split()
        
        if len(parts) != 2:
            logger.warning("Invalid authorization header format")
            return None
        
        scheme, token = parts
        
        if scheme.lower() != "bearer":
            logger.warning(f"Unsupported authorization scheme: {scheme}")
            return None
        
        return token


# 전역 AuthService 인스턴스
_auth_service: AuthService | None = None


def get_auth_service() -> AuthService:
    """
    전역 AuthService 인스턴스 반환
    
    Returns:
        AuthService 인스턴스
    """
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service


# 편의 함수들
def create_token(user_id: str, tenant_id: str | None = None, **extra: Any) -> str:
    """
    사용자 토큰 생성
    
    Args:
        user_id: 사용자 ID
        tenant_id: 테넌트 ID
        **extra: 추가 데이터
        
    Returns:
        JWT 토큰
    """
    auth = get_auth_service()
    data = {"sub": user_id, "tenant_id": tenant_id, **extra}
    return auth.create_access_token(data)


def verify_token(token: str) -> TokenPayload | None:
    """토큰 검증"""
    auth = get_auth_service()
    return auth.verify_token(token)


def get_user_from_token(token: str) -> User | None:
    """토큰에서 사용자 정보 추출"""
    auth = get_auth_service()
    return auth.extract_user_from_token(token)


def extract_bearer_token(authorization: str) -> str | None:
    """Authorization 헤더에서 토큰 추출"""
    auth = get_auth_service()
    return auth.extract_bearer_token(authorization)
