# Aura-Platform → DWP Frontend 전달 문서

> **전달 대상**: DWP Frontend 개발팀  
> **전달 일자**: 2026-01-16  
> **Aura-Platform 버전**: v0.3.1

---

## 📦 전달 내용 요약

Aura-Platform에서 프론트엔드와의 연동을 위해 구현 완료된 사항과 사용 방법을 전달합니다.

---

## ✅ 구현 완료 사항

### 1. Enhanced Agent API (프론트엔드 명세 v1.0)

**엔드포인트**: `POST /agents/v2/chat/stream`

**Gateway 경로**: `POST /api/aura/agents/v2/chat/stream` (백엔드 Gateway 경유)

**구현 내용**:
- ✅ 프론트엔드 명세 v1.0 완전 준수
- ✅ SSE (Server-Sent Events) 스트리밍
- ✅ 7가지 이벤트 타입 지원:
  - `start` - 시작 이벤트
  - `thought` - 사고 과정 (analysis, planning, reasoning, decision, reflection)
  - `plan_step` - 실행 계획 단계 (confidence 포함)
  - `tool_execution` - 도구 실행 (승인 필요 여부 포함)
  - `content` - 최종 응답 콘텐츠
  - `end` - 종료 이벤트
  - `error` - 에러 이벤트
- ✅ JWT 인증 통합
- ✅ X-Tenant-ID 헤더 검증

**파일**: `api/routes/agents_enhanced.py`

---

### 2. SSE 이벤트 스키마

**파일**: `api/schemas/events.py`

**주요 이벤트 타입**:

#### `thought` 이벤트
```typescript
{
  type: "thought",
  thoughtType: "analysis" | "planning" | "reasoning" | "decision" | "reflection",
  content: string,
  timestamp: string,
  sources: string[],  // 참고 파일 경로, 대화 ID 등
  metadata: Record<string, any>
}
```

#### `plan_step` 이벤트
```typescript
{
  type: "plan_step",
  stepId: string,
  description: string,
  status: "pending" | "in_progress" | "completed" | "failed" | "skipped",
  confidence: number,  // 0.0 ~ 1.0
  timestamp: string,
  metadata: Record<string, any>
}
```

#### `tool_execution` 이벤트
```typescript
{
  type: "tool_execution",
  toolName: string,
  toolArgs: Record<string, any>,
  status: "pending" | "running" | "success" | "failed" | "cancelled",
  result: any,
  error: string | null,
  requiresApproval: boolean,  // 승인 필요 여부
  timestamp: string,
  metadata: Record<string, any>
}
```

#### `content` 이벤트
```typescript
{
  type: "content",
  content: string,
  chunk: boolean,  // 스트리밍 중 청크 여부
  timestamp: string,
  metadata: Record<string, any>
}
```

---

### 3. HITL (Human-In-The-Loop) 지원

**구현 내용**:
- ✅ 중요 도구 실행 전 승인 요청
- ✅ `tool_execution` 이벤트에 `requiresApproval: true` 포함
- ✅ 승인 대기 상태 관리
- ✅ 승인 API 엔드포인트: `POST /agents/v2/approve`

**승인이 필요한 도구**:
- `git_merge` - Git 병합
- `github_create_pr` - PR 생성
- `github_merge_pr` - PR 병합

---

## 🔧 프론트엔드 연동 방법

### 1. API 엔드포인트

**경로**: `POST /agents/v2/chat/stream`

**Gateway 경로**: `POST /api/aura/agents/v2/chat/stream`

**요청 헤더**:
```
Authorization: Bearer {JWT_TOKEN}
X-Tenant-ID: {tenant_id}
Content-Type: application/json
```

**요청 Body**:
```json
{
  "message": "Analyze this PR: facebook/react#123",
  "context": {},
  "thread_id": "optional_thread_id"
}
```

**응답**: SSE 스트림 (`text/event-stream`)

---

### 2. React 예시 코드

```typescript
import { useState, useEffect } from 'react';

interface SSEEvent {
  type: string;
  [key: string]: any;
}

export function AuraAgentStream() {
  const [events, setEvents] = useState<SSEEvent[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);

  const startStream = async (message: string) => {
    setIsStreaming(true);
    setEvents([]);

    const token = localStorage.getItem('jwt_token');
    const tenantId = localStorage.getItem('tenant_id');

    const response = await fetch(
      'http://localhost:8080/api/aura/agents/v2/chat/stream',
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'X-Tenant-ID': tenantId || '',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message,
          context: {},
        }),
      }
    );

    const reader = response.body?.getReader();
    const decoder = new TextDecoder();

    if (!reader) return;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value);
      const lines = chunk.split('\n');

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6));
            setEvents(prev => [...prev, data]);

            // HITL 승인 요청 처리
            if (data.type === 'tool_execution' && data.requiresApproval) {
              // 승인 다이얼로그 표시
              const approved = await showApprovalDialog(data);
              if (approved) {
                // 승인 API 호출
                await approveToolExecution(data.toolName, data.toolArgs);
              }
            }
          } catch (e) {
            console.error('Failed to parse SSE event:', e);
          }
        }
      }
    }

    setIsStreaming(false);
  };

  return (
    <div>
      <button onClick={() => startStream('Analyze this code')}>
        Start Stream
      </button>
      <div>
        {events.map((event, idx) => (
          <div key={idx}>
            <strong>{event.type}:</strong> {JSON.stringify(event)}
          </div>
        ))}
      </div>
    </div>
  );
}
```

---

### 3. 이벤트 처리 가이드

#### `thought` 이벤트 처리
```typescript
if (event.type === 'thought') {
  // 사고 과정 표시
  displayThought(event.thoughtType, event.content, event.sources);
}
```

#### `plan_step` 이벤트 처리
```typescript
if (event.type === 'plan_step') {
  // 계획 단계 업데이트
  updatePlanStep(event.stepId, {
    description: event.description,
    status: event.status,
    confidence: event.confidence,
  });
}
```

#### `tool_execution` 이벤트 처리
```typescript
if (event.type === 'tool_execution') {
  // 도구 실행 상태 표시
  displayToolExecution(event.toolName, event.status, event.result);

  // 승인 필요 시
  if (event.requiresApproval) {
    const approved = await showApprovalDialog({
      tool: event.toolName,
      args: event.toolArgs,
    });
    
    if (approved) {
      await approveToolExecution(event.toolName, event.toolArgs);
    }
  }
}
```

#### `content` 이벤트 처리
```typescript
if (event.type === 'content') {
  // 최종 응답 표시
  appendContent(event.content, event.chunk);
}
```

---

## 📋 통합 체크리스트

### 프론트엔드 구현 필요 사항

- [ ] SSE 스트리밍 클라이언트 구현
- [ ] 7가지 이벤트 타입 처리
- [ ] HITL 승인 다이얼로그 구현
- [ ] JWT 토큰 관리
- [ ] X-Tenant-ID 헤더 전송
- [ ] 에러 처리 (error 이벤트)
- [ ] 로딩 상태 관리 (start/end 이벤트)

---

## 🔍 테스트 방법

### 1. curl로 테스트

```bash
# JWT 토큰 생성
TOKEN=$(cd /path/to/dwp-backend/dwp-auth-server && python3 test_jwt_for_aura.py --token-only)

# SSE 스트리밍 요청
curl -N -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Tenant-ID: tenant1" \
  -H "Content-Type: application/json" \
  -d '{"message": "Test message"}' \
  "http://localhost:8080/api/aura/agents/v2/chat/stream"
```

### 2. 예상 출력

```
data: {"type":"start","message":"Enhanced agent started","timestamp":"..."}

data: {"type":"thought","thoughtType":"analysis","content":"사용자 요청 분석 중...","sources":[]}

data: {"type":"plan_step","stepId":"uuid-1","description":"요청 처리","status":"pending","confidence":0.8}

data: {"type":"tool_execution","toolName":"github_get_pr","status":"running","requiresApproval":false}

data: {"type":"content","content":"Based on the PR analysis...","chunk":false}

data: {"type":"end","message":"Enhanced agent finished","timestamp":"..."}
```

---

## ⚠️ 주의사항

### 1. 포트 정보

- **Aura-Platform**: 포트 9000
- **Gateway**: 포트 8080 (프론트엔드는 Gateway를 통해 접근)

### 2. CORS 설정

Aura-Platform의 CORS 설정에 프론트엔드 URL이 포함되어 있어야 합니다.

**환경 변수**:
```bash
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:4200
```

### 3. JWT 토큰

- 백엔드에서 발행한 JWT 토큰 사용
- 토큰 만료 시간 확인 필요
- 토큰 갱신 로직 구현 권장

### 4. SSE 연결 관리

- 연결 끊김 시 재연결 로직 구현
- 타임아웃 처리 (기본 300초)
- 에러 이벤트 처리

---

## 📊 현재 상태

### 구현 완료율

| 항목 | Aura-Platform | DWP Frontend | 상태 |
|------|--------------|-------------|------|
| SSE 스트리밍 | ✅ 100% | - | 완료 |
| 이벤트 스키마 | ✅ 100% | - | 완료 |
| HITL 지원 | ✅ 100% | - | 완료 |
| 프론트엔드 클라이언트 | - | ⚠️ 0% | **구현 필요** |

**전체 진행률**: 50% (Aura-Platform 완료, Frontend 클라이언트 구현 필요)

---

## 🔗 관련 문서

### Aura-Platform 문서
- [FRONTEND_V1_SPEC.md](FRONTEND_V1_SPEC.md) - 프론트엔드 명세 v1.0 상세
- [BACKEND_INTEGRATION_STATUS.md](BACKEND_INTEGRATION_STATUS.md) - 백엔드 연동 상태

### DWP Backend 문서
- [AURA_PLATFORM_INTEGRATION_GUIDE.md](AURA_PLATFORM_INTEGRATION_GUIDE.md) - 백엔드 연동 가이드

---

## 📞 문의

통합 과정에서 문제가 발생하거나 추가 정보가 필요한 경우, Aura-Platform 개발팀에 문의하세요.

**다음 단계**: 프론트엔드에서 SSE 클라이언트 구현 후 통합 테스트 진행

---

**문서 버전**: v1.0  
**최종 업데이트**: 2026-01-16
