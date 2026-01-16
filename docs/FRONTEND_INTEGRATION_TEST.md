# Aura-Platform 통합 테스트 가이드 (프론트엔드)

> **작성일**: 2026-01-16  
> **버전**: v1.0  
> **대상**: DWP Frontend 개발팀  
> **목적**: Aura-Platform과의 통합 테스트 수행 가이드

---

## 📋 목차

1. [Aura-Platform 구현 상태 요약](#aura-platform-구현-상태-요약)
2. [사전 준비사항](#사전-준비사항)
3. [프론트엔드 테스트 항목](#프론트엔드-테스트-항목)
4. [상세 테스트 시나리오](#상세-테스트-시나리오)
5. [React 예제 코드](#react-예제-코드)
6. [문제 해결 가이드](#문제-해결-가이드)

---

## Aura-Platform 구현 상태 요약

### ✅ 구현 완료 사항

1. **SSE 스트리밍 API**
   - 엔드포인트: `POST /api/aura/test/stream` (Gateway 경유)
   - 이벤트 형식: `id: {event_id}\nevent: {type}\ndata: {json}`
   - 재연결 지원: `Last-Event-ID` 헤더

2. **이벤트 타입**
   - `start`: 시작 이벤트
   - `thought`: 사고 과정 (analysis, planning, reasoning, decision, reflection)
   - `plan_step`: 계획 단계 (confidence 포함)
   - `plan_step_update`: 계획 단계 업데이트
   - `timeline_step_update`: 타임라인 단계 업데이트
   - `tool_execution`: 도구 실행
   - `hitl`: 승인 요청
   - `content`: 최종 결과
   - `end`: 종료 이벤트
   - `error`: 에러 이벤트
   - `failed`: 작업 실패 (HITL 타임아웃 등)

3. **Context 기반 프롬프트 주입**
   - `activeApp`: 현재 활성 앱
   - `selectedItemIds`: 선택된 항목 ID 목록
   - `url`, `path`, `title`, `itemId`: 현재 화면 정보
   - `metadata`: 추가 메타데이터

4. **HITL (Human-In-The-Loop) 지원**
   - 승인 요청 이벤트 (`hitl`)
   - 승인/거절 API 연동
   - 타임아웃 처리 (300초)

---

## 사전 준비사항

### 1. 환경 확인

```bash
# Gateway 실행 확인
curl http://localhost:8080/api/main/health

# Aura-Platform 서버 실행 확인
curl http://localhost:9000/health
```

### 2. JWT 토큰 준비

프론트엔드에서 JWT 토큰을 백엔드로부터 받아야 합니다.

**토큰 구조**:
```json
{
  "sub": "user123",           // 사용자 ID
  "tenant_id": "tenant1",     // 테넌트 ID
  "exp": 1706152860,          // 만료 시간 (Unix timestamp)
  "iat": 1706149260           // 발급 시간 (Unix timestamp)
}
```

### 3. API 엔드포인트

- **SSE 스트리밍**: `POST /api/aura/test/stream`
- **HITL 승인**: `POST /api/aura/hitl/approve/{requestId}`
- **HITL 거절**: `POST /api/aura/hitl/reject/{requestId}`

---

## 프론트엔드 테스트 항목

### ✅ 테스트 체크리스트

#### 1. SSE 스트리밍 연결 테스트
- [ ] POST 요청으로 SSE 스트림 연결
- [ ] 이벤트 수신 및 파싱
- [ ] 모든 이벤트 타입 처리
- [ ] 스트림 종료 표시 (`data: [DONE]`) 처리

#### 2. 이벤트 타입별 처리 테스트
- [ ] `start` 이벤트 처리
- [ ] `thought` 이벤트 처리 (thoughtType별 구분)
- [ ] `plan_step` 이벤트 처리 (confidence 표시)
- [ ] `plan_step_update` 이벤트 처리
- [ ] `timeline_step_update` 이벤트 처리
- [ ] `tool_execution` 이벤트 처리
- [ ] `hitl` 이벤트 처리 (승인 UI 표시)
- [ ] `content` 이벤트 처리 (스트리밍 텍스트 표시)
- [ ] `end` 이벤트 처리
- [ ] `error` 이벤트 처리
- [ ] `failed` 이벤트 처리

#### 3. Context 전달 테스트
- [ ] `activeApp` 전달 및 프롬프트 반영 확인
- [ ] `selectedItemIds` 전달 및 프롬프트 반영 확인
- [ ] `url`, `path`, `title` 전달 확인
- [ ] `metadata` 전달 확인

#### 4. HITL 승인 프로세스 테스트
- [ ] HITL 이벤트 수신 시 승인 UI 표시
- [ ] 승인 버튼 클릭 시 승인 API 호출
- [ ] 거절 버튼 클릭 시 거절 API 호출
- [ ] 승인/거절 후 스트림 재개 확인
- [ ] 타임아웃 처리 (300초)

#### 5. 재연결 지원 테스트
- [ ] 연결 끊김 감지
- [ ] `Last-Event-ID` 헤더 포함 재연결
- [ ] 중단 지점부터 이벤트 재개
- [ ] `thread_id` 전달로 상태 복원

#### 6. 에러 처리 테스트
- [ ] 네트워크 오류 처리
- [ ] 인증 오류 처리 (401)
- [ ] 권한 오류 처리 (403)
- [ ] 서버 오류 처리 (500)
- [ ] 타임아웃 오류 처리

#### 7. UI/UX 테스트
- [ ] 스트리밍 텍스트 실시간 표시
- [ ] 사고 과정(thought) 표시
- [ ] 계획 단계(plan_step) 진행률 표시
- [ ] 타임라인 업데이트 표시
- [ ] 로딩 상태 표시
- [ ] 에러 메시지 표시

---

## 상세 테스트 시나리오

### 시나리오 1: 기본 SSE 스트리밍 연결

**목적**: SSE 스트리밍이 정상적으로 연결되고 이벤트를 수신하는지 확인

**테스트 단계**:

1. **SSE 연결 시작**:
```typescript
const eventSource = new EventSource(
  '/api/aura/test/stream',
  {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'X-Tenant-ID': tenantId,
      'X-User-ID': userId,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      prompt: '안녕하세요, 테스트입니다',
      context: {
        activeApp: 'mail',
        url: 'http://localhost:4200/mail'
      }
    })
  }
);
```

**참고**: `EventSource`는 GET만 지원하므로, `fetch` API를 사용해야 합니다.

**올바른 구현**:
```typescript
const response = await fetch('/api/aura/test/stream', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`,
    'X-Tenant-ID': tenantId,
    'X-User-ID': userId,
    'Content-Type': 'application/json',
    'Accept': 'text/event-stream',
  },
  body: JSON.stringify({
    prompt: '안녕하세요, 테스트입니다',
    context: {
      activeApp: 'mail',
      url: 'http://localhost:4200/mail'
    }
  })
});

const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const { value, done } = await reader.read();
  if (done) break;
  
  const chunk = decoder.decode(value);
  // SSE 이벤트 파싱 및 처리
}
```

2. **이벤트 수신 및 파싱**:
```typescript
function parseSSEEvent(chunk: string): SSEEvent[] {
  const events: SSEEvent[] = [];
  const lines = chunk.split('\n');
  
  let currentEvent: Partial<SSEEvent> = {};
  
  for (const line of lines) {
    if (line.startsWith('id: ')) {
      currentEvent.id = line.substring(4);
    } else if (line.startsWith('event: ')) {
      currentEvent.type = line.substring(7);
    } else if (line.startsWith('data: ')) {
      const data = line.substring(6);
      if (data === '[DONE]') {
        // 스트림 종료
        return events;
      }
      currentEvent.data = JSON.parse(data);
      events.push(currentEvent as SSEEvent);
      currentEvent = {};
    }
  }
  
  return events;
}
```

3. **예상 결과**:
   - ✅ `start` 이벤트 수신
   - ✅ `thought` 이벤트 수신 (여러 개)
   - ✅ `plan_step` 이벤트 수신
   - ✅ `content` 이벤트 수신 (스트리밍 텍스트)
   - ✅ `end` 이벤트 수신
   - ✅ `data: [DONE]` 수신

---

### 시나리오 2: Context 기반 프롬프트 주입 테스트

**목적**: 프론트엔드에서 전달한 context가 에이전트의 프롬프트에 반영되는지 확인

**테스트 단계**:

1. **Context 포함 요청**:
```typescript
const response = await fetch('/api/aura/test/stream', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`,
    'X-Tenant-ID': tenantId,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    prompt: '현재 화면에서 선택된 항목들을 분석해주세요',
    context: {
      activeApp: 'mail',
      selectedItemIds: [1, 2, 3],
      url: 'http://localhost:4200/mail',
      path: '/mail',
      title: '메일 인박스',
      itemId: 'msg-123',
      metadata: {
        folder: 'inbox',
        unreadCount: 5
      }
    }
  })
});
```

2. **에이전트 응답 확인**:
   - ✅ 에이전트가 "현재 사용자가 보고 있는 화면: mail"을 인지
   - ✅ 에이전트가 "선택된 항목 ID: 1, 2, 3"을 인지
   - ✅ 에이전트가 현재 URL, 경로, 제목을 참고하여 응답

3. **검증 방법**:
   - `thought` 이벤트의 `content`에서 context 정보 언급 확인
   - 에이전트 응답이 context에 맞게 생성되는지 확인

---

### 시나리오 3: HITL 승인 프로세스 테스트

**목적**: HITL 승인 요청이 정상적으로 처리되는지 확인

**테스트 단계**:

1. **HITL 이벤트 수신**:
```typescript
eventSource.onmessage = (event) => {
  const data = JSON.parse(event.data);
  
  if (data.type === 'hitl') {
    // 승인 UI 표시
    showApprovalDialog({
      requestId: data.requestId,
      actionType: data.actionType,
      message: data.message,
      context: data.context
    });
  }
};
```

2. **승인 버튼 클릭**:
```typescript
async function handleApprove(requestId: string) {
  const response = await fetch(`/api/aura/hitl/approve/${requestId}`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'X-Tenant-ID': tenantId,
      'X-User-ID': userId,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({})
  });
  
  if (response.ok) {
    // 승인 성공, 스트림 계속 진행
    console.log('Approval successful');
  }
}
```

3. **거절 버튼 클릭**:
```typescript
async function handleReject(requestId: string, reason?: string) {
  const response = await fetch(`/api/aura/hitl/reject/${requestId}`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'X-Tenant-ID': tenantId,
      'X-User-ID': userId,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      reason: reason || 'User rejected'
    })
  });
  
  if (response.ok) {
    // 거절 성공, 스트림 종료
    console.log('Rejection successful');
  }
}
```

4. **예상 결과**:
   - ✅ HITL 이벤트 수신 시 승인 UI 표시
   - ✅ 승인 클릭 시 스트림이 계속 진행
   - ✅ 거절 클릭 시 스트림 종료 및 에러 메시지 표시

---

### 시나리오 4: 재연결 지원 테스트

**목적**: 연결이 끊겼을 때 재연결이 정상 작동하는지 확인

**테스트 단계**:

1. **연결 끊김 감지**:
```typescript
let lastEventId: string | null = null;

eventSource.onmessage = (event) => {
  // 이벤트 ID 저장
  if (event.id) {
    lastEventId = event.id;
  }
  
  // 이벤트 처리
  handleEvent(JSON.parse(event.data));
};

// 연결 끊김 감지
reader.closed.then(() => {
  console.log('Connection closed, attempting reconnect...');
  reconnect(lastEventId);
});
```

2. **재연결 시도**:
```typescript
async function reconnect(lastEventId: string | null) {
  const headers: Record<string, string> = {
    'Authorization': `Bearer ${token}`,
    'X-Tenant-ID': tenantId,
    'Content-Type': 'application/json',
    'Accept': 'text/event-stream',
  };
  
  // Last-Event-ID 헤더 추가
  if (lastEventId) {
    headers['Last-Event-ID'] = lastEventId;
  }
  
  const response = await fetch('/api/aura/test/stream', {
    method: 'POST',
    headers,
    body: JSON.stringify({
      prompt: originalPrompt,
      context: originalContext,
      thread_id: threadId  // 이전 스레드 ID
    })
  });
  
  // 스트림 재개
  const reader = response.body.getReader();
  // ... 이벤트 처리 계속
}
```

3. **예상 결과**:
   - ✅ 재연결 시 `Last-Event-ID` 헤더 전달
   - ✅ Aura-Platform이 중단 지점부터 이벤트 재개
   - ✅ `thread_id`가 있으면 상태 복원

---

### 시나리오 5: 에러 처리 테스트

**목적**: 다양한 에러 상황이 정상적으로 처리되는지 확인

#### 5.1 인증 오류 (401)

```typescript
const response = await fetch('/api/aura/test/stream', {
  method: 'POST',
  headers: {
    'Authorization': 'Bearer invalid_token',
    'X-Tenant-ID': tenantId,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    prompt: 'test',
    context: {}
  })
});

// 예상: 401 Unauthorized
if (response.status === 401) {
  // 로그인 페이지로 리다이렉트 또는 에러 메시지 표시
  showError('인증이 필요합니다. 다시 로그인해주세요.');
}
```

#### 5.2 네트워크 오류

```typescript
try {
  const response = await fetch('/api/aura/test/stream', {
    // ... 요청 설정
  });
  
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }
  
  // 스트림 처리
} catch (error) {
  if (error instanceof TypeError) {
    // 네트워크 오류
    showError('네트워크 연결을 확인해주세요.');
  } else {
    // 기타 오류
    showError('오류가 발생했습니다. 잠시 후 다시 시도해주세요.');
  }
}
```

#### 5.3 HITL 타임아웃

```typescript
eventSource.onmessage = (event) => {
  const data = JSON.parse(event.data);
  
  if (data.type === 'failed') {
    if (data.errorType === 'TimeoutError') {
      // HITL 타임아웃
      showError('사용자 응답 지연으로 작업이 취소되었습니다.');
    }
  }
};
```

---

## React 예제 코드

### 완전한 React 컴포넌트 예제

```typescript
import React, { useState, useEffect, useRef } from 'react';

interface SSEEvent {
  id?: string;
  type: string;
  data: any;
}

interface AuraStreamProps {
  token: string;
  tenantId: string;
  userId: string;
  prompt: string;
  context?: Record<string, any>;
  onEvent?: (event: SSEEvent) => void;
  onComplete?: () => void;
  onError?: (error: Error) => void;
}

export const AuraStream: React.FC<AuraStreamProps> = ({
  token,
  tenantId,
  userId,
  prompt,
  context = {},
  onEvent,
  onComplete,
  onError,
}) => {
  const [isStreaming, setIsStreaming] = useState(false);
  const [lastEventId, setLastEventId] = useState<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const startStream = async () => {
    try {
      setIsStreaming(true);
      abortControllerRef.current = new AbortController();

      const headers: Record<string, string> = {
        'Authorization': `Bearer ${token}`,
        'X-Tenant-ID': tenantId,
        'X-User-ID': userId,
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream',
      };

      if (lastEventId) {
        headers['Last-Event-ID'] = lastEventId;
      }

      const response = await fetch('/api/aura/test/stream', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          prompt,
          context,
        }),
        signal: abortControllerRef.current.signal,
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error('Response body is not readable');
      }

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        
        if (done) {
          setIsStreaming(false);
          onComplete?.();
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const events = parseSSEEvents(buffer);
        
        for (const event of events) {
          if (event.id) {
            setLastEventId(event.id);
          }
          onEvent?.(event);
        }
      }
    } catch (error) {
      setIsStreaming(false);
      if (error instanceof Error && error.name !== 'AbortError') {
        onError?.(error);
      }
    }
  };

  const stopStream = () => {
    abortControllerRef.current?.abort();
    setIsStreaming(false);
  };

  const parseSSEEvents = (chunk: string): SSEEvent[] => {
    const events: SSEEvent[] = [];
    const lines = chunk.split('\n');
    
    let currentEvent: Partial<SSEEvent> = {};
    let dataBuffer = '';

    for (const line of lines) {
      if (line.startsWith('id: ')) {
        currentEvent.id = line.substring(4);
      } else if (line.startsWith('event: ')) {
        currentEvent.type = line.substring(7);
      } else if (line.startsWith('data: ')) {
        const data = line.substring(6);
        if (data === '[DONE]') {
          return events;
        }
        dataBuffer += data;
      } else if (line === '' && dataBuffer) {
        // 빈 줄 = 이벤트 종료
        try {
          currentEvent.data = JSON.parse(dataBuffer);
          events.push(currentEvent as SSEEvent);
        } catch (e) {
          console.error('Failed to parse SSE data:', e);
        }
        currentEvent = {};
        dataBuffer = '';
      }
    }

    return events;
  };

  useEffect(() => {
    return () => {
      stopStream();
    };
  }, []);

  return {
    startStream,
    stopStream,
    isStreaming,
    lastEventId,
  };
};
```

---

## 문제 해결 가이드

### 문제 1: SSE 연결이 시작되지 않음

**증상**: `fetch` 요청 후 응답이 없음

**해결 방법**:
1. 네트워크 탭에서 요청 확인
2. CORS 설정 확인
3. Gateway 로그 확인
4. Aura-Platform 서버 로그 확인

### 문제 2: 이벤트가 파싱되지 않음

**증상**: 이벤트 데이터를 읽을 수 없음

**해결 방법**:
1. SSE 형식 확인 (`id:`, `event:`, `data:`)
2. JSON 파싱 오류 확인
3. `data: [DONE]` 처리 확인

### 문제 3: HITL 승인 UI가 표시되지 않음

**증상**: `hitl` 이벤트를 받지 못함

**해결 방법**:
1. 이벤트 타입 필터링 확인
2. 에이전트가 승인이 필요한 작업을 수행하는지 확인
3. HITL 이벤트 형식 확인

### 문제 4: 재연결이 작동하지 않음

**증상**: 재연결 후 이벤트가 재개되지 않음

**해결 방법**:
1. `Last-Event-ID` 헤더 전달 확인
2. `thread_id` 전달 확인
3. Aura-Platform 로그에서 재연결 처리 확인

---

## 테스트 결과 기록

### 테스트 결과 템플릿

```markdown
## 테스트 결과

**테스트 일시**: YYYY-MM-DD HH:MM:SS
**테스트 담당자**: [이름]
**브라우저**: [Chrome/Firefox/Safari] [버전]
**Aura-Platform 버전**: v0.3.3

### 테스트 항목별 결과

#### 1. SSE 스트리밍 연결
- [ ] 통과
- [ ] 실패 (상세: ___________)

#### 2. 이벤트 타입별 처리
- [ ] 통과
- [ ] 실패 (상세: ___________)

#### 3. Context 전달
- [ ] 통과
- [ ] 실패 (상세: ___________)

#### 4. HITL 승인 프로세스
- [ ] 통과
- [ ] 실패 (상세: ___________)

#### 5. 재연결 지원
- [ ] 통과
- [ ] 실패 (상세: ___________)

#### 6. 에러 처리
- [ ] 통과
- [ ] 실패 (상세: ___________)

#### 7. UI/UX
- [ ] 통과
- [ ] 실패 (상세: ___________)

### 발견된 이슈

1. [이슈 1]
   - 설명: ___________
   - 재현 방법: ___________
   - 우선순위: [High/Medium/Low]

2. [이슈 2]
   - 설명: ___________
   - 재현 방법: ___________
   - 우선순위: [High/Medium/Low]

### 추가 확인 사항

- ___________
```

---

## 참고 자료

- **Aura-Platform 문서**:
  - `docs/FRONTEND_HANDOFF.md`: 프론트엔드 전달 문서
  - `docs/FRONTEND_V1_SPEC.md`: 프론트엔드 명세 v1.0

- **API 엔드포인트**:
  - `POST /api/aura/test/stream`: SSE 스트리밍
  - `POST /api/aura/hitl/approve/{requestId}`: 승인 처리
  - `POST /api/aura/hitl/reject/{requestId}`: 거절 처리

- **이벤트 스키마**:
  - `api/schemas/events.py`: 모든 이벤트 타입 정의

---

**문서 버전**: v1.0  
**최종 업데이트**: 2026-01-16  
**담당자**: Aura-Platform 개발팀
