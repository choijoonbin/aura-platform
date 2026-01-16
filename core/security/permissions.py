"""
Permissions Module

RBAC (Role-Based Access Control) 권한 관리를 구현합니다.
"""

import logging
from enum import Enum
from typing import Any

from core.security.auth import User

logger = logging.getLogger(__name__)


class UserRole(str, Enum):
    """사용자 역할"""
    ADMIN = "admin"
    MANAGER = "manager"
    USER = "user"
    GUEST = "guest"


class Permission(str, Enum):
    """권한 목록"""
    # 에이전트 관련
    AGENT_READ = "agent:read"
    AGENT_EXECUTE = "agent:execute"
    AGENT_MANAGE = "agent:manage"
    
    # 도메인 관련
    DOMAIN_READ = "domain:read"
    DOMAIN_WRITE = "domain:write"
    DOMAIN_DELETE = "domain:delete"
    
    # 시스템 관리
    SYSTEM_ADMIN = "system:admin"
    SYSTEM_CONFIG = "system:config"
    
    # 데이터 접근
    DATA_READ = "data:read"
    DATA_WRITE = "data:write"
    DATA_DELETE = "data:delete"


# 역할별 권한 매핑
ROLE_PERMISSIONS: dict[UserRole, list[Permission]] = {
    UserRole.ADMIN: [
        # 관리자는 모든 권한
        Permission.AGENT_READ,
        Permission.AGENT_EXECUTE,
        Permission.AGENT_MANAGE,
        Permission.DOMAIN_READ,
        Permission.DOMAIN_WRITE,
        Permission.DOMAIN_DELETE,
        Permission.SYSTEM_ADMIN,
        Permission.SYSTEM_CONFIG,
        Permission.DATA_READ,
        Permission.DATA_WRITE,
        Permission.DATA_DELETE,
    ],
    UserRole.MANAGER: [
        # 매니저는 실행 및 관리
        Permission.AGENT_READ,
        Permission.AGENT_EXECUTE,
        Permission.AGENT_MANAGE,
        Permission.DOMAIN_READ,
        Permission.DOMAIN_WRITE,
        Permission.DATA_READ,
        Permission.DATA_WRITE,
    ],
    UserRole.USER: [
        # 일반 사용자는 읽기 및 실행
        Permission.AGENT_READ,
        Permission.AGENT_EXECUTE,
        Permission.DOMAIN_READ,
        Permission.DATA_READ,
    ],
    UserRole.GUEST: [
        # 게스트는 읽기만
        Permission.AGENT_READ,
        Permission.DOMAIN_READ,
        Permission.DATA_READ,
    ],
}


class PermissionService:
    """
    권한 관리 서비스 클래스
    
    사용자의 역할에 따라 권한을 확인합니다.
    """
    
    def __init__(self) -> None:
        """PermissionService 초기화"""
        self.role_permissions = ROLE_PERMISSIONS
    
    def get_user_role(self, user: User) -> UserRole:
        """
        사용자의 역할 반환
        
        Args:
            user: User 객체
            
        Returns:
            UserRole
        """
        try:
            return UserRole(user.role)
        except ValueError:
            logger.warning(f"Unknown role: {user.role}, defaulting to USER")
            return UserRole.USER
    
    def get_role_permissions(self, role: UserRole) -> list[Permission]:
        """
        역할의 권한 목록 반환
        
        Args:
            role: UserRole
            
        Returns:
            Permission 리스트
        """
        return self.role_permissions.get(role, [])
    
    def has_permission(self, user: User, permission: Permission) -> bool:
        """
        사용자가 특정 권한을 가지고 있는지 확인
        
        Args:
            user: User 객체
            permission: 확인할 Permission
            
        Returns:
            권한 보유 여부
        """
        if not user.is_authenticated:
            return False
        
        role = self.get_user_role(user)
        permissions = self.get_role_permissions(role)
        
        return permission in permissions
    
    def has_any_permission(
        self,
        user: User,
        permissions: list[Permission],
    ) -> bool:
        """
        사용자가 주어진 권한 중 하나라도 가지고 있는지 확인
        
        Args:
            user: User 객체
            permissions: Permission 리스트
            
        Returns:
            권한 보유 여부
        """
        return any(self.has_permission(user, perm) for perm in permissions)
    
    def has_all_permissions(
        self,
        user: User,
        permissions: list[Permission],
    ) -> bool:
        """
        사용자가 주어진 모든 권한을 가지고 있는지 확인
        
        Args:
            user: User 객체
            permissions: Permission 리스트
            
        Returns:
            권한 보유 여부
        """
        return all(self.has_permission(user, perm) for perm in permissions)
    
    def require_permission(self, user: User, permission: Permission) -> None:
        """
        권한 확인 (없으면 예외 발생)
        
        Args:
            user: User 객체
            permission: 필요한 Permission
            
        Raises:
            PermissionError: 권한이 없는 경우
        """
        if not self.has_permission(user, permission):
            role = self.get_user_role(user)
            raise PermissionError(
                f"User with role '{role.value}' does not have permission '{permission.value}'"
            )
    
    def can_execute_agent(self, user: User) -> bool:
        """에이전트 실행 권한 확인"""
        return self.has_permission(user, Permission.AGENT_EXECUTE)
    
    def can_manage_agent(self, user: User) -> bool:
        """에이전트 관리 권한 확인"""
        return self.has_permission(user, Permission.AGENT_MANAGE)
    
    def is_admin(self, user: User) -> bool:
        """관리자 여부 확인"""
        role = self.get_user_role(user)
        return role == UserRole.ADMIN


# 전역 PermissionService 인스턴스
_permission_service: PermissionService | None = None


def get_permission_service() -> PermissionService:
    """
    전역 PermissionService 인스턴스 반환
    
    Returns:
        PermissionService 인스턴스
    """
    global _permission_service
    if _permission_service is None:
        _permission_service = PermissionService()
    return _permission_service


# 편의 함수들
def has_permission(user: User, permission: Permission) -> bool:
    """사용자 권한 확인"""
    service = get_permission_service()
    return service.has_permission(user, permission)


def require_permission(user: User, permission: Permission) -> None:
    """권한 확인 (없으면 예외)"""
    service = get_permission_service()
    service.require_permission(user, permission)


def can_execute_agent(user: User) -> bool:
    """에이전트 실행 권한 확인"""
    service = get_permission_service()
    return service.can_execute_agent(user)


def is_admin(user: User) -> bool:
    """관리자 여부 확인"""
    service = get_permission_service()
    return service.is_admin(user)
