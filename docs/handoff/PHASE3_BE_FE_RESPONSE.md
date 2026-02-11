# BE/FE 공유 수신 후 Aura 대응 및 추가 전달

> BE(back.txt), FE(front.txt) 공유 내용 반영. 작업 완료 후 각 시스템에 전달할 내용을 정리합니다.

---

## 1. Aura 측 진행한 작업

### 1.1 Phase2 body.evidence 확장 수용 (BE 요청 반영)

- **대상**: `POST /aura/cases/{caseId}/analysis-runs` 트리거 시 BE가 보내는 **body.evidence** 확장 스키마.
- **변경**: `core/analysis/phase2_pipeline.py` — `_normalize_body_evidence()` 확장.
  - 기존: `evidence`, `ragRefs` 만 evidence_items 로 변환.
  - **추가 수용**: **document** (header, items, type, docKey), **openItems**, **partyIds**, **lineage**, **policies**.
- **동작**: document 없음 케이스 등으로 BE가 open-item 기반 동일 구조로 채워 보내도, Aura는 위 필드를 파싱해 RAG/스코어링 입력용 evidence_items에 반영합니다. 기존 evidence/ragRefs는 그대로 유지됩니다.

### 1.2 콜백·스트림·fingerprint (BE 계약 유지)

- **콜백**: 기존 계약 유지. 실패 시 callback FAILED 반환.
- **proposals**: BE가 dedup_key(fingerprint) 계산·저장하므로, Aura는 proposals 전달만 수행 (현재 Phase2/Phase3 모두 fingerprint 포함 전달).

---

## 2. BE 팀에 전달할 추가 사항

- **Phase2 evidence 확장 수용 완료**  
  - `body.evidence`에 **document**, **openItems**, **partyIds**, **lineage**, **policies**를 넣어 주시면, Aura에서 정규화 후 파이프라인에 반영합니다. 기존 **evidence**, **ragRefs**도 그대로 사용합니다.
- **202 응답**  
  - Phase2/Phase3 트리거 모두 **202 Accepted**를 반환합니다. BE에서 202를 실패로 처리하지 않도록 only 확인 부탁드립니다.
- **스트림 완료**  
  - 스트림 종료 시 **event: completed** + `data: {"runId":"...","status":"completed"}` 를 보낸 뒤 **data: [DONE]**을 전송합니다. FE의 completed 후 refetch가 동작할 수 있도록 이미 이 순서로 구현되어 있습니다.

---

## 3. FE 팀에 전달할 추가 사항

- **완료 이벤트**  
  - 스트림 종료 시 **event: completed** 를 보내고, 이어서 **data: [DONE]** 을 보냅니다.  
  - FE에서 기대하신 “가능하면 event:completed 전송”에 맞춰 구현되어 있으므로, completed 수신 후 refetch만 유지하시면 됩니다.
- **event: agent (Phase3)**  
  - Phase3 스트림에서는 **event: agent** + `data: { agent, message, percent }` 를 전송합니다.  
  - FE에서 step과 동일하게 진행률(percent) 및 라벨로 표시하시면 됩니다.
- **진행률**  
  - **event: step** / **event: agent** 의 **percent** 값을 그대로 진행률 바에 사용하시면 됩니다.

---

## 4. 요약 표

| 대상 | Aura 진행 작업 | 전달/확인 요청 |
|------|----------------|----------------|
| **BE** | Phase2 body.evidence 확장(document, openItems, partyIds, lineage, policies) 수용 | 202를 실패로 처리하지 않기 확인, 확장 evidence 전송 시 Aura 정상 반영 |
| **FE** | event:completed + [DONE] 순서 유지, event:agent(Phase3) 스키마(agent, message, percent) 전송 | 완료 시 refetch, agent/step percent 진행률 표시 유지 |

위 내용은 BE(back.txt)·FE(front.txt) 공유를 반영한 Aura 측 대응 및 각 시스템 전달 사항입니다. 추가 연동 이슈가 있으면 이 문서에 보완해 두시면 됩니다.

---

## 5. FE 답변 수신 (FE 반영 완료 공유)

### FE 반영 완료

| 출처 | 내용 | FE 반영 |
|------|------|--------|
| **BE** | fingerprint, decidedBy, decidedAt, decisionComment | DTO·UI 반영, 결정 메타 표시 |
| **BE** | approve/reject body `{ "comment": "..." }` | API·mutation에 comment 옵션 추가 |
| **BE** | `POST .../action-proposals/{proposalId}/execute` (APPROVED만) | execute API·useExecuteProposalMutation, "실행(시뮬)" 버튼(APPROVED 시) |
| **Aura** | streamPath (스트림 경로) | 응답에서 streamUrl 또는 streamPath 사용, 상대 경로 시 NX_API_URL 접두 |
| **Aura** | 이벤트 started/step/agent/completed/failed | agent 처리·completed/[DONE] 처리 이미 반영 |

### 계약 정리 (FE 기준)

- **스트림**: BE가 Aura 트리거 후 받은 **streamPath**를 FE에 전달. FE는 `streamUrl` 또는 `streamPath`로 수신해 `GET /aura/cases/{caseId}/analysis/stream?runId=` 에 연결(상대 경로면 NX_API_URL 접두).
- **결정**: BE **decision API** 제공 완료. FE는 `POST .../decision` body `{ decision, comment? }` 로 전환 완료(approve=APPROVE, reject=REJECT).
- **실행**: `POST .../action-proposals/{proposalId}/execute` (path에 proposalId, body 없음) 사용 중. BE는 `POST .../actions/execute` (body에 proposalId 필수)도 지원.

---

## 6. FE 답변 수신 후 — 다시 전달할 내용 (FE 팀용)

아래는 FE에 “이번에 작성한 내용”을 다시 전달할 때 붙여 보낼 수 있는 확인 문구입니다.

```
[Aura] FE 반영 완료 공유 확인

FE에서 정리해 주신 반영 사항·계약 정리 확인했습니다.

■ 스트림
  - Aura는 BE가 내려준 streamPath(또는 streamUrl)에 해당하는
    GET /aura/cases/{caseId}/analysis/stream?runId= 를 그대로 제공합니다.
    상대 경로 시 FE에서 NX_API_URL 접두 시 동일하게 연결 가능합니다.

■ 이벤트
  - started / step / agent / completed / failed 전송 계약 유지합니다.
  - completed 후 data: [DONE] 순서도 변경 없습니다.

추가로 Aura 쪽에서 수정·전달할 사항 없습니다. 연동 이슈 있으면 공유 부탁드립니다.
```

---

## 7. BE 전달사항 수신 (Aura 대상)

### BE → Aura 전달 내용

- **트리거 시 evidence 페이로드 확장**
  - BE가 `POST /aura/cases/{caseId}/analysis-runs` 호출 시 보내는 **body.evidence** 에 다음 필드가 추가됩니다.  
    **document** (header, items, type, docKey), **openItems** (배열), **partyIds** (배열), **lineage** (LineageResponseDto 구조), **policies** (빈 배열).  
    기존 **evidence**, **ragRefs** 는 그대로 유지됩니다.
- **document 구조**
  - document 없음 케이스도 open-item 기반으로 동일 구조(document 형태)로 채워 전달합니다. RAG/LLM 입력으로 document·openItems·lineage·partyIds 를 일관되게 사용할 수 있습니다.
- **콜백·스트림**
  - 기존 계약 유지. 실패 시 callback FAILED 반환, proposal dedup_key(fingerprint)는 BE가 계산·저장하므로 Aura는 proposals 전달만 하면 됩니다.

---

## 8. BE 전달사항 수신 후 — 다시 전달할 내용 (BE 팀용)

아래는 BE에 전달사항 수신을 확인했다고 보낼 때 사용할 수 있는 문구입니다.

```
[Aura] BE 전달사항 확인 및 반영 완료

BE에서 전달해 주신 Aura 대상 사항 확인했습니다. 모두 반영되어 있습니다.

■ body.evidence 확장
  - document, openItems, partyIds, lineage, policies 수신 시
    Phase2 파이프라인에서 정규화 후 evidence_items로 반영합니다.
    document 없음·open-item 기반 구조도 동일하게 처리합니다.
  - evidence, ragRefs 는 기존처럼 유지합니다.

■ 콜백·스트림·fingerprint
  - 콜백/스트림 계약 유지. 실패 시 FAILED 콜백 반환합니다.
  - proposals는 fingerprint 포함해 전달하며, dedup_key 계산·저장은 BE에서 하시면 됩니다.

추가로 Aura 쪽에서 변경할 사항 없습니다. 이슈 있으면 공유 부탁드립니다.
```

---

## 9. FE 전달 내용 (Aura 추가 전달 → FE 문서 반영)

FE에서 Aura 추가 전달 사항을 자체 문서에 반영했다고 공유한 내용입니다.

| Aura 추가 전달 | FE 문서 반영 |
|----------------|--------------|
| streamPath/streamUrl → GET /aura/.../stream?runId= 제공 | §2.3 스트림, §3 Q1 |
| 상대 경로 시 FE에서 NX_API_URL 접두 시 동일 연결 가능 | §2.3, §3 |
| 이벤트·completed 후 data:[DONE] 순서 유지 | §2.3 |
| 추가 수정·전달 없음, 연동 이슈 시 공유 | — |

---

## 10. BE 답변 (Aura 확인 요청에 대한 BE 답변)

Aura가 BE에 요청한 확인 사항에 대한 BE 측 답변입니다.

| Aura 확인 요청 | BE 답변 |
|----------------|---------|
| **트리거 202** | BE는 Feign 202 수신 시 `failRunWithMessage`를 호출하지 않고, run을 **STARTED**로 두고 콜백만 대기하도록 이미 구현됨 → **202를 실패로 처리하지 않음**. |
| **스트림** | Aura가 종료 시 `event: completed` 후 `data: [DONE]` 전송, FE completed 후 refetch 형태로 구현 완료 → **BE는 스트림 내용을 바꾸지 않으며**, FE 계약과 일치함을 명시. |

### BE 반영 완료 (evidence 확장)

- **Phase2 body.evidence 확장 수용**: document, openItems, partyIds, lineage, policies → evidence_items로 정규화 후 파이프라인 반영.
- evidence, ragRefs는 기존과 동일 유지.

---

## 11. 미회신·추가 확인 필요 사항 정리 (최종)

### Aura가 답변 완료한 항목 (상대 측 회신 여부와 무관)

| 대상 | 상대 확인 요청/질문 | Aura 응답 위치 |
|------|----------------------|----------------|
| **BE** | 7.2 트리거 URL, 콜백 인증, streamPath 형식 | §12 답변 완료 |
| **FE** | Q3. failed 이벤트 retryable/error 사용 방식 | §13 답변 완료 |

### 이미 상대 측에서 답변/반영을 보낸 항목

| 대상 | Aura 전달/확인 요청 | 응답 상태 |
|------|---------------------|-----------|
| **BE** | 202를 실패로 처리하지 않기 | §10 답변: Feign 202 시 STARTED 유지·콜백 대기 |
| **BE** | 스트림 completed 후 [DONE] 순서 | §10 답변: 스트림 변경 없음, FE 계약 일치 |
| **BE** | body.evidence 확장 수용 반영 | §10 반영 완료 |
| **BE** | Phase3 internal 트리거·Phase3 전용 콜백 도입 계획 | §16 BE 명시적 회신 |
| **FE** | streamPath, completed·[DONE], event:agent | §5·§9: FE 반영 완료·문서 반영 공유 |

### 추가 확인이 필요할 수 있는 항목 (선택)

| 대상 | 내용 | 비고 |
|------|------|------|
| **BE** | §12 Aura 답변(7.2) 수신·반영 완료 | Aura는 답변함. BE가 "확인함" 회신은 없어도 동작에는 문제 없음. |
| **FE** | §13 Aura 답변(Q3) 수신·반영 완료 | Aura는 답변함. FE가 "확인함" 회신은 없어도 동작에는 문제 없음. |

※ Phase3 internal·콜백 도입 계획은 §16에서 BE 명시적 회신 수신함.  
※ FE가 BE에게 한 확인 요청(ragRefs, fingerprint, decision/execute API 등)은 FE↔BE 간 협의 사항이며, Aura는 당사자가 아님.

---

## 12. BE 확인 요청 (7.2 Aura) — Aura 답변

BE가 Aura에게 확인을 요청한 항목에 대한 Aura 측 답변입니다.

| 항목 | BE 확인 요청 내용 | Aura 답변 |
|------|------------------|-----------|
| **트리거 URL** | Phase3 시 `POST /aura/internal/cases/{caseId}/analysis-runs` 호출. Aura에서 **internal** 경로 노출 여부, **Authorization 필수** 정책 일치 여부. | **노출함.** `POST /aura/internal/cases/{caseId}/analysis-runs` 라우트 제공 중. **Authorization: Bearer &lt;token&gt;** 은 전역 미들웨어로 **필수** (Phase2와 동일). |
| **콜백 인증** | BE가 `callbacks.auth.token`을 넣어 주면 Aura가 콜백 시 `Authorization: Bearer {token}` 사용. 토큰 발급 주체(고정 시크릿 vs Gateway JWT 등) 정책. | Aura는 **BE가 넣어 준 token을 그대로** `Authorization: Bearer {token}` 으로 사용합니다. **발급 주체·형식은 BE/게이트웨이 정책에 따르며**, Aura는 검증하지 않고 전달만 합니다. |
| **streamPath 형식** | Phase3 202 응답의 **streamPath**가 상대 경로인지 절대 URL인지. FE에 내려줄 때 prefix 정책 맞추기 위함. | **상대 경로** 반환. 형식: `/aura/cases/{caseId}/analysis/stream?runId={runId}`. BE가 FE에 내려줄 때 절대 URL이 필요하면 **BE base URL(Gateway 등)을 prefix** 하시면 됩니다. |

---

### BE 팀에 전달할 답변 문구 (복사용)

```
[Aura] BE 확인 요청(7.2 Aura) 답변

■ 트리거 URL
  - POST /aura/internal/cases/{caseId}/analysis-runs 노출 중입니다.
  - Authorization: Bearer <token> 은 전역 정책으로 필수입니다 (Phase2와 동일).

■ 콜백 인증
  - callbacks.auth.token 을 그대로 Authorization: Bearer {token} 으로 사용합니다.
  - 토큰 발급 주체·형식은 BE/게이트웨이 정책에 따르시면 되고, Aura는 전달만 합니다.

■ streamPath 형식
  - 상대 경로로 반환합니다: /aura/cases/{caseId}/analysis/stream?runId={runId}
  - FE에 절대 URL로 내려주실 때는 BE(Gateway) base URL을 prefix 하시면 됩니다.
```

---

## 13. FE 질문 (Q3. failed 이벤트) — Aura 답변

FE의 **PHASE3_FOLLOWUP_QUESTIONS.md §2** 에서 요청한 **failed 이벤트 스키마(retryable, error 사용 방식)** 에 대한 Aura 답변입니다.

| 항목 | FE 질문 | Aura 답변 |
|------|---------|-----------|
| **Q3. failed 이벤트의 retryable** | retryable 값에 따라 "재시도 가능" 문구를 다르게 보여줘도 되는지, error 필드를 그대로 에러 메시지로 써도 되는지 | **둘 다 가능합니다.** **retryable**: UI에서 `true`일 때 "재시도 가능" 등으로 표시하고, `false`일 때는 다르게(또는 생략) 보여주셔도 됩니다. **error**: Aura가 넣는 사람이 읽기 쉬운 에러 메시지이므로, **그대로 에러 메시지로 표시**하셔도 됩니다. |

### FE 팀에 전달할 답변 문구 (복사용)

```
[Aura] failed 이벤트(Q3) 답변

■ retryable
  - 값에 따라 "재시도 가능" 문구를 다르게 보여주셔도 됩니다.
  - true → 재시도 가능 문구 표시, false → 다르게 표시하거나 생략 등 FE 정책대로 하시면 됩니다.

■ error
  - 에러 메시지로 그대로 사용하셔도 됩니다. Aura가 사람이 읽기 쉬운 문구로 넣습니다.
```

---

## 14. BE 확인 요청 (ragRefs 콜백 스키마) — Aura 답변

BE가 요청한 **ragRefs 콜백 스키마(필드명) 확정·공유**에 대한 Aura 답변입니다. FE 기대 필드: refId, sourceType, sourceKey, excerpt, score.

| 구분 | Aura 답변 |
|------|-----------|
| **Phase3 콜백** | **analysis.ragRefs** 배열 항목은 **refId, sourceType, sourceKey, excerpt, score** 필드명으로 전달합니다. FE 기대와 동일합니다. |
| **Phase2 콜백** | **finalResult.ragRefs**는 현재 evidence 유래 항목( type, source, caseId, keys 등)을 그대로 넘기며, refId/sourceType/sourceKey/excerpt/score 구조와 다를 수 있습니다. GET analysis 시 FE에서 ragRefs 블록을 표시할 때, Phase2 구간은 해당 필드가 없을 수 있으므로 비표시 처리하시면 됩니다. Phase2에서도 동일 스키마가 필요하면 별도 정리할 수 있습니다. |

### BE 팀에 전달할 답변 문구 (복사용)

```
[Aura] ragRefs 콜백 스키마 확정

■ Phase3 콜백 (analysis.ragRefs)
  - 항목 필드명: refId, sourceType, sourceKey, excerpt, score (FE 기대와 동일)
  - 위 이름으로 확정·전달합니다. BE는 저장·반환 시 동일 필드명 유지하시면 됩니다.

■ Phase2 콜백 (finalResult.ragRefs)
  - 현재는 evidence 유래 구조로, refId/sourceType/sourceKey/excerpt/score 와 다를 수 있습니다.
  - FE는 GET analysis 시 해당 필드가 있는 항목만 ragRefs 블록으로 렌더하시면 됩니다.
  - Phase2에서도 동일 스키마가 필요하면 요청 주시면 정리하겠습니다.
```

---

## 15. FE 최종 정리 (추가 논의 여부)

### FE 쪽 반영 내용 (FE 문서 기준)

- **§2.4 Aura 확인사항** — FE 질문 모두 답변 완료로 정리
- Aura 답변 완료: streamPath / completed / event:agent (§5·§9), Q3 failed retryable·error (§13)
- FE→Aura 질문 미회답 없음
- **§6 요약**: "FE→Aura 질문은 미회답 없음(§2.4). 필수 추가 확인은 1건 — Aura ragRefs 콜백 필드명 확정·공유" 로 명시
- 해당 1건(ragRefs 스키마)은 **§14**에서 BE에게 확정·공유 완료 (refId, sourceType, sourceKey, excerpt, score). FE는 BE 저장·반환 데이터로 동일 필드를 사용하면 됨.

### FE와 추가 논의 필요 여부

- **추가 논의 없음.**  
  FE→Aura 질문은 모두 답변되었고, ragRefs 필드명도 §14로 확정·공유된 상태입니다. FE는 BE GET analysis 응답의 ragRefs를 위 필드명으로 렌더하시면 됩니다.

---

## 16. BE 명시적 회신 (Phase3 internal·콜백 도입 계획)

Aura가 확인을 요청했던 **Phase3 internal 트리거·Phase3 전용 콜백 제공 여부/일정**에 대한 BE 측 명시적 회신입니다. (BE 문서 §6.3)

| 항목 | BE 답변 |
|------|---------|
| **Phase3 internal 트리거** | BE는 **POST /aura/internal/cases/{caseId}/analysis-runs** 를 **쓸 예정**(설정 시). |
| **Phase3 전용 콜백 URL** | **resultCallbackUrl** — 동일 엔드포인트 **POST /api/synapse/internal/aura/callback** 제공. |
| **도입 일정** | 코드 반영 완료. 운영 반영은 **배포·callback-base-url 설정 적용 시점**. |

Aura에서 "Phase3 internal 호출·Phase3 전용 콜백 제공 여부/일정"에 대한 답은 위 §16 및 BE 문서 §6.3으로 확정된 상태입니다.

### BE에 대한 Aura 추가 질문

- **추가 질문 없음.** 위 회신으로 Phase3 연동에 필요한 확인은 모두 마무리되었습니다.

---

## 17. 작업 완료 정리

| 구분 | 상태 |
|------|------|
| **FE → Aura** | FE 질문 모두 답변 완료 (§5·§9·§13). FE 추가 논의 없음 (§15). |
| **BE → Aura** | BE 확인 요청 모두 답변 완료 (§12·§14). |
| **Aura → BE** | Phase3 internal·콜백 도입 계획 BE 명시적 회신 수신 (§16). Aura 추가 질문 없음. |
| **Aura → FE** | 전달 사항 반영·문서 반영 완료. 추가 전달 없음. |

**프론트·Aura·백엔드 간 답변·추가 질문 없이 Phase3 handoff 작업 완료.**
