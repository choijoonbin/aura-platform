# 프론트엔드 명세 v1.0 구현 가이드

## 📋 개요

프론트엔드 명세 v1.0에 맞춰 AI 에이전트의 사고 과정을 스트리밍하도록 고도화한 구현입니다.

## 🎯 주요 기능

### 1. SSE 이벤트 타입

프론트엔드에서 수신하는 이벤트 타입:

- **`thought`**: 사고 과정 (analysis, planning, reasoning, decision, reflection)
- **`plan_step`**: 계획 단계 (confidence 포함)
- **`tool_execution`**: 도구 실행 (승인 필요 여부 포함)
- **`content`**: 최종 응답 콘텐츠
- **`start`**: 시작 이벤트
- **`end`**: 종료 이벤트
- **`error`**: 에러 이벤트

### 2. LangGraph State 구조

```python
class EnhancedAgentState(TypedDict):
    messages: list[BaseMessage]              # 대화 메시지
    user_id: str                              # 사용자 ID
    tenant_id: str | None                    # 테넌트 ID
    context: dict[str, Any]                   # 추가 컨텍스트
    thought_chain: list[ThoughtEntry]        # 사고 과정 체인
    plan_steps: list[PlanStep]               # 계획 단계 목록
    execution_logs: list[ExecutionLog]       # 실행 로그
    current_step_id: str | None               # 현재 단계 ID
    sources: list[str]                        # 참고 소스 목록
    pending_approvals: list[dict]            # 승인 대기 중인 도구
```

### 3. 워크플로우

```
analyze → plan → execute → [tools (if needed)] → reflect → END
```

각 노드에서:
- **analyze**: 사용자 요청 분석 (thoughtType: analysis)
- **plan**: 실행 계획 수립 (thoughtType: planning, plan_step 이벤트)
- **execute**: LLM 호출 및 도구 선택 (thoughtType: reasoning)
- **tools**: 도구 실행 (tool_execution 이벤트, HITL interrupt 가능)
- **reflect**: 결과 검토 (thoughtType: reflection, content 이벤트)

---

## 📡 API 엔드포인트

### POST `/agents/v2/chat/stream`

고도화된 스트리밍 엔드포인트 (프론트엔드 명세 v1.0)

**Request**:
```json
{
  "message": "Analyze this PR: facebook/react#123",
  "context": {},
  "thread_id": "optional_thread_id"
}
```

**Response** (SSE):
```
data: {"type": "start", "message": "Enhanced agent started", "timestamp": "..."}

data: {"type": "thought", "thoughtType": "analysis", "content": "...", "sources": [...]}

data: {"type": "plan_step", "stepId": "...", "description": "...", "status": "pending", "confidence": 0.8}

data: {"type": "tool_execution", "toolName": "github_get_pr", "status": "running", "requiresApproval": false}

data: {"type": "content", "content": "Based on the PR analysis...", "chunk": false}

data: {"type": "end", "message": "Enhanced agent finished", "timestamp": "..."}
```

---

## 🔧 구현 상세

### 1. SSE 이벤트 스키마

**파일**: `api/schemas/events.py`

- `ThoughtEvent`: 사고 과정 이벤트
- `PlanStepEvent`: 계획 단계 이벤트
- `ToolExecutionEvent`: 도구 실행 이벤트
- `ContentEvent`: 콘텐츠 이벤트

### 2. Enhanced Agent

**파일**: `domains/dev/agents/enhanced_agent.py`

- `EnhancedCodeAgent`: 고도화된 에이전트
- `EnhancedAgentState`: 확장된 상태 구조
- 5개 노드: analyze, plan, execute, tools, reflect

### 3. SSE Hook

**파일**: `domains/dev/agents/hooks.py`

- `SSEEventHook`: 노드 실행 시 이벤트 발행
- `on_node_start`: 노드 시작 시 호출
- `on_node_end`: 노드 종료 시 호출

### 4. HITL Interrupt

**구현 위치**: `domains/dev/agents/enhanced_agent.py` - `_tools_node`

**승인이 필요한 도구**:
- `git_merge`
- `github_create_pr`
- `github_merge_pr`

**동작 방식**:
1. 승인이 필요한 도구 실행 시 `pending_approvals`에 추가
2. 상태를 checkpoint에 저장
3. `tool_execution` 이벤트 발행 (status: pending, requiresApproval: true)
4. 백엔드에서 `/agents/v2/approve` 엔드포인트로 승인
5. 승인 후 실행 재개

### 5. Confidence Score

**구현 위치**: `domains/dev/agents/enhanced_agent.py` - `_calculate_confidence`

**계산 방법**:
1. LLM의 logprobs 사용 (가능한 경우)
2. 응답 길이 및 구조 기반 추정
3. 도구 호출 여부 고려

**결과**: 0.0~1.0 사이의 값

### 6. Source Attribution

**구현 위치**: `domains/dev/agents/enhanced_agent.py` - `_extract_sources`

**추출 소스**:
- 대화 히스토리에서 파일 경로 패턴
- 컨텍스트의 `file_paths`
- 참고한 코드 파일 경로

---

## 🧪 테스트 방법

### 1. 기본 스트리밍 테스트

```bash
export TOKEN="<JWT_TOKEN>"

curl -N -X POST http://localhost:8000/agents/v2/chat/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-ID: tenant1" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What tools do you have?",
    "context": {}
  }'
```

### 2. React Frontend 예시

```typescript
const response = await fetch('/agents/v2/chat/stream', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`,
    'X-Tenant-ID': 'tenant1',
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    message: 'Analyze this PR',
    context: {},
  }),
});

const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const { value, done } = await reader.read();
  if (done) break;
  
  const chunk = decoder.decode(value);
  const lines = chunk.split('\n\n');
  
  for (const line of lines) {
    if (line.startsWith('data: ')) {
      const data = JSON.parse(line.slice(6));
      
      switch (data.type) {
        case 'thought':
          // 사고 과정 표시
          setThoughts(prev => [...prev, data]);
          break;
        case 'plan_step':
          // 계획 단계 표시
          setPlanSteps(prev => [...prev, data]);
          break;
        case 'tool_execution':
          // 도구 실행 표시
          if (data.requiresApproval) {
            // 승인 요청 UI 표시
            showApprovalDialog(data);
          }
          break;
        case 'content':
          // 최종 응답 표시
          setContent(prev => prev + data.content);
          break;
      }
    }
  }
}
```

---

## 📝 다음 단계

### 완료된 작업
- [x] SSE 이벤트 스키마 정의
- [x] Enhanced Agent State 구조화
- [x] LangGraph Hook 구현
- [x] Confidence Score 계산
- [x] Source Attribution
- [x] HITL Interrupt 기본 구조

### 추가 작업 필요
- [ ] LangGraph 표준 Checkpointer 인터페이스 구현
- [ ] 실제 interrupt 메커니즘 완성 (checkpoint 기반 대기)
- [ ] 승인 API 완성 (`/agents/v2/approve`)
- [ ] 테스트 스크립트 작성
- [ ] 문서화 완성

---

**✅ 프론트엔드 명세 v1.0 기본 구조 완성!**
