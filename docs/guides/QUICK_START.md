# 🚀 Aura-Platform Quick Start Guide

## 📌 빠른 시작

### 1️⃣ 서버 시작하기

```bash
cd /Users/joonbinchoi/Work/dwp/aura-platform
source venv/bin/activate
python main.py
```

서버가 시작되면 다음과 같은 메시지가 표시됩니다:
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [xxxxx] using WatchFiles
```

### 2️⃣ API 문서 확인

브라우저에서 다음 URL로 접속:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### 3️⃣ 기본 엔드포인트 테스트

**터미널에서**:
```bash
# 루트 엔드포인트
curl http://localhost:8000/

# 헬스체크
curl http://localhost:8000/health
```

**예상 응답**:
```json
{
    "message": "Welcome to Aura-Platform!",
    "version": "0.1.0",
    "status": "operational"
}
```

---

## 🔧 설정 확인

### 설치 검증 스크립트 실행

```bash
cd /Users/joonbinchoi/Work/dwp/aura-platform
source venv/bin/activate
python scripts/test_setup.py
```

모든 테스트를 통과하면 ✅가 표시됩니다.

### 설정 정보 확인

```bash
cd /Users/joonbinchoi/Work/dwp/aura-platform
source venv/bin/activate
python -c "from core.config import settings; print(f'App: {settings.app_name}'); print(f'Version: {settings.app_version}'); print(f'Environment: {settings.app_env}')"
```

---

## ⚙️ 환경변수 설정

### OpenAI API 키 설정 (필수)

```bash
# .env 파일 편집
nano .env
```

다음 항목을 수정:
```env
OPENAI_API_KEY=sk-your-actual-openai-api-key-here
```

**API 키 발급**: https://platform.openai.com/api-keys

---

## 📂 프로젝트 구조

```
aura-platform/
├── core/              # 핵심 로직
│   ├── llm/          # OpenAI 클라이언트
│   ├── memory/       # 메모리 관리
│   ├── security/     # 인증/권한
│   └── config.py     # 전역 설정
├── domains/          # 부서별 도메인
│   └── dev/          # 개발팀 도메인
├── api/              # FastAPI 앱
├── tools/            # 통합 도구
├── database/         # DB 모델
├── tests/            # 테스트
├── docs/             # 문서
└── scripts/          # 유틸리티 스크립트
```

---

## 🎯 다음 단계

### Phase 2: Core 확장
1. Redis 메모리 구현
2. JWT 인증 시스템
3. 데이터베이스 설정

### Phase 3: Dev Domain
1. Git 통합 도구
2. Code Review Agent
3. Issue Manager Agent

자세한 내용은 [README.md](../README.md)를 참조하세요.

---

## 🛠️ 유용한 명령어

### 개발 모드로 서버 시작
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 의존성 추가
```bash
# requirements.txt에 패키지 추가 후
pip install -r requirements.txt
```

### 코드 포맷팅
```bash
black .
ruff check .
```

### 테스트 실행
```bash
pytest
pytest --cov=.
```

---

## ❓ 문제 해결

### 서버가 시작되지 않는 경우

1. **가상환경 활성화 확인**:
   ```bash
   source venv/bin/activate
   which python  # venv 경로가 나와야 함
   ```

2. **의존성 재설치**:
   ```bash
   pip install -r requirements.txt
   ```

3. **포트 충돌 확인**:
   ```bash
   lsof -i :8000  # 8000번 포트 사용 중인 프로세스 확인
   ```

### 환경변수 로딩 실패

1. **.env 파일 존재 확인**:
   ```bash
   ls -la .env
   ```

2. **설정 검증**:
   ```bash
   python -c "from core.config import settings; print(settings.model_dump())"
   ```

### ImportError 발생

```bash
# Python 경로 확인
python -c "import sys; print(sys.path)"

# 패키지 재설치
pip install --force-reinstall -r requirements.txt
```

---

## 📞 도움말

- **프로젝트 개요**: [README.md](../README.md)
- **설치 성공 리포트**: [SETUP_SUCCESS.md](./SETUP_SUCCESS.md)
- **변경 이력**: [CHANGELOG.md](../CHANGELOG.md)

---

**Happy Coding! 🎉**
