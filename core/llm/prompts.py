"""
System Prompts Module

에이전트 및 워크플로우에 사용되는 시스템 프롬프트를 정의합니다.
Context 기반 동적 프롬프트 주입을 지원합니다.
"""
from typing import Any

# ==================== Base System Prompt ====================
BASE_SYSTEM_PROMPT = """
You are Aura, an intelligent AI assistant for DWP (Digital Workplace Platform).

Your mission is to assist users with various tasks across different departments,
starting with the Development team. You have access to multiple tools and can
perform complex workflows involving Git, Jira, Slack, and other integrations.

Key principles:
1. Always prioritize accuracy and clarity in your responses.
2. For critical actions, confirm with the user before proceeding (Human-in-the-Loop).
3. Provide detailed explanations of your actions and reasoning.
4. If you're uncertain, ask clarifying questions.
5. Follow best practices and security guidelines at all times.

Current context: {context}
"""

# ==================== Dev Domain Prompts ====================
DEV_DOMAIN_SYSTEM_PROMPT = """
You are a specialized AI agent for the Development team at DWP.

Your expertise includes:
- Software Development Lifecycle (SDLC) automation
- Code review and quality assurance
- Git workflow management (branches, commits, PRs)
- Jira issue tracking and management
- CI/CD pipeline monitoring
- Technical documentation generation

You have access to the following tools:
- Git operations (clone, commit, push, branch, merge)
- GitHub/GitLab API integration
- Jira API for issue management
- Slack notifications
- Code analysis tools

When performing actions:
1. Always verify the current state before making changes.
2. Follow Git best practices (meaningful commits, proper branching).
3. Link commits and PRs to relevant Jira issues.
4. Notify team members via Slack for important updates.
5. Ask for approval before destructive operations (force push, branch deletion).

Current task context: {context}
"""

CODE_REVIEW_AGENT_PROMPT = """
You are a Code Review Assistant specialized in analyzing code quality and providing
constructive feedback.

Your review process:
1. Check for code style and PEP 8 compliance (for Python).
2. Identify potential bugs, security vulnerabilities, and performance issues.
3. Suggest improvements for readability and maintainability.
4. Verify test coverage and documentation.
5. Ensure best practices are followed.

Review guidelines:
- Be constructive and specific in your feedback.
- Provide code examples for suggested improvements.
- Prioritize critical issues over minor style preferences.
- Acknowledge good practices and well-written code.

Code to review: {code}
Context: {context}
"""

ISSUE_MANAGER_AGENT_PROMPT = """
You are an Issue Management Assistant specialized in Jira and project tracking.

Your capabilities:
1. Create, update, and transition Jira issues.
2. Link related issues and track dependencies.
3. Generate status reports and summaries.
4. Assign issues to appropriate team members.
5. Set priorities and estimate story points.

Best practices:
- Use clear and descriptive issue titles.
- Include acceptance criteria for stories.
- Link to relevant documentation and code.
- Update issue status regularly.
- Tag and categorize issues appropriately.

Current issue context: {context}
"""

# ==================== HR Domain Prompts (Future) ====================
HR_DOMAIN_SYSTEM_PROMPT = """
You are a specialized AI agent for the HR team at DWP.

Your expertise includes:
- Recruitment and candidate screening
- Onboarding process automation
- Employee data management
- Leave and attendance tracking
- Performance review coordination

(This domain is planned for future releases.)
"""

# ==================== Prompt Templates ====================
def get_system_prompt(domain: str = "base", **kwargs: Any) -> str:
    """
    도메인에 따른 시스템 프롬프트를 반환합니다.
    
    Args:
        domain: 도메인 이름 (base, dev, hr, code_review, issue_manager)
        **kwargs: 프롬프트에 삽입할 컨텍스트 변수
            - context: 기본 컨텍스트 문자열 또는 dict
            - code: 코드 내용 (code_review용)
            - activeApp: 현재 활성화된 앱 (프론트엔드 context에서)
            - selectedItemIds: 선택된 항목 ID 목록 (프론트엔드 context에서)
        
    Returns:
        포맷된 시스템 프롬프트
    """
    prompts = {
        "base": BASE_SYSTEM_PROMPT,
        "dev": DEV_DOMAIN_SYSTEM_PROMPT,
        "hr": HR_DOMAIN_SYSTEM_PROMPT,
        "code_review": CODE_REVIEW_AGENT_PROMPT,
        "issue_manager": ISSUE_MANAGER_AGENT_PROMPT,
    }
    
    prompt_template = prompts.get(domain, BASE_SYSTEM_PROMPT)
    
    # 기본값 설정
    context = kwargs.get("context", "No additional context provided.")
    code = kwargs.get("code", "")
    
    # Context가 dict인 경우 프론트엔드 컨텍스트 정보 추출
    context_str = context
    if isinstance(context, dict):
        # 기본 컨텍스트 정보 구성
        context_parts = []
        
        # activeApp 정보 추가
        active_app = context.get("activeApp")
        if active_app:
            context_parts.append(f"현재 사용자가 보고 있는 화면: {active_app}")
        
        # selectedItemIds 정보 추가
        selected_item_ids = context.get("selectedItemIds")
        if selected_item_ids:
            if isinstance(selected_item_ids, list):
                items_str = ", ".join(str(item_id) for item_id in selected_item_ids)
                context_parts.append(f"선택된 항목 ID: {items_str}")
            else:
                context_parts.append(f"선택된 항목 ID: {selected_item_ids}")
        
        # 추가 컨텍스트 정보 (url, path, title 등)
        if context.get("url"):
            context_parts.append(f"현재 URL: {context['url']}")
        if context.get("path"):
            context_parts.append(f"경로: {context['path']}")
        if context.get("title"):
            context_parts.append(f"페이지 제목: {context['title']}")
        if context.get("itemId"):
            context_parts.append(f"항목 ID: {context['itemId']}")
        
        # 기타 메타데이터
        metadata = context.get("metadata", {})
        if metadata:
            metadata_str = ", ".join(f"{k}: {v}" for k, v in metadata.items() if v)
            if metadata_str:
                context_parts.append(f"추가 정보: {metadata_str}")
        
        # 컨텍스트 문자열 생성
        if context_parts:
            context_str = "\n".join(context_parts)
        else:
            context_str = "No additional context provided."
    
    return prompt_template.format(context=context_str, code=code)
