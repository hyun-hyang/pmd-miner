# Git Repository PMD Analyzer

이 도구는 지정된 Git 저장소의 커밋 히스토리를 따라가며 각 커밋 시점의 소스 코드에 대해 PMD 정적 분석을 수행하고, 그 결과를 수집 및 요약합니다. 소프트웨어 리포지토리 마이닝 연구 등에 활용될 수 있습니다.

## 주요 기능

* Git 저장소의 모든 커밋을 순회하며 분석 수행
* 각 커밋별 PMD 분석 결과를 개별 JSON 파일로 저장 (R7)
* 전체 분석 결과에 대한 통계 요약 JSON 파일 생성 (R8)
* 사용자 정의 PMD 규칙셋 사용 가능 (R9)
* 분석할 Git 저장소 위치 지정 가능 (R5)
* 결과 저장 위치 지정 가능 (선택 사항)

## 요구사항

* Python 3.7 이상
* Git: 시스템 경로에 `git` 명령어가 등록되어 있어야 합니다.
* Java Runtime Environment (JRE): PMD 실행에 필요합니다. (PMD 버전에 맞는 JRE 버전 확인 필요)
* PMD: [PMD 공식 사이트](https://pmd.github.io/)에서 다운로드 및 설치 필요.

## 설치

1.  **저장소 클론:**
    ```bash
    git clone <your_repository_url>
    cd <repository_directory>
    ```
2.  **Python 의존성 설치:**
    ```bash
    pip install GitPython
    ```
3.  **PMD 다운로드:** [PMD Releases](https://github.com/pmd/pmd/releases) 에서 최신 바이너리 배포판(`pmd-bin-X.Y.Z.zip`)을 다운로드 받고 압축을 해제합니다.

## 사용법

```bash
python pmd_analyzer.py <git_repo_url_or_path> -p <path_to_pmd_executable> -r <path_to_ruleset.xml> [-o <output_directory>]



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


