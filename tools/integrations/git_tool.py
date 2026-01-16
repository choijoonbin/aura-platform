"""
Git Tool Module

로컬 Git 작업을 수행하는 도구입니다.
"""

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Any

from langchain_core.tools import tool
from pydantic import Field

logger = logging.getLogger(__name__)


@tool
async def git_diff(
    repo_path: str = Field(..., description="Git 저장소 경로"),
    branch: str = Field(default="HEAD", description="비교할 브랜치/커밋"),
    file_path: str = Field(default=None, description="특정 파일만 diff (선택)"),
) -> str:
    """
    Git diff를 조회합니다.
    
    로컬 Git 저장소의 변경사항을 확인할 때 사용합니다.
    """
    try:
        cmd = ["git", "-C", repo_path, "diff", branch]
        if file_path:
            cmd.append(file_path)
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        if result.returncode != 0:
            return f"Error: {result.stderr}"
        
        diff_output = result.stdout
        if not diff_output:
            return "No changes detected."
        
        return diff_output
        
    except subprocess.TimeoutExpired:
        return "Error: Git command timed out"
    except Exception as e:
        logger.error(f"Git diff failed: {e}")
        return f"Error: {str(e)}"


@tool
async def git_log(
    repo_path: str = Field(..., description="Git 저장소 경로"),
    limit: int = Field(default=10, description="조회할 커밋 개수"),
    branch: str = Field(default="HEAD", description="브랜치 이름"),
) -> str:
    """
    Git 커밋 로그를 조회합니다.
    
    최근 커밋 히스토리를 확인할 때 사용합니다.
    """
    try:
        cmd = [
            "git", "-C", repo_path, "log",
            f"-{limit}",
            "--pretty=format:%h - %an, %ar : %s",
            branch,
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        if result.returncode != 0:
            return f"Error: {result.stderr}"
        
        return result.stdout
        
    except subprocess.TimeoutExpired:
        return "Error: Git command timed out"
    except Exception as e:
        logger.error(f"Git log failed: {e}")
        return f"Error: {str(e)}"


@tool
async def git_status(
    repo_path: str = Field(..., description="Git 저장소 경로"),
) -> str:
    """
    Git 상태를 조회합니다.
    
    현재 작업 디렉토리의 변경사항을 확인할 때 사용합니다.
    """
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "status", "--short"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        if result.returncode != 0:
            return f"Error: {result.stderr}"
        
        status_output = result.stdout
        if not status_output:
            return "Working directory clean."
        
        return status_output
        
    except subprocess.TimeoutExpired:
        return "Error: Git command timed out"
    except Exception as e:
        logger.error(f"Git status failed: {e}")
        return f"Error: {str(e)}"


@tool
async def git_show_file(
    repo_path: str = Field(..., description="Git 저장소 경로"),
    file_path: str = Field(..., description="파일 경로"),
    commit: str = Field(default="HEAD", description="커밋 해시/브랜치"),
) -> str:
    """
    특정 커밋의 파일 내용을 조회합니다.
    
    과거 버전의 파일을 확인할 때 사용합니다.
    """
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, "show", f"{commit}:{file_path}"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        if result.returncode != 0:
            return f"Error: {result.stderr}"
        
        return result.stdout
        
    except subprocess.TimeoutExpired:
        return "Error: Git command timed out"
    except Exception as e:
        logger.error(f"Git show file failed: {e}")
        return f"Error: {str(e)}"


@tool
async def git_branch_list(
    repo_path: str = Field(..., description="Git 저장소 경로"),
    remote: bool = Field(default=False, description="리모트 브랜치 포함 여부"),
) -> str:
    """
    Git 브랜치 목록을 조회합니다.
    
    저장소의 모든 브랜치를 확인할 때 사용합니다.
    """
    try:
        cmd = ["git", "-C", repo_path, "branch"]
        if remote:
            cmd.append("-a")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        if result.returncode != 0:
            return f"Error: {result.stderr}"
        
        return result.stdout
        
    except subprocess.TimeoutExpired:
        return "Error: Git command timed out"
    except Exception as e:
        logger.error(f"Git branch list failed: {e}")
        return f"Error: {str(e)}"


# 도구 리스트 (LangGraph에서 사용)
GIT_TOOLS = [
    git_diff,
    git_log,
    git_status,
    git_show_file,
    git_branch_list,
]
