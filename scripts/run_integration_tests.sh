#!/bin/bash

echo "╔════════════════════════════════════════════════════════════╗"
echo "║     Aura-Platform Phase 2 Integration Tests               ║"
echo "╚════════════════════════════════════════════════════════════╝"

cd /Users/joonbinchoi/Work/dwp/aura-platform
source venv/bin/activate

# Redis 연결 확인
echo -e "\n[1/5] Checking Redis..."
redis-cli ping > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "  ✓ Redis is running"
else
    echo "  ✗ Redis is not running"
    echo "  Run: brew services start redis"
    exit 1
fi

# Redis 기본 테스트
echo -e "\n[2/5] Testing Redis Store..."
python scripts/test_redis_basic.py
if [ $? -ne 0 ]; then
    echo "  ✗ Redis store test failed"
    exit 1
fi

# Checkpoint 테스트
echo -e "\n[3/5] Testing Checkpointer..."
python scripts/test_checkpoint.py
if [ $? -ne 0 ]; then
    echo "  ✗ Checkpoint test failed"
    exit 1
fi

# 대화 메모리 테스트
echo -e "\n[4/5] Testing Conversation Memory..."
python scripts/test_conversation.py
if [ $? -ne 0 ]; then
    echo "  ✗ Conversation test failed"
    exit 1
fi

# JWT 테스트
echo -e "\n[5/5] Testing JWT..."
python scripts/test_jwt_standalone.py
if [ $? -ne 0 ]; then
    echo "  ✗ JWT test failed"
    exit 1
fi

echo -e "\n╔════════════════════════════════════════════════════════════╗"
echo "║              ✅ All Integration Tests Passed!              ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
echo "📌 Next steps:"
echo "  1. Test with dwp_backend JWT integration"
echo "  2. Test with dwp_frontend streaming"
echo "  3. See docs/PHASE2_TEST_GUIDE.md for detailed guide"
