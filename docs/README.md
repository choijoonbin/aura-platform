# 📚 Aura-Platform 문서 가이드

> **목적**: Aura-Platform 문서 구조 및 각 폴더의 역할 안내

> ⚠️ **통합 예정**: 루트 `README.md`와 이 파일(`docs/README.md`)이 중복될 수 있어, 내일 확인 후 하나로 통합하고 하나는 삭제할 예정입니다.

---

## 📂 폴더 구조

```
docs/
├── integration-tests/      # 통합 테스트 관련 문서
├── backend-integration/    # 백엔드 통합 관련 문서
├── handoff/                # 전달 문서 (Handoff/Delivery)
├── guides/                 # 가이드 및 스펙 문서
└── updates/                # 업데이트 및 상태 문서
```

---

## 📁 폴더별 설명

### 1. `integration-tests/` - 통합 테스트 문서

**목적**: 통합 테스트 수행을 위한 가이드 및 결과 문서

**주요 파일**:
- `INTEGRATION_TEST_SUMMARY.md` - 통합 테스트 전체 요약 (PM/QA/모든 팀 공유)
- `INTEGRATION_TEST_DELIVERY_GUIDE.md` - 문서 전달 대상 및 방법 안내
- `BACKEND_INTEGRATION_TEST.md` - 백엔드 팀용 통합 테스트 가이드
- `FRONTEND_INTEGRATION_TEST.md` - 프론트엔드 팀용 통합 테스트 가이드
- `AURA_PLATFORM_INTERNAL_TEST.md` - Aura-Platform 내부 동작 검증 가이드
- `AURA_PLATFORM_INTERNAL_TEST_RESULTS.md` - 내부 테스트 결과 문서
- `TESTING_GUIDE.md` - 테스트 방법 가이드 (직접 테스트, Gateway, 프론트엔드)
- `PHASE2_INTEGRATION_TEST.md` - Phase 2 통합 테스트
- `PHASE2_TEST_GUIDE.md` - Phase 2 테스트 가이드

**대상**: 백엔드 팀, 프론트엔드 팀, QA 팀, 프로젝트 관리자

---

### 2. `backend-integration/` - 백엔드 통합 문서

**목적**: 백엔드와의 통합 관련 문서 및 체크리스트

**주요 파일**:
- `BACKEND_INTEGRATION_CHECKLIST.md` - 백엔드 통합 체크리스트
- `BACKEND_INTEGRATION_CHECKLIST_RESPONSE.md` - 백엔드 통합 체크리스트 응답
- `BACKEND_INTEGRATION_CHECKLIST_REVIEW.md` - 백엔드 통합 체크리스트 리뷰
- `BACKEND_INTEGRATION_RESPONSE.md` - 백엔드 응답 문서
- `BACKEND_INTEGRATION_STATUS.md` - 백엔드 통합 상태
- `BACKEND_INTEGRATION_SUMMARY.md` - 백엔드 통합 요약
- `BACKEND_INTEGRATION_COMPLETE.md` - 백엔드 통합 완료 문서
- `BACKEND_INTEGRATION_COMPLETE_FINAL.md` - 백엔드 통합 최종 완료 문서
- `BACKEND_VERIFICATION_RESPONSE.md` - 백엔드 검증 응답 문서
- `BACKEND_UPDATE_SUMMARY.md` - 백엔드 업데이트 요약
- `INTEGRATION_CHECKLIST.md` - 통합/협업 체크리스트
- `INTEGRATION_STATUS.md` - 통합 상태 문서
- `SSE_RECONNECT_POLICY.md` - SSE 재연결 정책 (id/Last-Event-ID, dedupe, [DONE])

**대상**: 백엔드 팀, Aura-Platform 개발팀

---

### 3. `handoff/` - 전달 문서

**목적**: 다른 팀에 전달하는 핸드오프 문서

**주요 파일**:
- `BACKEND_HANDOFF.md` - 백엔드 팀 전달 문서
- `BACKEND_DELIVERY.md` - 백엔드 전달 문서
- `FRONTEND_HANDOFF.md` - 프론트엔드 팀 전달 문서
- `AURA_PLATFORM_HANDOFF.md` - Aura-Platform 핸드오프 문서
- `README_BACKEND_DELIVERY.md` - 백엔드 전달 README

**대상**: 백엔드 팀, 프론트엔드 팀

---

### 4. `guides/` - 가이드 및 스펙 문서

**목적**: 개발 가이드, 스펙, 빠른 참조 문서

**주요 파일**:
- `AURA_PLATFORM_INTEGRATION_GUIDE.md` - 상세 통합 가이드
- `AURA_PLATFORM_QUICK_REFERENCE.md` - 핵심 정보 빠른 참조
- `QUICK_START.md` - 빠른 시작 가이드
- `FRONTEND_V1_SPEC.md` - 프론트엔드 v1 스펙
- `JWT_COMPATIBILITY.md` - JWT Python-Java 호환성 가이드
- `DOCKER_REDIS_SETUP.md` - Docker Redis 설정 가이드

**대상**: 모든 개발자, 신규 팀원

---

### 5. `updates/` - 업데이트 및 상태 문서

**목적**: 프로젝트 업데이트 및 상태 문서

**주요 파일**:
- `AURA_PLATFORM_UPDATE.md` - Aura-Platform 업데이트 문서
- `SETUP_SUCCESS.md` - 설정 완료 보고서

**대상**: 프로젝트 관리자, 개발팀

---

## 🔍 문서 찾기 가이드

### 통합 테스트 관련 문서를 찾고 싶다면?
→ `integration-tests/` 폴더 확인

### 백엔드 통합 관련 문서를 찾고 싶다면?
→ `backend-integration/` 폴더 확인

### 다른 팀에 전달할 문서를 찾고 싶다면?
→ `handoff/` 폴더 확인

### 개발 가이드나 스펙을 찾고 싶다면?
→ `guides/` 폴더 확인

### 프로젝트 업데이트 내역을 찾고 싶다면?
→ `updates/` 폴더 확인

---

## 📝 문서 작성 가이드

### 새 문서를 추가할 때

1. **문서의 성격 파악**
   - 통합 테스트 관련 → `integration-tests/`
   - 백엔드 통합 관련 → `backend-integration/`
   - 전달 문서 → `handoff/`
   - 가이드/스펙 → `guides/`
   - 업데이트/상태 → `updates/`

2. **파일명 규칙**
   - 대문자와 언더스코어 사용: `BACKEND_INTEGRATION_TEST.md`
   - 명확하고 설명적인 이름 사용

3. **문서 내부 참조**
   - 같은 폴더 내 문서 참조: `[문서명](파일명.md)`
   - 다른 폴더 문서 참조: `[문서명](../폴더명/파일명.md)`
   - 루트 README 참조: `[README](../../README.md)`

---

## 🔗 주요 문서 링크

### 통합 테스트
- [통합 테스트 요약](integration-tests/INTEGRATION_TEST_SUMMARY.md)
- [백엔드 통합 테스트](integration-tests/BACKEND_INTEGRATION_TEST.md)
- [프론트엔드 통합 테스트](integration-tests/FRONTEND_INTEGRATION_TEST.md)
- [Aura-Platform 내부 테스트](integration-tests/AURA_PLATFORM_INTERNAL_TEST.md)
- [테스트 가이드](integration-tests/TESTING_GUIDE.md)

### 백엔드 통합
- [백엔드 통합 체크리스트](backend-integration/BACKEND_INTEGRATION_CHECKLIST.md)
- [백엔드 통합 상태](backend-integration/BACKEND_INTEGRATION_STATUS.md)
- [통합/협업 체크리스트](backend-integration/INTEGRATION_CHECKLIST.md)

### 전달 문서
- [백엔드 전달 문서](handoff/BACKEND_HANDOFF.md)
- [프론트엔드 전달 문서](handoff/FRONTEND_HANDOFF.md)

### 가이드
- [통합 가이드](guides/AURA_PLATFORM_INTEGRATION_GUIDE.md)
- [빠른 참조](guides/AURA_PLATFORM_QUICK_REFERENCE.md)
- [빠른 시작](guides/QUICK_START.md)
- [JWT 호환성 가이드](guides/JWT_COMPATIBILITY.md)

---

**최종 업데이트**: 2026-02-01  
**담당자**: Aura-Platform 개발팀
