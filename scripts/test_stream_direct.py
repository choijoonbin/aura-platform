#!/usr/bin/env python3
"""
Aura 스트림 엔드포인트 직접 검증 스크립트

BE 없이 Aura의 스트림이 정상 동작하는지 확인합니다.
트리거 → 스트림 연결 → 모든 이벤트 수신 확인
"""

import asyncio
import json
import sys
from datetime import datetime

import httpx


AURA_BASE = "http://localhost:9000"
CASE_ID = "85115"  # 테스트용 케이스 ID
AUTH_TOKEN = "Bearer test-token"  # 실제 토큰으로 교체 필요


async def trigger_analysis():
    """분석 트리거 (POST /aura/cases/{caseId}/analysis-runs)"""
    url = f"{AURA_BASE}/aura/cases/{CASE_ID}/analysis-runs"
    headers = {"Authorization": AUTH_TOKEN}
    
    print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] 📤 POST {url}")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, headers=headers, json={})
        
        if response.status_code != 202:
            print(f"❌ 트리거 실패: {response.status_code}")
            print(response.text)
            sys.exit(1)
        
        data = response.json()
        run_id = data.get("runId")
        stream_path = data.get("streamPath", "")
        
        print(f"✅ 트리거 성공: runId={run_id}")
        print(f"   streamPath={stream_path}")
        return run_id


async def consume_stream(run_id: str):
    """스트림 소비 (GET /aura/cases/{caseId}/analysis/stream?runId=...)"""
    url = f"{AURA_BASE}/aura/cases/{CASE_ID}/analysis/stream?runId={run_id}"
    headers = {"Authorization": AUTH_TOKEN}
    
    print(f"\n[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] 📡 GET {url}")
    print("=" * 80)
    
    event_count = 0
    bytes_received = 0
    events_by_type = {}
    
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, read=300.0)) as client:
            async with client.stream("GET", url, headers=headers) as response:
                if response.status_code != 200:
                    print(f"❌ 스트림 연결 실패: {response.status_code}")
                    print(await response.aread())
                    return
                
                print(f"✅ 스트림 연결 성공 (200 OK)")
                print(f"   Content-Type: {response.headers.get('content-type')}")
                print(f"   Connection: {response.headers.get('connection')}")
                print("-" * 80)
                
                current_event = None
                
                async for line in response.aiter_lines():
                    bytes_received += len(line.encode('utf-8')) + 1  # +1 for \n
                    
                    # SSE 파싱
                    if line.startswith(":"):
                        # 주석 라인
                        print(f"💬 {line}")
                        continue
                    
                    if line.startswith("event:"):
                        current_event = line[6:].strip()
                        events_by_type[current_event] = events_by_type.get(current_event, 0) + 1
                        continue
                    
                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        event_count += 1
                        
                        if data_str == "[DONE]":
                            print(f"🏁 [DONE] 수신 - 스트림 종료")
                            break
                        
                        try:
                            data = json.loads(data_str)
                            event_type = current_event or "message"
                            
                            # 이벤트 출력
                            timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
                            print(f"[{timestamp}] 📨 event: {event_type}")
                            
                            # 주요 필드만 표시
                            if "status" in data:
                                print(f"   └─ status: {data['status']}")
                            if "runId" in data:
                                print(f"   └─ runId: {data['runId']}")
                            if "stepName" in data:
                                print(f"   └─ step: {data['stepName']}")
                            if "score" in data:
                                print(f"   └─ score: {data['score']}")
                            if "message" in data and event_type == "message":
                                print(f"   └─ message: {data['message']}")
                            
                        except json.JSONDecodeError as e:
                            print(f"⚠️  JSON 파싱 실패: {data_str[:100]}")
                        
                        current_event = None
                    
                    if not line:
                        # 빈 줄 (이벤트 구분)
                        continue
    
    except asyncio.TimeoutError:
        print(f"\n⏱️  타임아웃 (300초)")
    except Exception as e:
        print(f"\n❌ 스트림 에러: {e}")
        import traceback
        traceback.print_exc()
    
    print("=" * 80)
    print(f"\n📊 통계:")
    print(f"   총 이벤트: {event_count}개")
    print(f"   수신 바이트: {bytes_received} bytes")
    print(f"   이벤트 타입별:")
    for event_type, count in sorted(events_by_type.items()):
        print(f"     - {event_type}: {count}개")


async def main():
    """메인 실행"""
    print("=" * 80)
    print("🧪 Aura 스트림 직접 검증")
    print("=" * 80)
    print(f"Base URL: {AURA_BASE}")
    print(f"Case ID: {CASE_ID}")
    print()
    
    # 1. 트리거
    run_id = await trigger_analysis()
    
    # 2. 약간 대기 (백그라운드 분석 시작 시간 확보)
    await asyncio.sleep(0.5)
    
    # 3. 스트림 소비
    await consume_stream(run_id)
    
    print("\n✅ 검증 완료")


if __name__ == "__main__":
    asyncio.run(main())
