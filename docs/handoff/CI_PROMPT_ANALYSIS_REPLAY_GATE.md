# CI 협의 프롬프트 (Analysis Replay Gate 연동)

## 목적
배포 전 RAG 리플레이 품질 기준을 자동 검증하고 기준 미달 시 배포 차단

## Aura 실행 커맨드
```bash
python3 tools/analysis_replay_gate.py \
  --cases docs/prompts/golden_rag_cases.json \
  --tenant-id 1 \
  --doc-ids 23,26 \
  --top-k 5 \
  --threshold 0.70 \
  --max-zero-rate 0.20 \
  --min-hit-at-k 0.70 \
  --min-strict-top1 0.45 \
  --out artifacts/analysis_replay_gate.json
```

- Exit code `0`: gate pass
- Exit code `2`: gate fail (배포 차단)

## GitHub Actions 예시
```yaml
name: analysis-replay-gate
on:
  workflow_dispatch:
  pull_request:
    branches: [main]

jobs:
  replay-gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install deps
        run: pip install -r requirements.txt
      - name: Run replay gate
        run: |
          python3 tools/analysis_replay_gate.py \
            --cases docs/prompts/golden_rag_cases.json \
            --tenant-id 1 \
            --doc-ids 23,26 \
            --threshold 0.70 \
            --max-zero-rate 0.20 \
            --min-hit-at-k 0.70 \
            --min-strict-top1 0.45 \
            --out artifacts/analysis_replay_gate.json
      - name: Upload report
        uses: actions/upload-artifact@v4
        with:
          name: analysis-replay-gate
          path: artifacts/analysis_replay_gate.json
```

## Jenkins pipeline 예시
```groovy
stage('Analysis Replay Gate') {
  steps {
    sh '''
      python3 tools/analysis_replay_gate.py \
        --cases docs/prompts/golden_rag_cases.json \
        --tenant-id 1 \
        --doc-ids 23,26 \
        --threshold 0.70 \
        --max-zero-rate 0.20 \
        --min-hit-at-k 0.70 \
        --min-strict-top1 0.45 \
        --out artifacts/analysis_replay_gate.json
    '''
    archiveArtifacts artifacts: 'artifacts/analysis_replay_gate.json', fingerprint: true
  }
}
```

