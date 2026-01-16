"""
Security Module

인증, 권한 관리 및 보안 관련 기능을 제공합니다.
JWT 기반 인증 및 RBAC 권한 시스템을 지원합니다.
"""

from core.security.auth import (
    TokenPayload,
    User,
    AuthService,
    get_auth_service,
    create_token,
    verify_token,
    get_user_from_token,
    extract_bearer_token,
)
from core.security.permissions import (
    UserRole,
    Permission,
    PermissionService,
    get_permission_service,
    has_permission,
    require_permission,
    can_execute_agent,
    is_admin,
)

__all__ = [
    # Auth
    "TokenPayload",
    "User",
    "AuthService",
    "get_auth_service",
    "create_token",
    "verify_token",
    "get_user_from_token",
    "extract_bearer_token",
    # Permissions
    "UserRole",
    "Permission",
    "PermissionService",
    "get_permission_service",
    "has_permission",
    "require_permission",
    "can_execute_agent",
    "is_admin",
]
