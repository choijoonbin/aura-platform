#!/usr/bin/env python3
"""
Agent Stream 샘플 이벤트 시드 (Prompt C)

최소 20건 샘플 이벤트를 생성하여 Synapse POST /api/synapse/agent/events로 push.
대시보드 시각 확인용.

Usage:
  python scripts/seed_agent_stream_events.py
  python scripts/seed_agent_stream_events.py --dry-run   # push 없이 로컬 출력만
  python scripts/seed_agent_stream_events.py --count 25 # 25건 생성
"""

import argparse
import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def _make_sample_events(count: int = 20) -> list:
    """20건 이상 샘플 AgentEvent 생성"""
    from core.agent_stream.schemas import AgentEvent, AgentStreamStage

    stages = [
        (AgentStreamStage.SCAN, "케이스 목표 및 컨텍스트 분석을 시작합니다."),
        (AgentStreamStage.SCAN, "스캔 완료: 3건 처리, 1.2초 소요"),
        (AgentStreamStage.DETECT, "Detection found: DUPLICATE_INVOICE (score: 0.85)"),
        (AgentStreamStage.DETECT, "Detection found: VENDOR_RISK (score: 0.62)"),
        (AgentStreamStage.ANALYZE, "RAG queried: 5 docs, topK=10, 120ms"),
        (AgentStreamStage.ANALYZE, "Reasoning composed for case: case-001"),
        (AgentStreamStage.SIMULATE, "Simulation PASS: sim_case-001_write_off_abc123"),
        (AgentStreamStage.SIMULATE, "Simulation FAIL: sim_case-002_clear_def456"),
        (AgentStreamStage.EXECUTE, "Action proposed: prop_case-001_write_off_xyz789 (requiresApproval=true)"),
        (AgentStreamStage.EXECUTE, "Action approved: req_abc123"),
        (AgentStreamStage.EXECUTE, "Action executed: prop_case-001_write_off_xyz789 (SUCCESS)"),
        (AgentStreamStage.EXECUTE, "SAP write success: SAP-REF-2026-0001"),
        (AgentStreamStage.EXECUTE, "Action failed: prop_case-002_clear_ghi012 - Connection timeout"),
        (AgentStreamStage.SCAN, "새 스캔 시작: tenant 200000"),
        (AgentStreamStage.DETECT, "Detection found: CASH_FLOW_ANOMALY (score: 0.91)"),
        (AgentStreamStage.ANALYZE, "RAG queried: 8 docs, topK=5, 95ms"),
        (AgentStreamStage.SIMULATE, "Simulation PASS: sim_case-003_adjust_jkl345"),
        (AgentStreamStage.EXECUTE, "Action proposed: prop_case-003_adjust_mno678 (requiresApproval=true)"),
        (AgentStreamStage.EXECUTE, "Action executed: prop_case-003_adjust_mno678 (SUCCESS)"),
        (AgentStreamStage.EXECUTE, "SAP write success: SAP-REF-2026-0002"),
    ]

    base_time = datetime.now(timezone.utc) - timedelta(hours=5)
    events = []
    for i in range(count):
        stage_info = stages[i % len(stages)]
        stage, message = stage_info
        ts = base_time + timedelta(minutes=i * 15)
        tenant = "1" if i % 3 == 0 else "200000"
        case_key = f"CS-2026-{i % 5 + 1:04d}" if i % 2 == 0 else None
        case_id = f"case-{i % 5 + 1:03d}" if case_key else None

        events.append(
            AgentEvent(
                tenantId=tenant,
                timestamp=ts,
                stage=stage.value,
                message=message,
                caseKey=case_key,
                caseId=case_id,
                severity="ERROR" if "failed" in message.lower() else "INFO",
                traceId=f"trace-{i:04d}-{ts.strftime('%H%M')}",
                actionId=f"prop_case-{i % 5 + 1:03d}_action_{i:04d}" if "Action" in message else None,
                payload={"index": i, "source": "seed_script"},
            )
        )
    return events


async def main():
    parser = argparse.ArgumentParser(description="Agent Stream 샘플 이벤트 시드")
    parser.add_argument("--count", type=int, default=20, help="생성할 이벤트 수 (기본 20)")
    parser.add_argument("--dry-run", action="store_true", help="push 없이 로컬 출력만")
    args = parser.parse_args()

    events = _make_sample_events(args.count)
    print(f"Generated {len(events)} sample Agent Stream events")
    print("-" * 60)

    if args.dry_run:
        for i, e in enumerate(events):
            print(f"  {i + 1}. [{e.stage}] {e.message[:50]}...")
        print("-" * 60)
        print("Dry-run: no push. Run without --dry-run to push to Synapse.")
        return

    from core.agent_stream.writer import get_agent_stream_writer

    writer = get_agent_stream_writer()
    ok = await writer.push(events)
    if ok:
        print(f"✅ Pushed {len(events)} events to {writer._push_url}")
    else:
        print("⚠️ Push failed (check Synapse URL, network, or API availability)")
        print("   Tip: Ensure Synapse is running and POST /api/synapse/agent/events exists")


if __name__ == "__main__":
    asyncio.run(main())
