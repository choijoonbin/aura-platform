# Docker Compose Redis 설정 가이드

Aura-Platform이 dwp_backend의 Docker Compose로 실행 중인 Redis를 사용하는 방법입니다.

## 🐳 Docker Compose Redis 사용 (권장)

dwp_backend 프로젝트에서 Docker Compose로 Redis가 이미 실행 중인 경우, 별도 설치 없이 바로 사용할 수 있습니다.

### 1. Redis 컨테이너 확인

```bash
# dwp_backend 프로젝트로 이동
cd /path/to/dwp-backend

# Docker Compose 상태 확인
docker-compose ps

# 예상 출력:
# NAME                IMAGE               STATUS              PORTS
# dwp-postgres        postgres:15         Up                  0.0.0.0:5432->5432/tcp
# dwp-redis           redis:7             Up                  0.0.0.0:6379->6379/tcp
```

### 2. Redis 시작 (필요 시)

```bash
# Redis만 시작 (다른 서비스는 제외)
docker-compose up -d redis

# 또는 전체 인프라 시작
docker-compose up -d

# 실행 상태 확인
docker-compose ps | grep redis
```

### 3. Redis 연결 테스트

```bash
# 방법 1: redis-cli 직접 연결 (로컬에 redis-cli 설치된 경우)
redis-cli -h localhost -p 6379 ping
# 응답: PONG

# 방법 2: Docker 컨테이너 내부에서 테스트
docker exec -it dwp-redis redis-cli ping
# 응답: PONG

# 방법 3: Python으로 테스트
python3 -c "
import redis
r = redis.Redis(host='localhost', port=6379, db=0)
print('PONG' if r.ping() else 'FAILED')
"
```

### 4. Aura-Platform 환경 변수 설정

`.env` 파일에서 Redis URL을 설정합니다:

```bash
# .env 파일
REDIS_URL=redis://localhost:6379/0
```

**설명**:
- `localhost:6379`: Docker Compose Redis의 호스트와 포트
- `/0`: Redis 데이터베이스 번호 (0번 사용)

### 5. Redis 데이터 확인

```bash
# Redis 컨테이너 내부에서
docker exec -it dwp-redis redis-cli

# Redis CLI에서:
127.0.0.1:6379> KEYS *
127.0.0.1:6379> GET <key>
127.0.0.1:6379> INFO
127.0.0.1:6379> exit
```

## 🔄 dwp_backend와 Redis 공유

### 장점

1. **인프라 통합**: 하나의 Redis 인스턴스로 모든 서비스 관리
2. **리소스 효율**: 별도 Redis 설치 불필요
3. **일관성**: 개발 환경과 프로덕션 환경 구조 일치
4. **이벤트 버스**: Redis Pub/Sub을 통한 서비스 간 이벤트 전파

### 주의사항

1. **데이터베이스 분리**: 
   - Aura-Platform은 DB 0번 사용
   - dwp_backend는 다른 DB 번호 사용 가능
   - 또는 키 네임스페이스로 분리 (예: `aura:*`, `dwp:*`)

2. **포트 충돌**:
   - Docker Compose Redis는 `localhost:6379`에서 실행
   - 로컬에 별도 Redis가 설치되어 있으면 포트 충돌 가능
   - 해결: 로컬 Redis 중지 또는 다른 포트 사용

3. **의존성**:
   - dwp_backend의 Docker Compose가 실행 중이어야 함
   - Redis 컨테이너가 중지되면 Aura-Platform도 Redis 연결 실패

## 🛠️ 문제 해결

### 문제 1: Redis 연결 실패

**증상**: `Connection refused` 또는 `redis.exceptions.ConnectionError`

**해결**:
```bash
# 1. Redis 컨테이너 확인
docker ps | grep redis

# 2. Redis 컨테이너가 없으면 시작
cd /path/to/dwp-backend
docker-compose up -d redis

# 3. Redis 포트 확인
docker-compose ps | grep redis
# 예상: 0.0.0.0:6379->6379/tcp

# 4. 연결 테스트
docker exec -it dwp-redis redis-cli ping
```

### 문제 2: 포트 충돌

**증상**: `Address already in use` 또는 포트 6379 사용 중

**해결**:
```bash
# 1. 포트 사용 확인
lsof -i :6379

# 2. 로컬 Redis 중지 (Docker Compose 사용 시)
brew services stop redis

# 3. 또는 Docker Compose Redis 포트 변경
# docker-compose.yml에서:
# ports:
#   - "6380:6379"  # 외부 포트를 6380으로 변경
# 
# Aura-Platform .env:
# REDIS_URL=redis://localhost:6380/0
```

### 문제 3: Redis 데이터 초기화

**증상**: Redis 데이터를 완전히 삭제하고 싶은 경우

**해결**:
```bash
# 주의: 모든 Redis 데이터가 삭제됩니다!
docker exec -it dwp-redis redis-cli FLUSHALL

# 또는 특정 DB만 초기화
docker exec -it dwp-redis redis-cli -n 0 FLUSHDB
```

## 📊 Redis 모니터링

### Redis 정보 확인

```bash
# Redis 서버 정보
docker exec -it dwp-redis redis-cli INFO

# 메모리 사용량
docker exec -it dwp-redis redis-cli INFO memory

# 연결 정보
docker exec -it dwp-redis redis-cli INFO clients

# 키 개수
docker exec -it dwp-redis redis-cli DBSIZE
```

### Redis 로그 확인

```bash
# Docker Compose 로그
cd /path/to/dwp-backend
docker-compose logs -f redis

# 또는 Docker 로그
docker logs -f dwp-redis
```

## 🔐 보안 고려사항

### 개발 환경

- Redis는 기본적으로 비밀번호 없이 실행됩니다.
- `localhost`에서만 접근 가능하므로 개발 환경에서는 안전합니다.

### 프로덕션 환경

프로덕션 환경에서는 다음을 고려해야 합니다:

1. **비밀번호 설정**:
   ```yaml
   # docker-compose.yml
   redis:
     command: redis-server --requirepass your_strong_password
   ```

2. **네트워크 격리**:
   - Docker 네트워크를 사용하여 외부 접근 차단
   - 필요한 서비스만 Redis에 접근 가능하도록 설정

3. **TLS/SSL**:
   - 프로덕션 환경에서는 TLS 암호화 사용 권장

## 📚 참고 자료

- [Docker Compose 공식 문서](https://docs.docker.com/compose/)
- [Redis 공식 문서](https://redis.io/docs/)
- [dwp_backend Docker Compose 설정](../dwp-backend/docker-compose.yml)

---

**✅ Docker Compose Redis를 사용하면 별도 설치 없이 바로 시작할 수 있습니다!**
