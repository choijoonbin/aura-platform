# LLM 및 연동 서비스 키 참조

> Aura-Platform에서 사용하는 API 키 및 환경변수 정리

---

## 1. LLM (필수)

### Azure OpenAI ✅ 현재 설정

| 환경변수 | 설명 | 예시 |
|----------|------|------|
| AZURE_OPENAI_ENDPOINT | Azure OpenAI 엔드포인트 URL | https://xxx.openai.azure.com/ |
| AZURE_OPENAI_API_KEY | Azure OpenAI API 키 | (발급받은 키) |
| AZURE_OPENAI_DEPLOYMENT | 배포 이름 (모델) | gpt-4o-mini |
| AZURE_OPENAI_API_VERSION | API 버전 | 2024-02-15-preview |

**사용 가능 deployment**: gpt-4.1, gpt-4.1-mini, gpt-4o, gpt-4o-mini, gpt-5, gpt-5-mini

### OpenAI 직접 연결 (대안)

| 환경변수 | 설명 |
|----------|------|
| OPENAI_API_KEY | OpenAI API 키 (Azure 미사용 시 필수) |
| OPENAI_MODEL | 모델 이름 (기본: gpt-4o-mini) |

---

## 2. RAG / Embedding (향후 사용)

Pinecone, RAG 구현 시 필요. 현재 프로젝트에는 미구현.

| 환경변수 | 설명 |
|----------|------|
| AZURE_OPENAI_EMBEDDING_DEPLOYMENT | Embedding 모델 deployment | text-embedding-3-small, text-embedding-3-large |
| PINECONE_API_KEY | Pinecone 벡터 DB (RAG용) |
| PINECONE_INDEX_NAME | Pinecone 인덱스 이름 |

---

## 3. Observability (선택)

### Langfuse

LLM 트레이싱, 비용 모니터링, 디버깅.

| 환경변수 | 설명 |
|----------|------|
| LANGFUSE_PUBLIC_KEY | Langfuse Public Key |
| LANGFUSE_SECRET_KEY | Langfuse Secret Key |
| LANGFUSE_HOST | Langfuse 서버 (기본: https://cloud.langfuse.com) |

**연동**: LangChain/LangGraph에 Langfuse callback 추가 필요.

### LangSmith

LangChain 공식 트레이싱.

| 환경변수 | 설명 |
|----------|------|
| LANGCHAIN_TRACING_V2 | true 설정 시 활성화 |
| LANGCHAIN_API_KEY | LangSmith API 키 |
| LANGCHAIN_PROJECT | 프로젝트 이름 (예: aura-platform) |

---

## 4. 기타 (이미 설정됨)

| 환경변수 | 용도 |
|----------|------|
| SECRET_KEY / JWT_SECRET | JWT 인증 (필수) |
| REDIS_URL | Redis (HITL, Audit Pub/Sub) |
| SYNAPSE_BASE_URL | Synapse 백엔드 Tool API |
| GITHUB_TOKEN | GitHub 연동 (선택) |

---

## 5. 요약

| 구분 | 필수 | 현재 상태 |
|------|------|-----------|
| **LLM** | ✅ | Azure OpenAI 설정 완료 |
| **RAG/Embedding** | - | 미구현, 필요 시 추가 |
| **Langfuse** | - | 선택, 미설정 |
| **LangSmith** | - | 선택, 미설정 |
| **Pinecone** | - | .cursorrules에 명시, 코드 미구현 |
