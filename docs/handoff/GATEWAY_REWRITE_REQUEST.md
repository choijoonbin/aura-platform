# Gateway 경로 Rewrite 요청

> **대상**: Gateway 개발팀  
> **작성일**: 2026-02-06  
> **목적**: Aura-Platform Finance API 경로 매핑

---

## 요청 내용

`/api/synapse/agent-tools/agents/**` 라우트에서 Aura-Platform으로 전달 시 **경로를 rewrite**해 주세요.

### 현재 동작
- Gateway 수신: `POST /api/synapse/agent-tools/agents/finance/stream`
- Aura 전달: `POST /aura/agents/finance/stream` (또는 동일 경로 그대로 전달)
- **문제**: Aura-Platform의 실제 경로는 `/agents/finance/stream` (prefix `/aura` 없음)

### 요청 동작
- Gateway 수신: `POST /api/synapse/agent-tools/agents/finance/stream`
- Aura 전달: `POST /agents/finance/stream` ← **RewritePath 적용**

---

## Rewrite 규칙

| Gateway 수신 경로 | Aura 전달 경로 |
|------------------|----------------|
| `/api/synapse/agent-tools/agents/**` | `/agents/**` |

**예시**
- `/api/synapse/agent-tools/agents/finance/stream` → `/agents/finance/stream`

---

## Aura-Platform 실제 경로 및 요청 형식

| 경로 | 메서드 | 요청 Body | 설명 |
|------|--------|-----------|------|
| `/agents/finance/stream` | POST | `{"prompt":"..."}` 또는 `{"message":"..."}`, `context` 선택 | Finance 에이전트 SSE 스트리밍 |
| `/agents/chat` | POST | Code Agent 채팅 |
| `/agents/chat/stream` | POST | Code Agent 스트리밍 |
| `/agents/v2/chat/stream` | POST | Enhanced Agent 스트리밍 |
| `/aura/test/stream` | POST | 백엔드 연동용 스트리밍 |
| `/aura/cases/{caseId}/stream` | GET | Case Detail 스트림 |

---

## Spring Cloud Gateway 예시

```yaml
# RewritePath 필터 예시
- id: aura-agents-rewrite
  uri: http://aura-platform:9000
  predicates:
    - Path=/api/synapse/agent-tools/agents/**
  filters:
    - RewritePath=/api/synapse/agent-tools/agents/(?<segment>.*), /agents/${segment}
```

또는 Java 설정:
```java
// RewritePath: /api/synapse/agent-tools/agents/** → /agents/**
.route("aura_agents", r -> r
    .path("/api/synapse/agent-tools/agents/**")
    .filters(f -> f.rewritePath("/api/synapse/agent-tools/agents/(?<segment>.*)", "/agents/${segment}"))
    .uri("http://aura-platform:9000"))
```

---

## 확인 사항

- [ ] RewritePath 적용 후 `POST /api/synapse/agent-tools/agents/finance/stream` → Aura `POST /agents/finance/stream` 정상 동작
- [ ] Authorization 헤더 그대로 전달 (기존 확인됨 ✅)
