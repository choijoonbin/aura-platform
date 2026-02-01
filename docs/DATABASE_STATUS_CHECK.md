# 데이터베이스 상태 점검 결과

> **점검 일시**: 2026-01-16  
> **점검 대상**: PostgreSQL 데이터베이스 (dwp-postgres 컨테이너)

---

## ✅ 점검 결과 요약

### 1. 데이터베이스 존재 여부

**`dwp_auth` 데이터베이스**: ✅ **존재함**

```sql
SELECT datname FROM pg_database WHERE datname LIKE '%auth%';
```

**결과**:
- `dwp_auth` 데이터베이스 존재 확인
- 소유자: `dwp_user`
- 인코딩: UTF8

---

### 2. 테이블 존재 여부

**테이블 개수**: ✅ **23개 테이블 존재**

주요 테이블 목록:
- `com_audit_logs` - 감사 로그
- `com_departments` - 부서 정보
- `com_permissions` - 권한 정보
- `com_resources` - 리소스 정보
- `com_role_members` - 역할 멤버
- `com_role_permissions` - 역할 권한
- `com_roles` - 역할 정보
- `com_tenants` - 테넌트 정보
- `com_user_accounts` - 사용자 계정
- `com_users` - 사용자 정보
- `flyway_schema_history` - Flyway 마이그레이션 이력
- `sys_api_call_histories` - API 호출 이력
- `sys_auth_policies` - 인증 정책
- `sys_code_groups` - 코드 그룹
- `sys_code_usages` - 코드 사용
- `sys_codes` - 코드 정보
- `sys_event_logs` - 이벤트 로그

---

### 3. Flyway 마이그레이션 상태

**마이그레이션 상태**: ✅ **완료됨**

```sql
SELECT version, description, installed_on 
FROM flyway_schema_history 
ORDER BY installed_rank DESC;
```

**결과**:
- Version: `1`
- Description: `create iam schema`
- Installed On: `2026-01-21 11:41:27.44413`

---

## 🔍 상세 점검 내용

### PostgreSQL 컨테이너 정보

- **컨테이너 이름**: `dwp-postgres`
- **이미지**: `postgres:15-alpine`
- **상태**: ✅ 실행 중 (Up 25 hours, healthy)
- **포트**: `0.0.0.0:5432->5432/tcp`

### 환경 변수

```
POSTGRES_DB=postgres
POSTGRES_USER=dwp_user
POSTGRES_PASSWORD=dwp_password
PGDATA=/var/lib/postgresql/data
```

### 초기화 스크립트

초기화 스크립트 위치: `/Users/joonbinchoi/Work/dwp/dwp-backend/docker/postgres/init.sql`

생성되는 데이터베이스:
- `dwp_auth` ✅
- `dwp_main`
- `dwp_mail`
- `dwp_chat`
- `dwp_approval`

---

## ⚠️ 발견된 이슈

### 1. 로그 오류 (과거 이력)

PostgreSQL 로그에서 일부 오류가 발견되었지만, 모두 과거 이력이며 현재는 정상 작동 중입니다:

- `ERROR: column "display_name" does not exist` (2026-01-20)
- `ERROR: function lower(bytea) does not exist` (2026-01-20)
- `ERROR: database "dwp_auth" is being accessed by other users` (2026-01-21)
- `ERROR: relation "com_tenants" already exists` (2026-01-21)

**분석**: 이러한 오류들은 데이터베이스 재생성 시도나 마이그레이션 실행 중 발생한 것으로 보이며, 현재는 모든 테이블이 정상적으로 생성되어 있습니다.

---

## ✅ 결론

**`dwp_auth` 데이터베이스는 정상적으로 생성되어 있으며, 모든 테이블과 마이그레이션이 완료되었습니다.**

### 확인 사항

1. ✅ 데이터베이스 존재: `dwp_auth` 데이터베이스 존재 확인
2. ✅ 테이블 생성: 23개 테이블 모두 생성 완료
3. ✅ 마이그레이션 완료: Flyway 마이그레이션 v1 완료
4. ✅ 컨테이너 상태: PostgreSQL 컨테이너 정상 실행 중

### 권장 사항

1. **데이터베이스가 보이지 않는 경우**:
   - 데이터베이스 클라이언트(DataGrip 등)에서 올바른 사용자명(`dwp_user`)과 비밀번호(`dwp_password`)를 사용하고 있는지 확인
   - 연결할 데이터베이스 이름이 `dwp_auth`인지 확인

2. **테이블이 보이지 않는 경우**:
   - 스키마가 `public`인지 확인
   - 사용자 권한 확인: `dwp_user`가 모든 테이블에 접근 권한이 있는지 확인

3. **재기동 후 문제가 발생하는 경우**:
   - PostgreSQL 컨테이너가 정상적으로 시작되었는지 확인: `docker ps | grep postgres`
   - 컨테이너 로그 확인: `docker logs dwp-postgres`
   - 데이터베이스 연결 테스트: `docker exec dwp-postgres psql -U dwp_user -d dwp_auth -c "\dt"`

---

## 🔧 데이터베이스 확인 명령어

### 데이터베이스 목록 확인
```bash
docker exec dwp-postgres psql -U dwp_user -d postgres -c "\l"
```

### 특정 데이터베이스의 테이블 목록 확인
```bash
docker exec dwp-postgres psql -U dwp_user -d dwp_auth -c "\dt"
```

### Flyway 마이그레이션 이력 확인
```bash
docker exec dwp-postgres psql -U dwp_user -d dwp_auth -c "SELECT * FROM flyway_schema_history ORDER BY installed_rank DESC;"
```

### 테이블 개수 확인
```bash
docker exec dwp-postgres psql -U dwp_user -d dwp_auth -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE';"
```

---

**최종 업데이트**: 2026-01-16  
**담당자**: Aura-Platform 개발팀
