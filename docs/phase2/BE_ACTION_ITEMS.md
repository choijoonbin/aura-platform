# BE 측 스트림 처리 필수 조치 사항

## ✅ BE 반영 완료 (2026-02 기준)

BE 팀에서 Aura 문서에 맞춰 수정 반영함.

| Aura 문서 항목 | BE 반영 상태 |
|----------------|-------------|
| **Streaming: ofLines()** | ✅ `BodyHandlers.ofInputStream()` + 바이트 루프 → **`BodyHandlers.ofLines()`** 로 변경. 라인 단위 스트리밍 수신 후 `(line + "\n").getBytes(UTF_8)` 로 FE 전달. |
| Read timeout 5분 이상 | ✅ 기존 30분 유지 |
| Connection 헤더 | ⚠️ Java HttpClient restricted header — **설정하지 말 것**. HTTP/1.1 시 keep-alive 기본. |
| HTTP/1.1 전용 | ✅ 기존 `HttpClient.Version.HTTP_1_1` |
| totalBytesForwarded 로그 | ✅ 기존 + 종료 시 lineCount 포함 |
| 즉시 FE 전달 | ✅ 청크 단위 `emitter.send(ByteBuffer.wrap(chunk))` |
| Aura 응답 읽기 로그 | ✅ DEBUG: `SSE line received`, 첫 라인: `SSE proxy first line received` |

**변경 요약 (AnalysisStreamProxyService)**  
- `HttpResponse.BodyHandlers.ofLines()` 사용, `response.body()` → `Stream<String>`, try-with-resources + Iterator 로 라인별 처리.  
- 각 라인에 `"\n"` 붙여 UTF-8 바이트로 변환 후 `emitter.send(ByteBuffer.wrap(chunk))` 호출.

**재테스트 시 확인**  
- BE 로그: `SSE proxy first line received`, `totalBytesForwarded > 0`, `lineCount > 0`  
- FE: 스트림 이벤트 수신 여부

### 스트림 "곧바로 끊김" 원인 — FE 조기 종료 (BE 확인 결과)

BE 확인 결과, **BE는 스트림을 먼저 끊지 않음.**  
- 끊김 순서: **FE(브라우저)가 먼저 연결 종료** → BE `emitter.send()` 시 IllegalStateException → BE가 Aura 읽기 루프 break → Aura 측에서 "클라이언트가 끊었다"로 보임.  
- totalBytesForwarded=12, lineCount=1 등으로 첫 줄은 수신·전달된 상태.  
- **권장:** FE에서 EventSource/스트림을 끝까지 유지하는지, 첫 이벤트 수신 후 닫는 로직이 있는지 확인.

---

## 📋 현상 요약 (과거)

- **증상**: Aura 스트림 API 응답이 비어 있음 (200 OK이나 body가 0 bytes)
- **원인**: BE의 HTTP 클라이언트가 **연결 후 8ms 만에 즉시 종료** (스트리밍 읽기 미지원)
- **확인**: Aura 직접 호출 시 정상 동작 → **BE HTTP 클라이언트 문제**

## ✅ Aura 측 완료 조치

1. ✅ BaseHTTPMiddleware 완전 제거 (스트림 경로)
2. ✅ 연결 즉시 이벤트 전송 (`: connected` + `event: started`)
3. ✅ 검증 스크립트 제공 (`scripts/test_stream_direct.py`)

→ **Aura는 정상 동작 확인됨. 이제 BE 측 수정 필요.**

---

## 🔧 BE 측 필수 수정 사항

### 1. **Streaming HTTP Client 사용** ⭐⭐⭐

현재 BE 코드가 아마 이렇게 되어 있을 것:

```java
// ❌ 잘못된 방식 - 전체 응답 대기
HttpResponse<String> response = client.send(request, 
    BodyHandlers.ofString());
String body = response.body();  // 스트림 끝날 때까지 블록
```

**올바른 방식 (스트리밍 읽기)**:

```java
// ✅ 방법 1: 라인 단위 스트리밍
HttpResponse<Stream<String>> response = client.send(request,
    BodyHandlers.ofLines());

response.body().forEach(line -> {
    // SSE 라인을 받는 즉시 처리
    if (line.startsWith("event:")) {
        // event 타입 추출
    } else if (line.startsWith("data:")) {
        // JSON 파싱 후 FE로 전달
    }
});
```

```java
// ✅ 방법 2: Subscriber 패턴
HttpResponse<Void> response = client.send(request,
    BodyHandlers.fromLineSubscriber(new Flow.Subscriber<String>() {
        @Override
        public void onNext(String line) {
            // 각 라인을 받는 즉시 처리
            processSSELine(line);
        }
        
        @Override
        public void onComplete() {
            // 스트림 종료
        }
        
        @Override
        public void onError(Throwable throwable) {
            // 에러 처리
        }
    }));
```

### 2. **Read Timeout 충분히 설정** ⭐⭐

SSE는 장시간 연결이 유지되어야 합니다 (몇 초~몇 분).

```java
HttpClient client = HttpClient.newBuilder()
    .connectTimeout(Duration.ofSeconds(10))     // 연결 타임아웃
    .version(HttpClient.Version.HTTP_1_1)       // HTTP/1.1 고정
    .build();

HttpRequest request = HttpRequest.newBuilder()
    .uri(URI.create(streamUrl))
    .timeout(Duration.ofMinutes(5))              // ⭐ Read timeout 5분
    .header("Authorization", authToken)
    .GET()
    .build();
```

**중요**: `timeout()`은 **전체 요청 타임아웃**이 아니라 **읽기 타임아웃**입니다. 스트림이 5분간 데이터를 보내면 5분 동안 연결이 유지되어야 합니다.

### 3. **FE로 즉시 전달 (버퍼링 금지)** ⭐

BE는 Aura에서 받은 SSE 라인을 **즉시 FE로 전달**해야 합니다.

```java
// ❌ 잘못된 방식 - 모두 모아서 한 번에
List<String> lines = new ArrayList<>();
response.body().forEach(lines::add);
return String.join("\n", lines);  // 스트림 끝날 때까지 대기

// ✅ 올바른 방식 - 받는 즉시 전달
response.body().forEach(line -> {
    outputStream.write((line + "\n").getBytes());
    outputStream.flush();  // ⭐ 즉시 flush
});
```

### 4. **Connection 헤더는 설정하지 말 것** (BE 측)

Java `HttpClient`는 **`Connection`을 restricted header로 관리**합니다.  
앱에서 `.header("Connection", "keep-alive")` 를 설정하면 **`IllegalArgumentException: restricted header name: "Connection"`** 이 발생합니다.

- **조치**: `Connection` 헤더를 **설정하지 말 것**.  
- **이유**: HTTP/1.1 (`HttpClient.Version.HTTP_1_1`) 사용 시 keep-alive는 **기본 동작**이며, HttpClient가 알아서 처리합니다.

```java
HttpRequest request = HttpRequest.newBuilder()
    .uri(streamUri)
    .header("Authorization", authToken)
    // .header("Connection", "keep-alive")  // ❌ 설정 금지 — restricted header
    .header("Accept", "text/event-stream")
    .GET()
    .build();
```

---

## 🧪 검증 방법

### 1단계: Aura 직접 호출로 정상 동작 확인

```bash
# Python 검증 스크립트 (Aura 저장소)
cd /path/to/aura-platform
python scripts/test_stream_direct.py

# 또는 curl
curl -N http://localhost:9000/aura/cases/85115/analysis/stream?runId=<RUN_ID> \
  -H "Authorization: Bearer test-token"
```

**예상 출력** (정상):
```
: connected

event: started
data: {"status":"started","runId":"...","caseId":"85115"}

event: step
data: {"stepName":"retrieve_evidence",...}

event: completed
data: {"status":"completed","score":85,...}

data: [DONE]
```

→ **이렇게 나오면 Aura는 정상**. BE 클라이언트가 이렇게 읽어야 함.

### 2단계: BE 로그 확인

`AnalysisStreamProxyService` 로그에서:

```
✅ 정상: totalBytesForwarded > 0  (예: 1000 bytes)
❌ 문제: totalBytesForwarded = 0  (BE가 바이트를 못 받음)
```

### 3단계: BE → Aura 읽기 로그 추가

BE에서 Aura 응답을 읽을 때마다 로그:

```java
int bytesRead = 0;
response.body().forEach(line -> {
    bytesRead += line.length();
    logger.info("SSE line received: {} bytes, total: {}", line.length(), bytesRead);
    // FE로 전달
});
logger.info("Stream finished, total bytes: {}", bytesRead);
```

---

## 📚 참고 자료

### Java HttpClient Streaming 예제

```java
import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import java.util.stream.Stream;

public class SSEStreamExample {
    public static void main(String[] args) throws Exception {
        HttpClient client = HttpClient.newBuilder()
            .version(HttpClient.Version.HTTP_1_1)
            .connectTimeout(Duration.ofSeconds(10))
            .build();
        
        HttpRequest request = HttpRequest.newBuilder()
            .uri(URI.create("http://localhost:9000/aura/cases/85115/analysis/stream?runId=test"))
            .timeout(Duration.ofMinutes(5))
            .header("Authorization", "Bearer test-token")
            .GET()
            .build();
        
        // 스트리밍 읽기
        HttpResponse<Stream<String>> response = client.send(request,
            HttpResponse.BodyHandlers.ofLines());
        
        System.out.println("Status: " + response.statusCode());
        System.out.println("Content-Type: " + response.headers().firstValue("content-type"));
        
        // 각 라인 처리
        response.body().forEach(line -> {
            System.out.println(line);
            // FE로 전달 로직
        });
    }
}
```

### Spring WebFlux (Reactive) 예제

```java
@GetMapping(value = "/stream-proxy", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
public Flux<String> proxyStream(@RequestParam String runId) {
    String auraUrl = "http://localhost:9000/aura/cases/85115/analysis/stream?runId=" + runId;
    
    return webClient.get()
        .uri(auraUrl)
        .header("Authorization", "Bearer " + token)
        .retrieve()
        .bodyToFlux(String.class);  // 스트리밍으로 받아 바로 반환
}
```

---

## 🎯 체크리스트

BE 개발자가 확인할 사항:

- [ ] `BodyHandlers.ofLines()` 또는 `BodyHandlers.fromLineSubscriber()` 사용
- [ ] `timeout(Duration.ofMinutes(5))` 이상 설정
- [ ] 받은 라인을 **즉시 FE로 전달** (버퍼링 X)
- [ ] `totalBytesForwarded` 로그가 0보다 큰지 확인
- [ ] Aura 직접 호출 시 데이터가 나오는지 확인 (`curl -N` 또는 검증 스크립트)
- [ ] BE에서 Aura 응답 읽기 로그 추가 (디버깅용)

---

## 💬 추가 지원

질문이나 추가 로그가 필요하면 Aura 팀에 연락:
- 디버그 문서: `docs/phase2/ANALYSIS_STREAM_DEBUG.md`
- 검증 스크립트: `scripts/test_stream_direct.py`
