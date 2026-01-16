"""
GitHub Tool Module

GitHub API를 사용하여 PR, 이슈, 코드 등을 조회하는 도구입니다.
"""

import logging
from typing import Any, Optional

import httpx
from langchain_core.tools import tool
from pydantic import Field

from core.config import settings

logger = logging.getLogger(__name__)


class GitHubClient:
    """GitHub API 클라이언트"""
    
    def __init__(self, token: str | None = None):
        """
        GitHubClient 초기화
        
        Args:
            token: GitHub Personal Access Token
        """
        self.token = token or settings.github_token
        self.base_url = "https://api.github.com"
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
        }
        if self.token:
            self.headers["Authorization"] = f"token {self.token}"
    
    async def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs: Any,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """GitHub API 요청"""
        url = f"{self.base_url}{endpoint}"
        
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method,
                url,
                headers=self.headers,
                timeout=30.0,
                **kwargs,
            )
            response.raise_for_status()
            return response.json()
    
    async def get_pr(self, owner: str, repo: str, pr_number: int) -> dict[str, Any]:
        """PR 정보 조회"""
        return await self._request("GET", f"/repos/{owner}/{repo}/pulls/{pr_number}")
    
    async def list_prs(
        self,
        owner: str,
        repo: str,
        state: str = "open",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """PR 목록 조회"""
        data = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls",
            params={"state": state, "per_page": limit},
        )
        return data if isinstance(data, list) else []
    
    async def get_pr_files(
        self,
        owner: str,
        repo: str,
        pr_number: int,
    ) -> list[dict[str, Any]]:
        """PR의 변경된 파일 목록"""
        data = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls/{pr_number}/files",
        )
        return data if isinstance(data, list) else []
    
    async def get_file_content(
        self,
        owner: str,
        repo: str,
        path: str,
        ref: str = "main",
    ) -> dict[str, Any]:
        """파일 내용 조회"""
        return await self._request(
            "GET",
            f"/repos/{owner}/{repo}/contents/{path}",
            params={"ref": ref},
        )


# GitHub 클라이언트 싱글톤
_github_client: GitHubClient | None = None


def get_github_client() -> GitHubClient:
    """GitHub 클라이언트 반환"""
    global _github_client
    if _github_client is None:
        _github_client = GitHubClient()
    return _github_client


@tool
async def github_get_pr(
    owner: str = Field(..., description="저장소 소유자 (예: facebook)"),
    repo: str = Field(..., description="저장소 이름 (예: react)"),
    pr_number: int = Field(..., description="PR 번호"),
) -> str:
    """
    GitHub Pull Request 정보를 조회합니다.
    
    PR의 제목, 설명, 상태 등을 확인할 때 사용합니다.
    """
    try:
        client = get_github_client()
        pr = await client.get_pr(owner, repo, pr_number)
        
        result = f"""
PR #{pr['number']}: {pr['title']}
Author: {pr['user']['login']}
State: {pr['state']}
Created: {pr['created_at']}
Updated: {pr['updated_at']}

Description:
{pr['body'] or 'No description'}

Stats:
- Commits: {pr['commits']}
- Files changed: {pr['changed_files']}
- Additions: +{pr['additions']}
- Deletions: -{pr['deletions']}
"""
        return result.strip()
        
    except httpx.HTTPStatusError as e:
        logger.error(f"GitHub API error: {e}")
        return f"Error: HTTP {e.response.status_code} - {e.response.text}"
    except Exception as e:
        logger.error(f"GitHub get PR failed: {e}")
        return f"Error: {str(e)}"


@tool
async def github_list_prs(
    owner: str = Field(..., description="저장소 소유자"),
    repo: str = Field(..., description="저장소 이름"),
    state: str = Field(default="open", description="PR 상태 (open, closed, all)"),
    limit: int = Field(default=10, description="조회할 PR 개수"),
) -> str:
    """
    GitHub Pull Request 목록을 조회합니다.
    
    저장소의 PR 목록을 확인할 때 사용합니다.
    """
    try:
        client = get_github_client()
        prs = await client.list_prs(owner, repo, state, limit)
        
        if not prs:
            return f"No {state} PRs found in {owner}/{repo}"
        
        result_lines = [f"Found {len(prs)} PR(s) in {owner}/{repo}:\n"]
        for pr in prs:
            result_lines.append(
                f"#{pr['number']} - {pr['title']} "
                f"by {pr['user']['login']} ({pr['state']})"
            )
        
        return "\n".join(result_lines)
        
    except httpx.HTTPStatusError as e:
        logger.error(f"GitHub API error: {e}")
        return f"Error: HTTP {e.response.status_code}"
    except Exception as e:
        logger.error(f"GitHub list PRs failed: {e}")
        return f"Error: {str(e)}"


@tool
async def github_get_pr_diff(
    owner: str = Field(..., description="저장소 소유자"),
    repo: str = Field(..., description="저장소 이름"),
    pr_number: int = Field(..., description="PR 번호"),
) -> str:
    """
    GitHub Pull Request의 변경된 파일 목록을 조회합니다.
    
    PR에서 어떤 파일이 변경되었는지 확인할 때 사용합니다.
    """
    try:
        client = get_github_client()
        files = await client.get_pr_files(owner, repo, pr_number)
        
        if not files:
            return f"No files changed in PR #{pr_number}"
        
        result_lines = [f"PR #{pr_number} changed {len(files)} file(s):\n"]
        for file in files:
            status = file['status']
            filename = file['filename']
            additions = file['additions']
            deletions = file['deletions']
            
            result_lines.append(
                f"[{status}] {filename} (+{additions} -{deletions})"
            )
        
        return "\n".join(result_lines)
        
    except httpx.HTTPStatusError as e:
        logger.error(f"GitHub API error: {e}")
        return f"Error: HTTP {e.response.status_code}"
    except Exception as e:
        logger.error(f"GitHub get PR diff failed: {e}")
        return f"Error: {str(e)}"


@tool
async def github_get_file(
    owner: str = Field(..., description="저장소 소유자"),
    repo: str = Field(..., description="저장소 이름"),
    path: str = Field(..., description="파일 경로"),
    ref: str = Field(default="main", description="브랜치/커밋"),
) -> str:
    """
    GitHub 저장소의 파일 내용을 조회합니다.
    
    특정 파일의 코드를 확인할 때 사용합니다.
    """
    try:
        import base64
        
        client = get_github_client()
        file_data = await client.get_file_content(owner, repo, path, ref)
        
        if file_data.get('encoding') == 'base64':
            content = base64.b64decode(file_data['content']).decode('utf-8')
            return f"File: {path}\n\n{content}"
        
        return f"Error: Unsupported encoding: {file_data.get('encoding')}"
        
    except httpx.HTTPStatusError as e:
        logger.error(f"GitHub API error: {e}")
        return f"Error: HTTP {e.response.status_code}"
    except Exception as e:
        logger.error(f"GitHub get file failed: {e}")
        return f"Error: {str(e)}"


# 도구 리스트 (LangGraph에서 사용)
GITHUB_TOOLS = [
    github_get_pr,
    github_list_prs,
    github_get_pr_diff,
    github_get_file,
]
