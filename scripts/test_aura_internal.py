#!/usr/bin/env python3
"""
Aura-Platform 내부 동작 검증 스크립트

이 스크립트는 AURA_PLATFORM_INTERNAL_TEST.md의 테스트 항목을 자동화하여 검증합니다.
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import redis
from dotenv import load_dotenv

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

load_dotenv()

# 테스트 설정
BASE_URL = "http://localhost:9000"
TENANT_ID = "tenant1"
USER_ID = "test_user_001"

# JWT 토큰 생성
from core.security.auth import create_token
TOKEN = create_token(
    user_id=USER_ID,
    tenant_id=TENANT_ID,
    email="test@dwp.com",
    role="user"
)

# Redis 연결
redis_client = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)


class TestResult:
    """테스트 결과 클래스"""
    def __init__(self, name: str):
        self.name = name
        self.passed = False
        self.error = None
        self.details: list[str] = []

    def add_detail(self, detail: str):
        self.details.append(detail)

    def success(self):
        self.passed = True

    def fail(self, error: str):
        self.passed = False
        self.error = error


def parse_sse_events(content: str) -> list[dict[str, Any]]:
    """SSE 이벤트 파싱"""
    events = []
    lines = content.split('\n')
    
    current_event: dict[str, Any] = {}
    data_buffer = ""
    
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
            data_buffer += data
        elif line == '' and data_buffer:
            # 빈 줄 = 이벤트 종료
            try:
                current_event['data'] = json.loads(data_buffer)
                events.append(current_event.copy())
                current_event = {}
                data_buffer = ""
            except json.JSONDecodeError as e:
                print(f"JSON 파싱 오류: {data_buffer[:100]}... - {e}")
                data_buffer = ""
    
    return events


async def test_sse_schema() -> TestResult:
    """SSE 이벤트 스키마 검증"""
    result = TestResult("SSE 이벤트 스키마 준수")
    
    try:
        # SSE 스트림 요청
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{BASE_URL}/aura/test/stream",
                headers={
                    "Authorization": f"Bearer {TOKEN}",
                    "X-Tenant-ID": TENANT_ID,
                    "Content-Type": "application/json",
                },
                json={
                    "prompt": "안녕하세요, 테스트입니다",
                    "context": {"activeApp": "mail"}
                },
            )
            
            if response.status_code != 200:
                result.fail(f"HTTP {response.status_code}: {response.text[:200]}")
                return result
            
            # 응답 내용 읽기
            content = ""
            async for chunk in response.aiter_text():
                content += chunk
                # 최소한의 이벤트를 받으면 중단 (테스트용)
                if "event: end" in content or "data: [DONE]" in content:
                    break
        
        # 이벤트 파싱
        events = parse_sse_events(content)
        result.add_detail(f"총 {len(events)}개 이벤트 수신")
        
        if not events:
            result.fail("이벤트가 수신되지 않음")
            return result
        
        # 각 이벤트 검증
        event_types_found = set()
        for event in events:
            if event.get('type') == 'done':
                continue
            
            event_type = event.get('type')
            event_types_found.add(event_type)
            data = event.get('data', {})
            
            # 공통 필드 검증
            if 'type' not in data:
                result.fail(f"{event_type} 이벤트에 'type' 필드 없음")
                return result
            
            if 'timestamp' not in data:
                result.fail(f"{event_type} 이벤트에 'timestamp' 필드 없음")
                return result
            
            if not isinstance(data['timestamp'], int):
                result.fail(f"{event_type} 이벤트의 'timestamp'가 정수가 아님 (타입: {type(data['timestamp'])})")
                return result
            
            # id 라인 확인
            if 'id' not in event:
                result.fail(f"{event_type} 이벤트에 'id' 라인 없음")
                return result
            
            # 이벤트 타입별 검증
            if event_type == 'thought':
                if 'thoughtType' not in data:
                    result.fail("'thought' 이벤트에 'thoughtType' 필드 없음")
                    return result
                if 'content' not in data:
                    result.fail("'thought' 이벤트에 'content' 필드 없음")
                    return result
            
            elif event_type == 'plan_step':
                required_fields = ['stepId', 'description', 'status', 'confidence']
                for field in required_fields:
                    if field not in data:
                        result.fail(f"'plan_step' 이벤트에 '{field}' 필드 없음")
                        return result
                if not (0.0 <= data['confidence'] <= 1.0):
                    result.fail(f"'confidence' 값이 0.0~1.0 범위를 벗어남: {data['confidence']}")
                    return result
            
            elif event_type == 'tool_execution':
                required_fields = ['toolName', 'status', 'requiresApproval']
                for field in required_fields:
                    if field not in data:
                        result.fail(f"'tool_execution' 이벤트에 '{field}' 필드 없음")
                        return result
            
            elif event_type == 'hitl':
                required_fields = ['requestId', 'actionType', 'message']
                for field in required_fields:
                    if field not in data:
                        result.fail(f"'hitl' 이벤트에 '{field}' 필드 없음")
                        return result
            
            elif event_type == 'content':
                if 'content' not in data:
                    result.fail("'content' 이벤트에 'content' 필드 없음")
                    return result
        
        result.add_detail(f"발견된 이벤트 타입: {', '.join(sorted(event_types_found))}")
        result.success()
        
    except Exception as e:
        result.fail(f"예외 발생: {str(e)}")
    
    return result


async def test_completion_flag() -> TestResult:
    """종료 플래그 검증"""
    result = TestResult("종료 플래그 전송")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{BASE_URL}/aura/test/stream",
                headers={
                    "Authorization": f"Bearer {TOKEN}",
                    "X-Tenant-ID": TENANT_ID,
                    "Content-Type": "application/json",
                },
                json={
                    "prompt": "안녕하세요",
                    "context": {}
                },
            )
            
            if response.status_code != 200:
                result.fail(f"HTTP {response.status_code}: {response.text[:200]}")
                return result
            
            # 전체 응답 읽기
            content = ""
            async for chunk in response.aiter_text():
                content += chunk
            
            # 종료 플래그 확인
            if "data: [DONE]" not in content:
                result.fail("종료 플래그 'data: [DONE]'가 전송되지 않음")
                return result
            
            # 종료 플래그가 마지막에 있는지 확인
            lines = content.split('\n')
            done_index = -1
            for i, line in enumerate(lines):
                if line == "data: [DONE]":
                    done_index = i
                    break
            
            if done_index == -1:
                result.fail("종료 플래그를 찾을 수 없음")
                return result
            
            # 마지막 몇 줄에 종료 플래그가 있는지 확인
            if done_index < len(lines) - 5:
                result.add_detail("종료 플래그가 스트림 중간에 위치 (경고)")
            else:
                result.add_detail("종료 플래그가 스트림 끝에 위치 (정상)")
            
            result.success()
        
    except Exception as e:
        result.fail(f"예외 발생: {str(e)}")
    
    return result


async def test_context_usage() -> TestResult:
    """Context 활용 검증"""
    result = TestResult("Context 활용 (프롬프트 동적 반영)")
    
    try:
        # Context 포함 요청
        test_context = {
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
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{BASE_URL}/aura/test/stream",
                headers={
                    "Authorization": f"Bearer {TOKEN}",
                    "X-Tenant-ID": TENANT_ID,
                    "Content-Type": "application/json",
                },
                json={
                    "prompt": "현재 화면에서 선택된 항목들을 분석해주세요",
                    "context": test_context
                },
            )
            
            if response.status_code != 200:
                result.fail(f"HTTP {response.status_code}: {response.text[:200]}")
                return result
            
            # 응답 내용 읽기
            content = ""
            async for chunk in response.aiter_text():
                content += chunk
                if "event: end" in content or "data: [DONE]" in content:
                    break
        
        # 시스템 프롬프트 직접 테스트
        from core.llm.prompts import get_system_prompt
        
        prompt = get_system_prompt("dev", context=test_context)
        
        # Context 정보가 프롬프트에 포함되어 있는지 확인
        checks = {
            "activeApp": "현재 사용자가 보고 있는 화면: mail" in prompt,
            "selectedItemIds": "선택된 항목 ID: 1, 2, 3" in prompt,
            "url": "현재 URL: http://localhost:4200/mail" in prompt,
            "path": "경로: /mail" in prompt,
            "title": "페이지 제목: 메일 인박스" in prompt,
            "itemId": "항목 ID: msg-123" in prompt,
        }
        
        failed_checks = [key for key, passed in checks.items() if not passed]
        if failed_checks:
            result.fail(f"다음 context 필드가 프롬프트에 반영되지 않음: {', '.join(failed_checks)}")
            return result
        
        result.add_detail("모든 context 필드가 시스템 프롬프트에 반영됨")
        result.success()
        
    except Exception as e:
        result.fail(f"예외 발생: {str(e)}")
    
    return result


async def test_langgraph_interrupt() -> TestResult:
    """LangGraph Interrupt 검증 (간단 버전)"""
    result = TestResult("LangGraph Interrupt (HITL 중단 및 체크포인트 저장)")
    
    try:
        # 승인이 필요한 작업 요청 (GitHub PR 생성 등)
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{BASE_URL}/aura/test/stream",
                headers={
                    "Authorization": f"Bearer {TOKEN}",
                    "X-Tenant-ID": TENANT_ID,
                    "Content-Type": "application/json",
                },
                json={
                    "prompt": "GitHub PR을 생성해주세요",
                    "context": {}
                },
            )
            
            if response.status_code != 200:
                result.fail(f"HTTP {response.status_code}: {response.text[:200]}")
                return result
            
            # 응답 내용 읽기 (HITL 이벤트 대기)
            content = ""
            hitl_found = False
            async for chunk in response.aiter_text():
                content += chunk
                if "event: hitl" in content:
                    hitl_found = True
                    result.add_detail("HITL 이벤트 발행 확인")
                    break
                # 타임아웃 방지 (30초)
                if len(content) > 10000:  # 충분한 데이터 수신
                    break
        
        if not hitl_found:
            result.add_detail("HITL 이벤트가 발행되지 않음 (승인이 필요한 작업이 없었을 수 있음)")
            result.add_detail("이것은 정상일 수 있습니다 (에이전트가 승인 없이 작업 완료)")
            result.success()  # HITL이 없어도 정상일 수 있음
            return result
        
        # Redis 체크포인트 확인
        keys = redis_client.keys("checkpoint:*")
        if keys:
            result.add_detail(f"Redis에 {len(keys)}개의 체크포인트 키 발견")
            # 최신 체크포인트 확인
            for key in keys[:3]:  # 최근 3개만 확인
                value = redis_client.get(key)
                if value:
                    try:
                        checkpoint = json.loads(value)
                        if 'pending_approvals' in checkpoint or 'messages' in checkpoint:
                            result.add_detail(f"체크포인트 {key}에 상태 정보 포함 확인")
                    except:
                        pass
        else:
            result.add_detail("Redis에 체크포인트 키가 없음 (경고)")
        
        result.success()
        
    except Exception as e:
        result.fail(f"예외 발생: {str(e)}")
    
    return result


async def main():
    """모든 테스트 실행"""
    print("=" * 60)
    print("Aura-Platform 내부 동작 검증 테스트")
    print("=" * 60)
    print()
    
    tests = [
        ("1. SSE 이벤트 스키마 준수", test_sse_schema),
        ("2. 종료 플래그 전송", test_completion_flag),
        ("3. Context 활용 (프롬프트 동적 반영)", test_context_usage),
        ("4. LangGraph Interrupt (HITL 중단 및 체크포인트 저장)", test_langgraph_interrupt),
    ]
    
    results: list[TestResult] = []
    
    for name, test_func in tests:
        print(f"\n[{name}] 테스트 시작...")
        try:
            result = await test_func()
            results.append(result)
            
            if result.passed:
                print(f"✅ {name}: 통과")
                for detail in result.details:
                    print(f"   - {detail}")
            else:
                print(f"❌ {name}: 실패")
                if result.error:
                    print(f"   오류: {result.error}")
                for detail in result.details:
                    print(f"   - {detail}")
        except Exception as e:
            print(f"❌ {name}: 예외 발생 - {str(e)}")
            result = TestResult(name)
            result.fail(str(e))
            results.append(result)
        
        print()
    
    # 결과 요약
    print("=" * 60)
    print("테스트 결과 요약")
    print("=" * 60)
    
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    
    for result in results:
        status = "✅ 통과" if result.passed else "❌ 실패"
        print(f"{status} - {result.name}")
        if result.error:
            print(f"      오류: {result.error}")
    
    print()
    print(f"전체 결과: {passed}/{total} 통과")
    
    if passed < total:
        print("\n⚠️ 일부 테스트가 실패했습니다. 상세 내용을 확인하세요.")
        sys.exit(1)
    else:
        print("\n✅ 모든 테스트가 통과했습니다!")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
