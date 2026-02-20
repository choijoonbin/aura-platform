"""
System Prompts Module

에이전트 및 워크플로우에 사용되는 시스템 프롬프트를 정의합니다.
Context 기반 동적 프롬프트 주입을 지원합니다.

YAML 기반 외부 프롬프트 파일을 우선 로드하여 코드 수정 없이 프롬프트를 관리할 수 있습니다.
"""
import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# ==================== YAML Prompt Loader ====================
_PROMPTS_DIR = Path(__file__).parent / "prompts"
_yaml_prompt_cache: dict[str, dict[str, Any]] = {}


def _load_yaml_prompt(filename: str) -> dict[str, Any] | None:
    """
    YAML 프롬프트 파일을 로드합니다. 캐싱 적용.
    
    Args:
        filename: 프롬프트 파일명 (예: "aura_auditor.yaml")
    
    Returns:
        파싱된 YAML dict 또는 None (파일 없음/파싱 실패)
    """
    if filename in _yaml_prompt_cache:
        return _yaml_prompt_cache[filename]
    
    filepath = _PROMPTS_DIR / filename
    if not filepath.exists():
        logger.debug(f"YAML prompt file not found: {filepath}")
        return None
    
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            _yaml_prompt_cache[filename] = data
            logger.info(f"Loaded YAML prompt: {filename} (version: {data.get('version', 'unknown')})")
            return data
    except Exception as e:
        logger.warning(f"Failed to load YAML prompt {filename}: {e}")
        return None


def get_auditor_prompt(domain: str = "finance", **kwargs: Any) -> str:
    """
    범용 감사 에이전트 프롬프트를 반환합니다.
    aura_auditor.yaml을 우선 로드하고, 도메인별 확장 규칙을 병합합니다.
    
    Args:
        domain: 도메인 (finance, hr, manufacturing 등) - 대소문자 무관
        **kwargs: 추가 컨텍스트 변수
    
    Returns:
        조합된 시스템 프롬프트 문자열
    
    Usage:
        # 아래 호출 모두 동일하게 동작
        get_auditor_prompt(domain='finance')
        get_auditor_prompt(domain='FINANCE')
        get_auditor_prompt(domain='HR')
        get_auditor_prompt(domain='hr')
    """
    yaml_data = _load_yaml_prompt("aura_auditor.yaml")
    
    if yaml_data is None:
        logger.warning("aura_auditor.yaml not found, falling back to legacy prompt")
        return get_system_prompt(domain, **kwargs)
    
    prompts = yaml_data.get("prompts", {})
    domain_extensions = yaml_data.get("domain_extensions", {})
    
    # 도메인 정규화: 대소문자 무관하게 처리
    domain_normalized = domain.lower().strip()
    domain_display = domain_normalized.upper()  # 표시용
    
    # 기본 프롬프트 조합
    sections = [
        prompts.get("system_role", ""),
        prompts.get("context_reconstruction", ""),
        prompts.get("reasoning_guidelines", ""),
        prompts.get("output_format", ""),
        prompts.get("citation_rules", ""),
        prompts.get("professional_judgment", ""),
        prompts.get("thought_stream_template", ""),
    ]
    
    # 도메인별 확장 규칙 추가 (정규화된 키로 조회)
    if domain_normalized in domain_extensions:
        ext = domain_extensions[domain_normalized]
        additional = ext.get("additional_rules", "")
        tools = ext.get("tools", [])
        if additional:
            sections.append(f"\n[Domain-Specific Rules: {domain_display}]\n{additional}")
        if tools:
            tools_str = ", ".join(tools)
            sections.append(f"\n[Available Tools for {domain_display}]\n{tools_str}")
        logger.debug(f"get_auditor_prompt: Applied domain extension for '{domain_normalized}'")
    else:
        logger.debug(f"get_auditor_prompt: No domain extension found for '{domain_normalized}', using base prompt only")
    
    # 컨텍스트 주입
    context = kwargs.get("context", "")
    if context:
        context_str = context if isinstance(context, str) else str(context)
        sections.append(f"\n[Current Context]\n{context_str}")
    
    return "\n".join(section.strip() for section in sections if section.strip())


def reload_yaml_prompts() -> None:
    """YAML 프롬프트 캐시를 클리어하여 다음 호출 시 재로드합니다."""
    global _yaml_prompt_cache
    _yaml_prompt_cache.clear()
    logger.info("YAML prompt cache cleared")

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

# ==================== Finance Domain Prompts ====================
FINANCE_DOMAIN_SYSTEM_PROMPT = """
당신은 DWP(Digital Workplace Platform)의 전문 AI 금융 감사관 'Aura'입니다.
당신의 임무는 전표 데이터를 분석하여 위반 의심 케이스를 조사하고, 논리적 근거에 기반한 조치를 제안하는 것입니다.

### 핵심 감사 원칙 (Reasoning Strategy):
1. **단계적 근거 수집**: 
   - 먼저 `search_documents`와 `hybrid_retrieve`를 통해 사내 규정집에서 관련 조항을 탐색하십시오.
   - 만약 사내 규정에서 명확한 근거를 찾지 못했다면, 반드시 외부 웹 검색 도구(Tavily 등)를 사용하여 '통상적인 회계 감사 기준', '국세청 가이드라인', '업종별 지출 관행'을 확인하십시오.
   
2. **출처 명시 (Citations)**:
   - 모든 판단 근거에는 반드시 출처를 명시하십시오. 최종 결과(reasoning_summary) 내 URL은 프론트엔드에서 하이퍼링크로 인식되도록 **반드시 표준 마크다운 링크 형식**으로 작성합니다: [표시텍스트](URL)
   - 내부 규정 예시: `[내부규정: 일반경비집행기준.pdf p.24]` 또는 `[참고: 사내 일반경비 집행기준 p.24]`
   - 외부 근거 예시: `[국세청 법인카드 세무처리 안내](https://www.nts.go.kr/...)` — 괄호 안에 URL을 넣어 하이퍼링크로 렌더링되게 할 것.

3. **지능형 추론 (Professional Judgment)**:
   - 명시적인 위반 규정이 없더라도, 결제 시간/장소/패턴이 사회 통념상 업무 연관성이 낮다고 판단되면(예: 주말 심야 유흥업소 이용) 이를 '상식적 판단' 근거와 함께 '점검 필요' 의견으로 제시하십시오.

### 사고 과정 노출 (Thought Streaming):
사용자가 실시간으로 당신의 분석 단계를 인지할 수 있도록, 다음 순서에 따라 `thought_stream`을 생성하십시오:
- (규정 탐색) "사내 규정집에서 해당 업종의 결제 제한 조항이 있는지 확인 중입니다..."
- (외부 검색) "내부 규정에 명시적 제한이 없어, 통상적인 기업 회계 기준 및 국세청 가이드라인을 검색하여 대조합니다..."
- (종합 판단) "수집된 내부/외부 근거를 바탕으로 해당 전표의 위반 위험도를 산출하고 있습니다..."

### 사용 가능 도구:
- get_case: 케이스 상세 조회
- search_documents: 문서 및 사내 규정(RAG) 검색
- get_document: 단일 문서 상세 조회
- get_entity: 거래처/엔티티 정보 조회
- get_open_items: 미결 항목 조회
- web_search (Tavily 등): 외부 지능형 웹 검색 실행
- simulate_action: 액션 실행 결과 미리보기
- propose_action: 조치 제안 (위험도가 높을 경우 HITL 승인 프로세스 작동)

Current context: {context}
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
        "finance": FINANCE_DOMAIN_SYSTEM_PROMPT,
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
        
        # Finance 도메인: caseId, documentIds, entityIds, openItemIds
        if context.get("caseId"):
            context_parts.append(f"케이스 ID: {context['caseId']}")
        if context.get("documentIds"):
            context_parts.append(f"문서 ID 목록: {context['documentIds']}")
        if context.get("entityIds"):
            context_parts.append(f"엔티티 ID 목록: {context['entityIds']}")
        if context.get("openItemIds"):
            context_parts.append(f"미결 항목 ID 목록: {context['openItemIds']}")
        
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
