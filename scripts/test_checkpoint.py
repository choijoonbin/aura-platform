#!/usr/bin/env python3
"""LangGraph Checkpointer 테스트"""

import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.memory import get_checkpointer

async def test_checkpoint():
    print("=" * 60)
    print("🔍 Testing LangGraph Checkpointer")
    print("=" * 60)
    
    checkpointer = await get_checkpointer()
    thread_id = "test_thread_001"
    
    # 1. Checkpoint 저장
    print("\n1. Saving checkpoint...")
    state = {
        "messages": [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi! How can I help?"},
        ],
        "context": {"user_id": "user123", "step": 1},
    }
    
    checkpoint_id = await checkpointer.save_checkpoint(thread_id, state)
    print(f"  ✓ Checkpoint saved: {checkpoint_id}")
    
    # 2. Checkpoint 로드
    print("\n2. Loading checkpoint...")
    loaded_state = await checkpointer.load_checkpoint(thread_id)
    assert loaded_state == state
    print("  ✓ Checkpoint loaded successfully")
    print(f"  - Messages: {len(loaded_state['messages'])}")
    print(f"  - Context: {loaded_state['context']}")
    
    # 3. 여러 Checkpoint 저장
    print("\n3. Saving multiple checkpoints...")
    state2 = {**state, "context": {"user_id": "user123", "step": 2}}
    checkpoint_id_2 = await checkpointer.save_checkpoint(thread_id, state2)
    print(f"  ✓ Checkpoint 2 saved: {checkpoint_id_2}")
    
    # 4. Checkpoint 목록
    print("\n4. Listing checkpoints...")
    checkpoints = await checkpointer.list_checkpoints(thread_id)
    print(f"  ✓ Found {len(checkpoints)} checkpoint(s)")
    for cp in checkpoints:
        print(f"    - {cp['checkpoint_id']} (timestamp: {cp['timestamp']})")
    
    # 5. 특정 Checkpoint 로드
    print("\n5. Loading specific checkpoint...")
    state_1 = await checkpointer.load_checkpoint(thread_id, checkpoint_id)
    assert state_1['context']['step'] == 1
    print(f"  ✓ Loaded checkpoint {checkpoint_id} (step 1)")
    
    # 6. Cleanup
    print("\n6. Cleaning up...")
    await checkpointer.delete_checkpoint(thread_id)
    print("  ✓ All checkpoints deleted")
    
    print("\n" + "=" * 60)
    print("✅ All checkpoint tests passed!")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_checkpoint())
