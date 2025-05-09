# Git Repository **PMD Analyzer**

> **대규모 Java 저장소의 모든 커밋을 PMD로 분석**하여 JSON 결과를 수집‑집계하는 연구용 도구입니다.  
> "저장소 마이닝"·"정적 분석 기반 품질 추세 연구"와 같은 실험을 완전 자동화된 컨테이너 하나로 수행할 수 있습니다.

---

## 주요 기능

| 기능 | 설명 |
|------|------|
| **원격/로컬 레포 지원** | Git URL 또는 로컬 경로 어떤 것이든 입력하면 자동으로 분석합니다. |
| **JVM 상시 실행 PMD 데몬** | JVM 부팅 오버헤드를 제거, 커밋 수천 개도 빠르게 처리합니다. |
| **Python 멀티프로세싱** | 커밋 단위 병렬 분석 → CPU 코어 수에 비례해 선형 가속. |
| **파일 해시 캐시** | 같은 파일 해시가 재등장하면 재분석을 건너뛰어 시간을 절약합니다. |
| **커밋별 JSON + 통합 `summary.json`** | 후속 통계 작업, 시각화, ML 학습 데이터로 바로 활용 가능. |
| **멀티스테이지 Docker 빌드** | "빌드 환경 ≠ 실행 환경" 문제를 근본적으로 차단합니다. |

---

## 빠른 시작

### 1. 사전 요구사항

* **Docker 20.10+** (필수)
* Git · Maven (로컬 직접 빌드 시 선택)

### 2. Docker 이미지 빌드

```bash
# 캐시 없이 최신 소스로 이미지 빌드
docker build --no-cache -t pmd-analyzer:dev .
```

### 3. 실행 방법

#### Docker 컨테이너로 분석 실행

```bash
# 개발용 이미지로 실행 예시 (PowerShell 형식)
docker run --rm `
  -v "${PWD}/analysis_results:/app/analysis_results" `
  pmd-analyzer-dev `
  https://github.com/apache/commons-lang `
  -r rules/quickstart.xml `
  -o analysis_results `

```
> **필수 옵션 요약**
> * `-v` : 분석 결과를 호스트에 영구 저장할 디렉터리 마운트  
> * 첫 번째 위치 인자 : 분석할 Git **URL 또는 경로**  
> * `-r / --ruleset` : 컨테이너 내부 규칙셋 경로  
> * `-o / --output-dir` : 결과 디렉터리 이름  
> * `-w / --workers` : 동시 워커 수(기본 = CPU 코어)

컨테이너 내부에서 **PMD Daemon**(포트 5000)이 먼저 기동되고 준비되면 Python Analyzer가 히스토리를 순회합니다.


---

## CLI 옵션
| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `<repo_location>` | 분석 대상 Git URL 또는 로컬 경로 | – |
| `-r, --ruleset` | PMD 룰셋 XML 경로 | `rules/quickstart.xml` |
| `-o, --output-dir` | 결과 저장 디렉터리(필수) | – |
| `-w, --workers` | 병렬 프로세스 개수 | CPU 코어 수 |
| `-v, --verbose` | 디버그 로그 활성화 | 꺼짐 |
| `-q, --quiet` | PMD·네트워크 로그 최소화 | 꺼짐 |

---

## 결과 구조
```
analysis_results/
├── repo_base/          # 클론한 원본 저장소 (read‑only)
├── worktrees/          # 커밋별 Git worktree (자동 정리)
├── pmd_results/        # <commit>.json PMD 결과 모음
└── summary.json        # 통합 통계
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

# Architecture & Design Decisions

## 개요
본 프로젝트는 **PMD** 정적 분석 규칙으로 대규모 Java 저장소의 과거 커밋을 일괄 분석하는 파이프라인을 제공합니다. CI/CD 환경에 바로 포함될 수 있도록 **컨테이너 우선(Container‑first)** 원칙으로 설계되었으며, 다음과 같은 두 개의 장기 실행 서비스와 하나의 조정 계층으로 구성됩니다.

```
┌────────────┐   HTTP / JSON   ┌────────────────┐   멀티프로세스   ┌──────────────┐
│ Python     │ ──────────────▶ │   Java PMD     │ ───────────────▶ │    PMD       │
│ Analyzer   │                 │    Daemon      │                 │  Core API    │
└────────────┘◀──────────────  └────────────────┘◀───────────────┘
```

* **Java PMD 데몬**: JVM 내부에서 PMD Core API 를 직접 호출하며, HTTP REST 엔드포인트(`/analyze`)를 통해 분석 요청을 받습니다.
* **Python Analyzer**: Git 히스토리를 순회하며 각 커밋을 데몬에 전달하고 결과를 집계합니다.
* **Docker 조정 계층**: 멀티스테이지 이미지를 사용해 두 서비스를 하나의 컨테이너 안에서 orchestration 합니다.


---

# Performance & Scalability

| 전략 | 효과 |
|------|------|
| **JVM 상시 실행** | 데몬 웜업 이후 CLI 대비 평균 처리 시간 30 %↓ |
| **멀티프로세싱 8‑proc** | 5 k 커밋 분석 ≈ **13 분** (CLI 루프 대비 5× 가속) |
| **클래스패스 캐싱** | 외부 라이브러리 재파싱 제거 → 추가 10 % 속도 향상 |
| **멀티스테이지 이미지** | 크기 230 MB → 95 MB 로 축소, CI/CD 캐시 부담 완화 |

---

## 정리 & 주의 사항
* 분석 완료 시 **worktree** 디렉터리는 자동 정리됩니다.
* 강제 종료했다면 다음 명령으로 잔여 worktree 를 정리할 수 있습니다.
  ```bash
  cd analysis_results/repo_base
  git worktree prune
  ```

---

## 기여하기
1. Issue 또는 Pull Request 열기 →  eslint / maven‑checkstyle 통과 필수  
2. 새로운 룰셋·성능 최적화·CI 워크플로 환영


## 라이선스
MIT License — 자유롭게 사용·수정·배포 가능하나, **연구 결과 인용 시 본 프로젝트를 레퍼런스** 해주세요.

---


## 참고 링크
* **PMD**: <https://pmd.github.io>
* 테스트용 대형 저장소: <https://github.com/apache/commons-lang>


