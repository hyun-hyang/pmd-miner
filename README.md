# Git Repository PMD Analyzer

이 도구는 Git 저장소의 전체 커밋 히스토리를 따라가면서 PMD(정적 분석 도구)를 실행하고, 결과를 JSON 파일로 수집하는 프로그램입니다. 소프트웨어 저장소 마이닝 연구를 위한 데이터 수집에 사용할 수 있습니다.

## 주요 기능

- Git 저장소의 **모든 커밋**에 대해 자동으로 분석 수행
- 각 커밋마다 **PMD 정적 분석 결과 수집**
- **커밋별 JSON 파일** 생성
- 저장소 전체에 대한 **요약 JSON 파일** 생성
- **병렬 처리** 및 **Worktree 활용**으로 고속 분석
- **파일 해시 캐시**를 통한 중복 분석 방지
- **1.0초/커밋 이하** 성능 목표 충족 가능
- **Docker 컨테이너로 간편 실행 가능**

## 요구사항

* Python 3.8 이상
* Docker (권장)
* Git: 시스템 경로에 `git` 명령어가 등록되어 있어야 합니다.
* Java Runtime Environment (JRE): PMD 실행에 필요합니다. (PMD 버전에 맞는 JRE 버전 확인 필요)

## 설치

1.  **저장소 클론:**
    ```bash
    git clone https://github.com/hyun-hyang/pmd-miner.git
    cd pmd-miner
    ```
2.  **Python 의존성 설치:**
    ```bash
    pip install GitPython
    ```

## 실행 방법

### 1. Docker로 실행 (권장)

#### 1-1. Docker 이미지 빌드
루트 디렉토리(같은 폴더)에 있는 Dockerfile을 기반으로 이미지를 빌드합니다:

```bash
docker build --no-cache -t pmd-analyzer-daemon .      
```

#### 1-2. Docker 컨테이너로 분석 실행

```bash
docker run --rm \
  -v "$(pwd)/analysis_output:/app/analysis_results_parallel" \
  pmd-analyzer \
  https://github.com/apache/commons-lang \
  -r /app/quickstart.xml \
  --aux-jars /opt/libs/junit-4.13.2.jar /opt/libs/commons-lang-2.6.jar \
  -w 8

```
윈도우용)
```bash
docker run --rm -v "${PWD}/analysis_output:/app/analysis_results_parallel" pmd-analyzer-daemon https://github.com/apache/commons-lang --aux-jars /opt/libs/junit-4.13.2.jar:/opt/libs/commons-lang-2.6.jar -o /app/analysis_results_parallel -r /app/quickstart.xml
```

> 컨테이너 안에서 PMD Daemon 서버가 자동으로 올라간 후, Python 분석 스크립트가 실행됩니다.

> `output/` 디렉토리는 자동 생성되며, 커밋별 분석 결과 및 `summary.json`이 저장됩니다.

---

## ⚙️ 입력 인자

| 인자명        | 설명                          |
|---------------|-----------------------------|
| `<repo_location>`      | Git 저장소 URL                 |
| `-r, --ruleset`   | PMD 룰셋 XML 파일 경로            |
| `-o, --output-dir`| 결과를 저장할 기본 디렉토리  (필수)            |
| `--aux-jars`  | PMD 분석에 필요한 추가 JAR 파일 리스트   |
| `-w, --workers`  | 사용할 병렬 프로세스 개수 (기본값: CPU 수) |
| `-v, --verbose`  | 디버그 로깅 활성화                  |
| `-q, --quiet`  | PMD 및 네트워크 관련 로그 출력 억제      |

---

## 📁 출력 파일 구조

- repo_base/ — 클론된 Git 저장소

- worktrees/ — 임시 Git worktree 디렉토리

- pmd_results/ — 커밋별 JSON 분석 결과

- summary.json — 전체 통계 요약 파일

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

## 정리 및 주의사항

분석 완료 후 임시 worktree 디렉토리는 자동 정리됩니다.

중간에 강제 종료한 경우, 수동으로 다음 명령어로 정리할 수 있습니다.

```bash
cd your/output/path/repo_base
git worktree prune

```


## 참고

- PMD 공식 사이트: [https://pmd.github.io](https://pmd.github.io)
- 테스트 추천 저장소: [apache/commons-lang](https://github.com/apache/commons-lang)


