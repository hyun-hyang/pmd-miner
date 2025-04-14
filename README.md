# 🛠️ PMD Repository Miner

Java Git 저장소를 분석하여, 각 커밋에 대해 PMD 정적 분석 결과를 수집하고 통계 요약을 제공하는 자동화 도구입니다.

---

## 📦 주요 기능

- Git 저장소를 커밋 단위로 순회  
- 각 커밋에서 PMD 분석 수행  
- 커밋별 JSON 결과 저장  
- 전체 저장소에 대한 품질 요약 통계 생성

---

## 🚀 실행 방법 (Docker 기반)

### 1. Docker 이미지 빌드

```bash
docker build -t pmd-miner .
```

### 2. 프로그램 실행

```bash
docker run --rm -v $(pwd)/output:/app/output pmd-miner \
  --repo https://github.com/apache/commons-lang \
  --ruleset ruleset.xml \
  --output_dir output
```

> `output/` 디렉토리는 자동 생성되며, 커밋별 분석 결과 및 `summary.json`이 저장됩니다.

---

## ⚙️ 입력 인자

| 인자명        | 설명                             | 필수 여부 |
|---------------|----------------------------------|------------|
| `--repo`      | Git 저장소 URL                   | ✅         |
| `--ruleset`   | PMD 룰셋 XML 파일 경로           | ✅         |
| `--output_dir`| JSON 출력 폴더 경로              | ✅         |
| `--temp_dir`  | 임시 클론 저장 폴더 (기본: `./temp_repo`) | ❌ |

---

## 📁 출력 파일 구조

```
output/
├── <commit_hash1>.json
├── <commit_hash2>.json
└── summary.json
```

### `summary.json` 예시

```json
{
  "location": "/app/output",
  "stat_of_repository": {
    "number_of_commits": 123,
    "avg_of_num_java_files": 42.3,
    "avg_of_num_warnings": 198.1
  },
  "stat_of_warnings": {
    "UnusedPrivateField": 1320,
    "AvoidCatchingGenericException": 982
  }
}
```

---

## 📝 참고

- PMD 공식 사이트: [https://pmd.github.io](https://pmd.github.io)
- 테스트 추천 저장소: [apache/commons-lang](https://github.com/apache/commons-lang)


