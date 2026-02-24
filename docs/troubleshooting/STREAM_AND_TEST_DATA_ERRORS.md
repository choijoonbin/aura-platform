# 테스트 데이터 생성 후 스트림 오류 원인 및 조치

테스트 데이터 생성 직후 스트림 과정에서 발생한 로그를 기준으로 원인과 조치 방법을 정리합니다.

---

## 1. 401 Unauthorized on `POST /aura/test/stream`

### 현상
```
Missing Authorization header: /aura/test/stream
"POST /aura/test/stream HTTP/1.1" 401 Unauthorized
```

### 원인
- `POST /aura/test/stream` 은 인증이 필요한 경로였고, 프론트에서 **Authorization 헤더 없이** 호출하면 미들웨어에서 401을 반환함.
- 테스트/데모 화면에서 토큰 없이 스트림만 열고 싶을 때 발생.

### 조치 (Aura 측 적용 완료)
- **인증 예외**: `/aura/test/stream` 을 미들웨어 `EXEMPT_PATTERNS`에 추가하여, 해당 경로는 Authorization 없이 통과하도록 함.
- **라우트**: `backend_stream` 에서 `OptionalUser` 사용. 인증이 없으면 `user_id=test`, `tenant_id=1` 인 기본 사용자로 동작.
- **프론트**: 그대로 `POST /aura/test/stream` 호출해도 401 없이 동작. (운영 환경에서는 필요 시 Authorization 전달 권장.)

---

## 2. 분석 스트림 조기 종료 (Cancelled via cancel scope)

### 현상
```
case_analysis_stream: start consuming run_id=8539f823-... case_id=66
case_analysis_stream: first chunk sent run_id=8539f823-...
case_analysis_stream: stream closed run_id=8539f823-... reason=Cancelled via cancel scope ... by RequestResponseCycle.run_asgi()
```

- `GET /aura/cases/66/analysis/stream?runId=...` 는 **200 OK** 로 스트림을 시작하고 첫 청크까지 전송한 뒤, 곧바로 **클라이언트 측에서 연결이 취소**됨.
- 서버 로그 상으로는 **분석 자체는 정상 완료** (콜백 전송, queue 제거까지 수행).

### 원인
- **클라이언트(또는 Gateway)가 SSE 연결을 먼저 끊는 상황**입니다. 서버가 스트림을 중단한 것이 아님.
- 가능한 원인:
  - 스트림을 연 직후 컴포넌트 언마운트로 `fetch` / `EventSource` 가 abort됨.
  - 202 응답의 `streamUrl` / `runId` 로 스트림 URL을 열기 전에 다른 요청으로 덮어쓰거나, 잘못된 runId로 재연결하면서 이전 스트림이 취소됨.
  - 짧은 타임아웃으로 인한 abort.
  - Gateway/프록시의 스트리밍 응답 타임아웃.

### 조치 (프론트/Gateway)
- **스트림 연결 유지**: `GET .../analysis/stream?runId={runId}` 연결을 **`data: [DONE]` 또는 `failed` 이벤트가 올 때까지 유지**하고, 중간에 abort하지 않도록 함.
- **runId 일치**: `POST .../analysis-runs` 의 202 응답에 담긴 `runId` 를 그대로 사용해 스트림 URL을 구성할 것. 다른 runId로 재연결하지 않음.
- **언마운트 시에만 정리**: 스트림을 구독하는 컴포넌트가 언마운트될 때만 연결 해제하도록 하고, 페이지 전환이나 상태 변경 시 불필요한 재연결/abort를 피할 것.
- **타임아웃**: 분석이 수십 초 걸릴 수 있으므로, 스트림용 fetch/EventSource 타임아웃을 넉넉히 두거나, 스트리밍 응답에는 타임아웃을 걸지 않음.
- **Gateway**: 스트리밍 프록시가 일정 시간 후 연결을 끊지 않도록 설정 확인.

---

## 3. Azure Content Filter (INPUT_NORM 단계)

### 현상
```
generate_thought_stream LLM failed: step=INPUT_NORM error=Azure has not provided the response due to a content filter being triggered
```

### 원인
- Azure OpenAI 콘텐츠 정책에 의해 **INPUT_NORM** 단계에서 응답이 차단됨.
- 입력(케이스 요약/증거 등) 또는 프롬프트 문구가 정책에 걸린 경우 발생.

### 조치
- **파이프라인**: 해당 단계만 실패하고, 이후 단계는 그대로 진행됨 (해당 구간 thought 스트림만 비거나 fallback 처리).
- **근본 완화**: 입력 데이터/프롬프트에서 정책을 유발할 수 있는 문구를 완화하거나, Azure 포털에서 해당 배포의 content filter 레벨을 조정 (운영 정책에 맞게).

---

## 4. RAG 검색 0건

### 현상
```
[RAG Search] Query returned 0 rows
audit_analysis_pipeline: RAG summary case_id=66 results=0 max_score=0.000 threshold=0.700 need_web_search=True
```

### 원인
- 해당 케이스에 연결된 `doc_id`(예: 23)에 대해 **pgvector에 청크가 없거나**, 쿼리와 유사도가 threshold(0.75) 미만인 경우.

### 조치
- **벡터화**: 해당 문서가 `POST /aura/rag/...` 등으로 벡터화되어 pgvector에 적재되었는지 확인.
- **에이전트 설정**: 백엔드 에이전트 설정에서 해당 케이스/테넌트에 올바른 `docIds` 가 할당되었는지 확인.
- **운영**: 0건이어도 파이프라인은 `web_search` 등으로 이어져 분석은 완료됨.

---

## 5. 요약

| 현상 | 원인 | 조치 |
|------|------|------|
| 401 on `/aura/test/stream` | Authorization 미전달 | Aura: 경로 인증 예외 + OptionalUser 처리 적용. FE: 필요 시 토큰 전달. |
| 스트림 즉시 취소 | 클라이언트/Gateway가 연결 종료 | FE: runId 유지, 스트림 유지, 타임아웃/언마운트 처리 점검. |
| Azure content filter | 입력/프롬프트 정책 위반 | 입력·프롬프트 조정 또는 Azure 정책 조정. |
| RAG 0건 | 벡터 미적재 또는 유사도 부족 | 문서 벡터화·에이전트 docIds 확인. |

위 조치 후에도 동일 로그가 반복되면, 스트림 취소 시점의 **프론트엔드 코드(스트림 구독/정리 로직)** 와 **Gateway 스트리밍 타임아웃** 설정을 함께 확인하는 것이 좋습니다.
