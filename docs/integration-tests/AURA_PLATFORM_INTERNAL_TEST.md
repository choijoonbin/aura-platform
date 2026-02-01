# Aura-Platform 내부 테스트 가이드

> **작성일**: 2026-01-16  
> **버전**: v1.0  
> **대상**: Aura-Platform 개발팀  
> **목적**: Aura-Platform 에이전트 엔진의 내부 동작 검증

---

## 📋 목차

1. [테스트 목표](#테스트-목표)
2. [사전 준비사항](#사전-준비사항)
3. [핵심 테스트 항목](#핵심-테스트-항목)
4. [상세 테스트 시나리오](#상세-테스트-시나리오)
5. [검증 방법](#검증-방법)
6. [문제 해결 가이드](#문제-해결-가이드)

---

## 테스트 목표

프론트엔드 명세 v1.0에 맞는 정확한 SSE 이벤트 발행 및 중단점 제어를 확인합니다.

**핵심 검증 사항**:
- ✅ SSE 이벤트 스키마 정확성
- ✅ LangGraph Interrupt 동작
- ✅ 승인 신호 대기 및 재개
- ✅ Context 활용 (프롬프트 동적 반영)
- ✅ 종료 플래그 전송
- ✅ **SSE 재연결**: `id` / `Last-Event-ID` 정책 및 중복·순서 보장 → [SSE 재연결 정책](../backend-integration/SSE_RECONNECT_POLICY.md) 참고

---

## 사전 준비사항

### 1. 환경 설정

```bash
# Aura-Platform 서버 실행
uvicorn main:app --reload --host 0.0.0.0 --port 9000

# Redis 실행 확인
docker ps | grep redis
redis-cli ping

# 환경 변수 확인
cat .env | grep -E "OPENAI_API_KEY|JWT_SECRET|REDIS"
```

### ⚠️ OPENAI_API_KEY 필요 여부

**OPENAI_API_KEY 없이 테스트 가능한 항목**:
- ✅ SSE 이벤트 스키마 검증 (에러 이벤트 포함)
- ✅ 종료 플래그 전송 (`data: [DONE]`)
- ✅ Context 활용 (프롬프트 생성 로직만)
- ✅ 에러 처리 및 응답 형식

**OPENAI_API_KEY가 필요한 항목**:
- ❌ 실제 LLM 호출 및 응답 생성
- ❌ `thought`, `plan_step`, `content` 이벤트 생성
- ❌ HITL Interrupt 실제 동작 (승인이 필요한 도구 실행)
- ❌ 승인 신호 대기 및 재개
- ❌ 에이전트의 실제 추론 과정

> **참고**: OPENAI_API_KEY가 없어도 기본적인 스키마 검증과 에러 처리는 테스트할 수 있습니다.  
> 실제 에이전트 동작을 테스트하려면 OPENAI_API_KEY가 필요합니다.

### 2. 테스트 도구 준비

```bash
# JWT 토큰 생성
cd dwp-backend/dwp-auth-server
python3 test_jwt_for_aura.py --token-only

# 테스트 변수 설정
export TOKEN="<생성된_JWT_토큰>"
export TENANT_ID="tenant1"
export USER_ID="user123"
```

### 3. 로그 모니터링

```bash
# Aura-Platform 로그 모니터링
tail -f /tmp/aura-platform.log

# Redis 모니터링 (별도 터미널)
redis-cli MONITOR
```

---

## 핵심 테스트 항목

### ✅ 테스트 체크리스트

#### 1. SSE 이벤트 스키마 준수
- [ ] `thought` 이벤트: 필드명과 데이터 타입 정확성
- [ ] `plan_step` 이벤트: 필드명과 데이터 타입 정확성
- [ ] `tool_execution` 이벤트: 필드명과 데이터 타입 정확성
- [ ] `hitl` 이벤트: 필드명과 데이터 타입 정확성
- [ ] `content` 이벤트: 필드명과 데이터 타입 정확성
- [ ] 모든 이벤트에 `timestamp` 필드 포함 (Unix timestamp, 초 단위)
- [ ] 모든 이벤트에 `id:` 라인 포함 (재연결 지원)

#### 2. LangGraph Interrupt
- [ ] HITL 이벤트 발행 시 작업 즉시 중단
- [ ] Redis에 체크포인트(State) 안전하게 저장
- [ ] `pending_approvals` 상태 정확히 기록
- [ ] 중단 시점의 상태 정보 보존

#### 3. 승인 신호 대기
- [ ] Redis Pub/Sub 구독 정상 작동
- [ ] 승인 신호 수신 시 중단된 노드부터 재개
- [ ] 거절 신호 수신 시 적절한 에러 처리
- [ ] 타임아웃 처리 (300초)

#### 4. Context 활용
- [ ] `activeApp`을 시스템 프롬프트에 반영
- [ ] `selectedItemIds`를 시스템 프롬프트에 반영
- [ ] `url`, `path`, `title`, `itemId`를 시스템 프롬프트에 반영
- [ ] `metadata`를 시스템 프롬프트에 반영
- [ ] 에이전트 응답에 context 정보 반영 확인

#### 5. 종료 플래그
- [ ] 모든 작업 완료 시 `data: [DONE]\n\n` 전송
- [ ] 에러 발생 시에도 종료 플래그 전송
- [ ] HITL 타임아웃 시 종료 플래그 전송

---

## 상세 테스트 시나리오

### 시나리오 1: SSE 이벤트 스키마 준수 검증

**목적**: 모든 이벤트가 프론트엔드 명세 v1.0에 맞는 형식으로 발행되는지 확인

**테스트 단계**:

1. **SSE 스트림 시작**:
```bash
curl -N -X POST http://localhost:9000/aura/test/stream \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Tenant-ID: ${TENANT_ID}" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "GitHub PR을 분석해주세요",
    "context": {
      "activeApp": "mail"
    }
  }' > /tmp/sse_output.txt
```

2. **이벤트 파싱 및 검증**:
```python
# test_sse_schema.py
import json
import re

def parse_sse_events(file_path):
    """SSE 이벤트 파싱"""
    with open(file_path, 'r') as f:
        content = f.read()
    
    events = []
    lines = content.split('\n')
    
    current_event = {}
    for line in lines:
        if line.startswith('id: '):
            current_event['id'] = line[4:]
        elif line.startswith('event: '):
            current_event['type'] = line[7:]
        elif line.startswith('data: '):
            data = line[6:]
            if data == '[DONE]':
                events.append({'type': 'done', 'data': '[DONE]'})
                break
            try:
                current_event['data'] = json.loads(data)
                events.append(current_event.copy())
                current_event = {}
            except json.JSONDecodeError:
                print(f"JSON 파싱 오류: {data}")
    
    return events

def validate_event_schema(event):
    """이벤트 스키마 검증"""
    event_type = event.get('type')
    data = event.get('data', {})
    
    # 공통 필드 검증
    assert 'type' in data, f"{event_type} 이벤트에 'type' 필드 없음"
    assert 'timestamp' in data, f"{event_type} 이벤트에 'timestamp' 필드 없음"
    assert isinstance(data['timestamp'], int), f"{event_type} 이벤트의 'timestamp'가 정수가 아님"
    
    # 이벤트 타입별 검증
    if event_type == 'thought':
        assert 'thoughtType' in data, "'thought' 이벤트에 'thoughtType' 필드 없음"
        assert 'content' in data, "'thought' 이벤트에 'content' 필드 없음"
        assert data['thoughtType'] in ['analysis', 'planning', 'reasoning', 'decision', 'reflection']
    
    elif event_type == 'plan_step':
        assert 'stepId' in data, "'plan_step' 이벤트에 'stepId' 필드 없음"
        assert 'description' in data, "'plan_step' 이벤트에 'description' 필드 없음"
        assert 'status' in data, "'plan_step' 이벤트에 'status' 필드 없음"
        assert 'confidence' in data, "'plan_step' 이벤트에 'confidence' 필드 없음"
        assert 0.0 <= data['confidence'] <= 1.0, "'confidence' 값이 0.0~1.0 범위를 벗어남"
    
    elif event_type == 'tool_execution':
        assert 'toolName' in data, "'tool_execution' 이벤트에 'toolName' 필드 없음"
        assert 'status' in data, "'tool_execution' 이벤트에 'status' 필드 없음"
        assert 'requiresApproval' in data, "'tool_execution' 이벤트에 'requiresApproval' 필드 없음"
    
    elif event_type == 'hitl':
        assert 'requestId' in data, "'hitl' 이벤트에 'requestId' 필드 없음"
        assert 'actionType' in data, "'hitl' 이벤트에 'actionType' 필드 없음"
        assert 'message' in data, "'hitl' 이벤트에 'message' 필드 없음"
    
    elif event_type == 'content':
        assert 'content' in data, "'content' 이벤트에 'content' 필드 없음"
    
    print(f"✅ {event_type} 이벤트 스키마 검증 통과")

# 실행
events = parse_sse_events('/tmp/sse_output.txt')
for event in events:
    if event.get('type') != 'done':
        validate_event_schema(event)
```

3. **검증 사항**:
   - ✅ 모든 이벤트에 `id:` 라인 포함
   - ✅ 모든 이벤트에 `event:` 라인 포함
   - ✅ 모든 이벤트에 `data:` 라인 포함 (JSON 형식)
   - ✅ 필수 필드 모두 포함
   - ✅ 데이터 타입 정확성 (timestamp는 정수, confidence는 0.0~1.0)

---

### 시나리오 2: LangGraph Interrupt 검증

**목적**: HITL 이벤트 발행 시 작업이 즉시 중단되고 체크포인트가 저장되는지 확인

**테스트 단계**:

1. **승인이 필요한 작업 요청**:
```bash
curl -N -X POST http://localhost:9000/aura/test/stream \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Tenant-ID: ${TENANT_ID}" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "GitHub PR을 생성해주세요",
    "context": {}
  }' > /tmp/hitl_test.txt &
SSE_PID=$!
```

2. **HITL 이벤트 대기**:
```bash
# HITL 이벤트 확인
timeout 30 tail -f /tmp/hitl_test.txt | grep "event: hitl"
```

3. **Redis 체크포인트 확인**:
```python
# test_checkpoint.py
import redis
import json

r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

# 체크포인트 키 패턴 검색
keys = r.keys('checkpoint:*')
print(f"체크포인트 키 개수: {len(keys)}")

# 최신 체크포인트 확인
for key in keys[:5]:  # 최근 5개만 확인
    value = r.get(key)
    if value:
        checkpoint = json.loads(value)
        print(f"\n체크포인트 키: {key}")
        print(f"pending_approvals: {checkpoint.get('pending_approvals', [])}")
        print(f"messages 개수: {len(checkpoint.get('messages', []))}")
```

4. **Aura-Platform 로그 확인**:
```bash
# HITL Interrupt 로그 확인
grep "HITL Interrupt" /tmp/aura-platform.log

# 체크포인트 저장 로그 확인
grep "checkpoint" /tmp/aura-platform.log | tail -10
```

5. **검증 사항**:
   - ✅ HITL 이벤트 발행 후 스트림이 즉시 중단됨
   - ✅ Redis에 체크포인트가 저장됨
   - ✅ `pending_approvals` 상태가 정확히 기록됨
   - ✅ 중단 시점의 메시지 히스토리가 보존됨

---

### 시나리오 3: 승인 신호 대기 및 재개 검증

**목적**: Redis Pub/Sub을 통한 승인 신호 수신 및 작업 재개 확인

**테스트 단계**:

1. **HITL 요청 생성 및 request_id 추출**:
```bash
# SSE 스트림 시작
curl -N -X POST http://localhost:9000/aura/test/stream \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Tenant-ID: ${TENANT_ID}" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "GitHub PR을 생성해주세요",
    "context": {}
  }' > /tmp/approval_test.txt &
SSE_PID=$!

# HITL 이벤트에서 request_id 추출
sleep 5
REQUEST_ID=$(grep -o '"requestId":"[^"]*"' /tmp/approval_test.txt | head -1 | cut -d'"' -f4)
SESSION_ID=$(grep -o '"sessionId":"[^"]*"' /tmp/approval_test.txt | head -1 | cut -d'"' -f4)

echo "Request ID: ${REQUEST_ID}"
echo "Session ID: ${SESSION_ID}"
```

2. **Redis Pub/Sub 채널 확인**:
```bash
# Redis에서 채널 확인
redis-cli PUBSUB CHANNELS "hitl:channel:*"

# 승인 신호 발행 (백엔드 API 호출 시뮬레이션)
redis-cli PUBLISH "hitl:channel:${SESSION_ID}" '{"type":"approval","requestId":"'${REQUEST_ID}'","timestamp":'$(date +%s)'}'
```

3. **승인 신호 저장 확인**:
```python
# test_approval_signal.py
import redis
import json
import time

r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

session_id = "session_user123_1706149260"
signal_key = f"hitl:signal:{session_id}"

# 승인 신호 확인
signal = r.get(signal_key)
if signal:
    signal_data = json.loads(signal)
    print(f"승인 신호: {json.dumps(signal_data, indent=2, ensure_ascii=False)}")
    assert signal_data['type'] == 'approval', "승인 신호 타입이 올바르지 않음"
    assert 'timestamp' in signal_data, "타임스탬프가 없음"
    print("✅ 승인 신호 저장 확인")
else:
    print("❌ 승인 신호가 저장되지 않음")
```

4. **작업 재개 확인**:
```bash
# SSE 스트림이 재개되는지 확인
tail -f /tmp/approval_test.txt | grep -E "event: (content|end|error)"
```

5. **검증 사항**:
   - ✅ Redis Pub/Sub 채널 구독 정상 작동
   - ✅ 승인 신호 수신 시 작업 재개
   - ✅ 중단된 노드부터 정확히 재개
   - ✅ 거절 신호 수신 시 적절한 에러 처리
   - ✅ 타임아웃(300초) 처리 정상 작동

---

### 시나리오 4: Context 활용 검증

**목적**: 요청 본문의 context 데이터가 시스템 프롬프트에 동적으로 반영되는지 확인

**테스트 단계**:

1. **Context 포함 요청**:
```bash
curl -N -X POST http://localhost:9000/aura/test/stream \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Tenant-ID: ${TENANT_ID}" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "현재 화면에서 선택된 항목들을 분석해주세요",
    "context": {
      "activeApp": "mail",
      "selectedItemIds": [1, 2, 3],
      "url": "http://localhost:4200/mail",
      "path": "/mail",
      "title": "메일 인박스",
      "itemId": "msg-123",
      "metadata": {
        "folder": "inbox",
        "unreadCount": 5
      }
    }
  }' > /tmp/context_test.txt
```

2. **시스템 프롬프트 확인** (로깅 활성화):
```python
# core/llm/prompts.py에 로깅 추가 후 확인
# 또는 직접 테스트
from core.llm.prompts import get_system_prompt

context = {
    "activeApp": "mail",
    "selectedItemIds": [1, 2, 3],
    "url": "http://localhost:4200/mail",
    "path": "/mail",
    "title": "메일 인박스",
    "itemId": "msg-123",
    "metadata": {
        "folder": "inbox",
        "unreadCount": 5
    }
}

prompt = get_system_prompt("dev", context=context)
print(prompt)

# 검증: context 정보가 프롬프트에 포함되어 있는지 확인
assert "현재 사용자가 보고 있는 화면: mail" in prompt
assert "선택된 항목 ID: 1, 2, 3" in prompt
assert "현재 URL: http://localhost:4200/mail" in prompt
assert "경로: /mail" in prompt
assert "페이지 제목: 메일 인박스" in prompt
assert "항목 ID: msg-123" in prompt
```

3. **에이전트 응답 확인**:
```bash
# thought 이벤트에서 context 정보 언급 확인
grep -A 5 "event: thought" /tmp/context_test.txt | grep -i "mail\|선택\|항목"
```

4. **검증 사항**:
   - ✅ `activeApp`이 시스템 프롬프트에 반영됨
   - ✅ `selectedItemIds`가 시스템 프롬프트에 반영됨
   - ✅ `url`, `path`, `title`, `itemId`가 시스템 프롬프트에 반영됨
   - ✅ `metadata`가 시스템 프롬프트에 반영됨
   - ✅ 에이전트 응답에 context 정보가 반영됨

---

### 시나리오 5: 종료 플래그 검증

**목적**: 모든 작업 완료 시 `data: [DONE]`이 명확히 전송되는지 확인

**테스트 단계**:

1. **정상 완료 시나리오**:
```bash
curl -N -X POST http://localhost:9000/aura/test/stream \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Tenant-ID: ${TENANT_ID}" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "안녕하세요",
    "context": {}
  }' > /tmp/normal_completion.txt

# 종료 플래그 확인
tail -5 /tmp/normal_completion.txt | grep "data: \[DONE\]"
```

2. **에러 발생 시나리오**:
```bash
# 잘못된 요청으로 에러 유발
curl -N -X POST http://localhost:9000/aura/test/stream \
  -H "Authorization: Bearer invalid_token" \
  -H "X-Tenant-ID: ${TENANT_ID}" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "test",
    "context": {}
  }' > /tmp/error_completion.txt

# 종료 플래그 확인 (에러 후에도 전송되어야 함)
tail -5 /tmp/error_completion.txt
```

3. **HITL 타임아웃 시나리오**:
```bash
# HITL 요청 생성 후 승인하지 않음
curl -N -X POST http://localhost:9000/aura/test/stream \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-Tenant-ID: ${TENANT_ID}" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "GitHub PR을 생성해주세요",
    "context": {}
  }' > /tmp/timeout_completion.txt &

# 300초 대기 (또는 타임아웃 시간 조정)
sleep 300

# 종료 플래그 확인
tail -5 /tmp/timeout_completion.txt | grep "data: \[DONE\]"
```

4. **검증 사항**:
   - ✅ 정상 완료 시 `data: [DONE]\n\n` 전송
   - ✅ 에러 발생 시에도 `data: [DONE]\n\n` 전송
   - ✅ HITL 타임아웃 시 `data: [DONE]\n\n` 전송
   - ✅ 종료 플래그는 항상 스트림의 마지막에 위치

---

## 검증 방법

### 자동화된 테스트 스크립트

```python
# scripts/test_aura_internal.py
"""
Aura-Platform 내부 동작 검증 스크립트
"""

import asyncio
import json
import sys
from pathlib import Path

# 테스트 함수들
async def test_sse_schema():
    """SSE 이벤트 스키마 검증"""
    # 구현...
    pass

async def test_langgraph_interrupt():
    """LangGraph Interrupt 검증"""
    # 구현...
    pass

async def test_approval_signal():
    """승인 신호 대기 및 재개 검증"""
    # 구현...
    pass

async def test_context_usage():
    """Context 활용 검증"""
    # 구현...
    pass

async def test_completion_flag():
    """종료 플래그 검증"""
    # 구현...
    pass

async def main():
    """모든 테스트 실행"""
    tests = [
        ("SSE 이벤트 스키마", test_sse_schema),
        ("LangGraph Interrupt", test_langgraph_interrupt),
        ("승인 신호 대기", test_approval_signal),
        ("Context 활용", test_context_usage),
        ("종료 플래그", test_completion_flag),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            await test_func()
            results.append((name, True, None))
            print(f"✅ {name}: 통과")
        except Exception as e:
            results.append((name, False, str(e)))
            print(f"❌ {name}: 실패 - {e}")
    
    # 결과 요약
    passed = sum(1 for _, success, _ in results if success)
    total = len(results)
    print(f"\n테스트 결과: {passed}/{total} 통과")
    
    if passed < total:
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 문제 해결 가이드

### 문제 1: SSE 이벤트 스키마 불일치

**증상**: 프론트엔드에서 이벤트 파싱 오류

**해결 방법**:
1. `api/schemas/events.py`에서 스키마 정의 확인
2. `domains/dev/agents/hooks.py`에서 이벤트 생성 로직 확인
3. 실제 발행된 이벤트와 스키마 비교

### 문제 2: LangGraph Interrupt가 작동하지 않음

**증상**: HITL 이벤트 발행 후에도 작업이 계속 진행됨

**해결 방법**:
1. `domains/dev/agents/enhanced_agent.py`의 `_tools_node` 확인
2. `APPROVAL_REQUIRED_TOOLS` 목록 확인
3. `pending_approvals` 상태 업데이트 확인
4. Redis 체크포인트 저장 확인

### 문제 3: 승인 신호를 받지 못함

**증상**: 승인 API 호출 후에도 작업이 재개되지 않음

**해결 방법**:
1. Redis Pub/Sub 채널 구독 확인
2. `core/memory/hitl_manager.py`의 `wait_for_approval_signal` 확인
3. Redis 채널 이름 일치 확인 (`hitl:channel:{sessionId}`)
4. 신호 형식 확인 (Unix timestamp 포함)

### 문제 4: Context가 프롬프트에 반영되지 않음

**증상**: 에이전트 응답에 context 정보가 없음

**해결 방법**:
1. `core/llm/prompts.py`의 `get_system_prompt` 확인
2. Context 파싱 로직 확인
3. 시스템 프롬프트 로깅으로 실제 반영 여부 확인

### 문제 5: 종료 플래그가 전송되지 않음

**증상**: 스트림이 종료되지만 `data: [DONE]`이 없음

**해결 방법**:
1. `api/routes/aura_backend.py`의 `event_generator` 확인
2. 모든 종료 경로에서 `data: [DONE]` 전송 확인
3. 예외 처리 경로에서도 종료 플래그 전송 확인

---

## 테스트 결과 기록

### 테스트 결과 템플릿

```markdown
## Aura-Platform 내부 테스트 결과

**테스트 일시**: YYYY-MM-DD HH:MM:SS
**테스트 담당자**: [이름]
**Aura-Platform 버전**: v0.3.3

### 테스트 항목별 결과

#### 1. SSE 이벤트 스키마 준수
- [ ] 통과
- [ ] 실패 (상세: ___________)

#### 2. LangGraph Interrupt
- [ ] 통과
- [ ] 실패 (상세: ___________)

#### 3. 승인 신호 대기 및 재개
- [ ] 통과
- [ ] 실패 (상세: ___________)

#### 4. Context 활용
- [ ] 통과
- [ ] 실패 (상세: ___________)

#### 5. 종료 플래그
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

- **구현 파일**:
  - `api/routes/aura_backend.py`: SSE 스트리밍 엔드포인트
  - `domains/dev/agents/enhanced_agent.py`: Enhanced Agent 구현
  - `domains/dev/agents/hooks.py`: SSE 이벤트 Hook
  - `core/llm/prompts.py`: 시스템 프롬프트 생성
  - `core/memory/hitl_manager.py`: HITL Manager
  - `api/schemas/events.py`: 이벤트 스키마 정의

- **관련 문서**:
  - `docs/FRONTEND_V1_SPEC.md`: 프론트엔드 명세 v1.0
  - `docs/BACKEND_INTEGRATION_TEST.md`: 백엔드 통합 테스트
  - `docs/FRONTEND_INTEGRATION_TEST.md`: 프론트엔드 통합 테스트

---

**문서 버전**: v1.0  
**최종 업데이트**: 2026-01-16  
**담당자**: Aura-Platform 개발팀
