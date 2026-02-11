#!/usr/bin/env python3
"""
Aura 스트림 직접 확인 (BE 경유 없이)

1. 트리거 POST → runId 획득
2. GET stream?runId=... 연결 후 수신 데이터 출력
"""
import asyncio
import sys
import time
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 기본 Aura 주소 (서버 기동 포트)
BASE = "http://127.0.0.1:9000"


async def main() -> None:
    try:
        from core.security import create_token
    except Exception as e:
        print(f"Import error: {e}")
        sys.exit(1)

    token = create_token(user_id="stream-test", tenant_id="1", role="user")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Tenant-ID": "1",
    }
    run_id = f"aura-direct-test-{time.time():.0f}"
    case_id = "85116"

    import httpx

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1) 트리거
        r = await client.post(
            f"{BASE}/aura/cases/{case_id}/analysis-runs",
            headers=headers,
            json={"runId": run_id, "caseId": case_id},
        )
        if r.status_code != 202:
            print(f"Trigger failed: {r.status_code} - {r.text[:300]}")
            sys.exit(1)
        body = r.json()
        print(f"Trigger 202 OK runId={body.get('runId', run_id)}")
        print()

        # 2) 스트림 연결 (동일 runId)
        stream_url = f"{BASE}/aura/cases/{case_id}/analysis/stream?runId={run_id}"
        print(f"Connecting to {stream_url} ...")
        print("--- stream output ---")
        total_bytes = 0
        async with client.stream("GET", stream_url, headers={**headers, "Accept": "text/event-stream"}) as resp:
            if resp.status_code != 200:
                print(f"Stream failed: {resp.status_code} - {await resp.aread()}")
                sys.exit(1)
            async for chunk in resp.aiter_bytes():
                total_bytes += len(chunk)
                text = chunk.decode("utf-8", errors="replace")
                print(text, end="", flush=True)
        print("--- end stream ---")
        print(f"Total bytes received: {total_bytes}")
        if total_bytes == 0:
            print("FAIL: 0 bytes (Aura sent no SSE data)")
            sys.exit(1)
        print("OK: Aura stream sent data.")


if __name__ == "__main__":
    asyncio.run(main())
