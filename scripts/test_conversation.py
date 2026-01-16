#!/usr/bin/env python3
"""대화 메모리 테스트"""

import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.memory import (
    add_user_message,
    add_assistant_message,
    get_recent_context,
    get_conversation_history,
)

async def test_conversation():
    print("=" * 60)
    print("🔍 Testing Conversation Memory")
    print("=" * 60)
    
    thread_id = "test_conv_001"
    tenant_id = "tenant1"
    
    # 1. 사용자 메시지 추가
    print("\n1. Adding user message...")
    await add_user_message(
        thread_id,
        "What is LangGraph?",
        tenant_id,
    )
    print("  ✓ User message added")
    
    # 2. 어시스턴트 메시지 추가
    print("\n2. Adding assistant message...")
    await add_assistant_message(
        thread_id,
        "LangGraph is a library for building stateful, multi-actor applications with LLMs.",
        tenant_id,
    )
    print("  ✓ Assistant message added")
    
    # 3. 추가 대화
    print("\n3. Adding more messages...")
    await add_user_message(thread_id, "Can you give me an example?", tenant_id)
    await add_assistant_message(
        thread_id,
        "Sure! You can create agents that maintain state across interactions.",
        tenant_id,
    )
    print("  ✓ Additional messages added")
    
    # 4. 대화 조회
    print("\n4. Retrieving conversation...")
    history = await get_conversation_history()
    messages = await history.get_messages(thread_id, tenant_id)
    print(f"  ✓ Retrieved {len(messages)} message(s)")
    
    for i, msg in enumerate(messages, 1):
        content_preview = msg.content[:50] + "..." if len(msg.content) > 50 else msg.content
        print(f"    {i}. [{msg.role.value}] {content_preview}")
    
    # 5. LLM 컨텍스트 생성
    print("\n5. Generating LLM context...")
    context = await get_recent_context(thread_id, tenant_id, limit=10)
    print("  ✓ Context generated:")
    print("  " + "-" * 56)
    for line in context.split('\n'):
        print(f"  {line}")
    print("  " + "-" * 56)
    
    # 6. 메타데이터 조회
    print("\n6. Getting metadata...")
    metadata = await history.get_thread_metadata(thread_id, tenant_id)
    print(f"  ✓ Thread ID: {metadata['thread_id']}")
    print(f"  ✓ Tenant ID: {metadata['tenant_id']}")
    print(f"  ✓ Message count: {metadata['message_count']}")
    print(f"  ✓ Created at: {metadata['created_at']}")
    
    # 7. Cleanup
    print("\n7. Cleaning up...")
    await history.clear_history(thread_id, tenant_id)
    print("  ✓ History cleared")
    
    print("\n" + "=" * 60)
    print("✅ All conversation tests passed!")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_conversation())
