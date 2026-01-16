#!/bin/bash
# Aura-Platform 서버 중지 스크립트

echo "=== Aura-Platform 서버 중지 ==="

# 포트 9000에서 실행 중인 프로세스 확인 및 종료
PORT_9000_PID=$(lsof -ti:9000 2>/dev/null)
if [ -n "$PORT_9000_PID" ]; then
    echo "포트 9000에서 실행 중인 프로세스 발견: PID $PORT_9000_PID"
    kill -9 $PORT_9000_PID
    echo "✅ 프로세스 종료 완료 (PID: $PORT_9000_PID)"
else
    echo "포트 9000에서 실행 중인 프로세스 없음"
fi

# 포트 8000에서 실행 중인 프로세스 확인 및 종료 (이전 포트)
PORT_8000_PID=$(lsof -ti:8000 2>/dev/null)
if [ -n "$PORT_8000_PID" ]; then
    echo "포트 8000에서 실행 중인 프로세스 발견: PID $PORT_8000_PID"
    kill -9 $PORT_8000_PID
    echo "✅ 프로세스 종료 완료 (PID: $PORT_8000_PID)"
else
    echo "포트 8000에서 실행 중인 프로세스 없음"
fi

# Python 프로세스 확인 (main.py 또는 uvicorn)
PYTHON_PIDS=$(ps aux | grep -E "python.*main.py|uvicorn.*main" | grep -v grep | awk '{print $2}')
if [ -n "$PYTHON_PIDS" ]; then
    echo "Python 프로세스 발견: $PYTHON_PIDS"
    echo "$PYTHON_PIDS" | xargs kill -9
    echo "✅ Python 프로세스 종료 완료"
else
    echo "실행 중인 Python 프로세스 없음"
fi

echo ""
echo "✅ 서버 중지 완료"
