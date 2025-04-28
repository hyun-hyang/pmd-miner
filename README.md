# Git Repository PMD Analyzer

이 도구는 Git 저장소의 전체 커밋 히스토리를 따라가면서 PMD(정적 분석 도구)를 실행하고, 결과를 JSON 파일로 수집하는 프로그램입니다. 소프트웨어 저장소 마이닝 연구를 위한 데이터 수집에 사용할 수 있습니다.

## 주요 기능

- 원격 Git 레포지토리 클론 또는 로컬 레포 사용
- 성능 최적화를 위한 JVM 상시 실행 PMD 데몬
- Git 워크트리와 Python 병렬 처리로 커밋별 분석
- 파일 단위 해시 캐시로 재분석 방지
- 커밋별 JSON 결과 및 통합 summary.json 생성
- 멀티 스테이지 Docker로 일관된 빌드 보장

## 사전 요구사항

* Docker 20.10+
* (Optional) Git and Maven for local builds

## Building the Docker Image

```bash
# 캐시 없이 이미지 빌드 및 태그 설정
docker build --no-cache -t pmd-analyzer-daemon .
```

## 실행 방법

#### Docker 컨테이너로 분석 실행

```bash
# 개발용 이미지로 실행 예시 (PowerShell 형식)
docker run --rm `
  -v "${PWD}/analysis_results:/app/analysis_results" `
  -p 8000:8000 `
  pmd-analyzer-dev `
  https://github.com/apache/commons-lang `
  -r /rules/quickstart.xml `
  -o /app/analysis_results `
  -w 4

```
- --rm: 컨테이너 종료 시 자동 삭제

- -v: 호스트 디렉토리 마운트 (결과 저장)

- -p: PMD 데몬 HTTP 포트 매핑

- 이미지 이름: pmd-analyzer-dev 또는 pmd-analyzer-daemon

- 첫 번째 위치 인자: 분석할 Git URL/경로

- -r: 컨테이너 내 룰셋 XML 경로

- -o: 분석 결과 저장 디렉토리

- -w: 병렬 워커 수 (기본은 CPU 코어 수)

> 컨테이너 안에서 PMD Daemon 서버가 자동으로 올라간 후, Python 분석 스크립트가 실행됩니다.

> `output/` 디렉토리는 자동 생성되며, 커밋별 분석 결과 및 `summary.json`이 저장됩니다.

---

## 입력 인자

| 인자명        | 설명                          |
|---------------|-----------------------------|
| `<repo_location>`      | Git 저장소 URL                 |
| `-r, --ruleset`   | PMD 룰셋 XML 파일 경로            |
| `-o, --output-dir`| 결과를 저장할 기본 디렉토리  (필수)            |
| `-w, --workers`  | 사용할 병렬 프로세스 개수 (기본값: CPU 수) |
| `-v, --verbose`  | 디버그 로깅 활성화                  |
| `-q, --quiet`  | PMD 및 네트워크 관련 로그 출력 억제      |

---

## 📁 출력 파일 구조

/app
├── pmd-daemon.jar           # Shaded PMD 데몬 JAR
├── pmd_analyzer_parallel.py # 분석 스크립트
├── rules
│   └── quickstart.xml       # PMD 룰셋
├── pmd-cache.dat            # 선택적 캐시 파일
└── analysis_results         # 마운트된 호스트 결과 디렉토리
    ├── repo_base            # 클론된 레포지토리 베이스
    ├── worktrees            # 워커별 Git worktree
    ├── pmd_results          # 커밋별 JSON 결과
    └── summary.json         # 통합 통계 결과

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

## Worktree 정리

분석 전후에 자동으로 stale worktree를 정리합니다. 수동 정리가 필요하다면:

```bash
# analysis_output/<timestamp> 디렉토리에서 실행
dd
cd analysis_output/<timestamp>
rm -rf worktrees repo_base
```


## 참고

- PMD 공식 사이트: [https://pmd.github.io](https://pmd.github.io)
- 테스트 추천 저장소: [apache/commons-lang](https://github.com/apache/commons-lang)


