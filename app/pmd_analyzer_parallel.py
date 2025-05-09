import argparse
import subprocess
import logging
import json
import time
import os
import shutil
from pathlib import Path
from multiprocessing import Pool, Manager, current_process
from datetime import datetime
import requests
from typing import List
import hashlib

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - [%(processName)s] - %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger(__name__)

file_cache = Manager().dict()


def compute_file_hash(path: Path) -> str:
    """
    주어진 파일(Path)의 SHA-1 해시를 계산하여 16진수 문자열로 반환.
    큰 파일도 chunk 단위로 읽어 메모리 과부하를 방지합니다.
    """
    h = hashlib.sha1()
    with path.open('rb') as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def load_cache(cache_path: Path) -> dict:
    """
    파일 해시 → 분석결과 맵을 JSON에서 로드합니다.
    """
    if cache_path.is_file():
        try:
            return json.loads(cache_path.read_text(encoding='utf-8'))
        except Exception as e:
            logger.warning(f"Failed to load cache from {cache_path}: {e}")
    return {}


def save_cache(cache_path: Path, cache: dict):
    """
    메모리상의 캐시 맵을 JSON 파일로 저장합니다.
    """
    try:
        cache_path.write_text(json.dumps(cache, indent=2), encoding='utf-8')
    except Exception as e:
        logger.error(f"Failed to save cache to {cache_path}: {e}")


def get_changed_java_files(prev_hash: str, curr_hash: str, repo_path: Path) -> List[Path]:
    """
    prev_hash → curr_hash 사이에 변경된 .java 파일들의 절대 경로 리스트를 반환.
    prev_hash가 None이면, 워크트리 전체의 .java 파일을 반환.
    """
    if prev_hash is None:
        # 첫 커밋인 경우: 전체 .java 파일
        return list(Path(repo_path).rglob("*.java"))

    # 변경된 파일 목록 조회
    result = run_command(
        ['git', 'diff', '--name-only', '--diff-filter=ACM', prev_hash, curr_hash],
        cwd=repo_path,
        check=True
    )
    files = result.stdout.splitlines()
    # .java 확장자만 필터링
    java_files = [
        Path(f) for f in files
        if f.endswith('.java')
    ]
    return java_files


def run_pmd_analysis_http(worktree_path, ruleset, aux_classpath, timeout=600, files: List[str] = None):
    """
    PMD Daemon에 HTTP POST 요청을 보내고 JSON 리포트를 dict로 반환.
    """
    url = "http://localhost:8000/analyze"
    payload = {
        "path": str(worktree_path),
        "ruleset": str(ruleset),
        "auxClasspath": aux_classpath or "",
        # 변경된 파일 목록이 주어지면 해당 파일만 분석
        **({"files": files} if files is not None else {})
    }
    resp = requests.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def run_command(command, cwd=None, check=True, suppress_stderr=False):
    cmd_str = ' '.join(map(str, command))
    command = [str(part) for part in command]
    logger.debug(f"Running command: {cmd_str} in {cwd or 'default CWD'}")
    stderr_pipe = subprocess.PIPE if not suppress_stderr else subprocess.DEVNULL
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, cwd=cwd, errors='ignore')

        log_level_stdout = logging.DEBUG
        log_level_stderr = logging.WARNING
        if result.returncode != 0:
            log_level_stdout = logging.WARNING if not check else logging.ERROR
            log_level_stderr = logging.ERROR

        if result.stdout and (logger.getEffectiveLevel() <= logging.DEBUG or log_level_stdout >= logging.WARNING):
            logger.log(log_level_stdout, f"Command stdout: {cmd_str}\n{result.stdout.strip()}")

        if result.stderr and not suppress_stderr:
            logger.log(log_level_stderr, f"Command stderr: {cmd_str}\n{result.stderr.strip()}")

        if check and result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, command, output=result.stdout, stderr=result.stderr)

        return result

    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed: {' '.join(map(str, e.cmd))}")
        logger.error(f"Return code: {e.returncode}")
        if e.stdout:
            logger.error(f"Failed Command Output: {e.stdout.strip()}")
        if e.stderr:
            logger.error(f"Failed Command Error Output: {e.stderr.strip()}")
        if check:
            raise
        return e
    except FileNotFoundError:
        logger.error(f"Command not found: {command[0]}")
        raise
    except Exception as e:
        logger.error(f"An unexpected error occurred running command '{cmd_str}': {e}",
                     exc_info=True)  # Add exc_info for full traceback
        raise


def get_commit_hashes(repo_path):
    logger.info("Retrieving commit hashes...")
    try:
        result = run_command(['git', 'log', '--format=%H', '--reverse'], cwd=repo_path)
        hashes = [h for h in result.stdout.strip().split('\n') if h]
        logger.info(f"Found {len(hashes)} commit hashes.")
        return hashes
    except subprocess.CalledProcessError:
        logger.error(f"Failed to get commit hashes from {repo_path}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error getting commit hashes: {e}", exc_info=True)
        return []


def analyze_commit(commit_hash, prev_hash, base_repo_path, worktree_path, pmd_path, ruleset, aux_classpath, output_dir,
                   pmd_results_dir, progress_lock, progress_data, worktree_lock, extra_pmd_flags):
    success_flag = False
    pmd_code = -1
    new_cache_dict = {}

    worker_name = current_process().name
    start_time = time.time()
    commit_short = commit_hash[:8]
    result_file = pmd_results_dir / f"{commit_hash}.json"
    error_file = pmd_results_dir / f"{commit_hash}.error.json"

    # Skip if already done
    if result_file.exists() or error_file.exists():
        with progress_lock:
            progress_data['processed'] += 1
        return commit_hash, 0.0, True, 0, {}

    logger.info(f"[{worker_name}] - Processing commit {commit_short}")

    # Checkout
    try:
        with worktree_lock:
            ok = safe_git_checkout(commit_hash, worktree_path, base_repo_path)
            if not ok:
                raise RuntimeError("git checkout failed after lock-cleanup retries")
    except Exception as e:
        logger.error(f"[{worker_name}] - Git checkout failed for {commit_short}: {e}")
        with open(error_file, 'w', encoding='utf-8') as f:
            json.dump({"commit": commit_hash, "error": "Git checkout failed"}, f, indent=2)
        return commit_hash, 0.0, False, -1, {}

    # Gather only changed Java files since previous commit
    if prev_hash:
        # 리포지터리 기준 상대경로 리스트
        rel_paths = get_changed_java_files(prev_hash, commit_hash, base_repo_path)
        # worktree_path 기준 실제 파일 객체로 변환
        java_files = [worktree_path / rel for rel in rel_paths]
        # 존재하지 않는 파일은 스킵
        missing = [f for f in java_files if not f.exists()]

        if missing:
            logger.warning(f"[{worker_name}] - Missing files (skipped): {missing}")
        java_files = [f for f in java_files if f.exists()]
    else:
        # 첫 커밋일 땐 전체 파일
        java_files = list(Path(worktree_path).rglob("*.java"))

    if not java_files:
        placeholder = {"commit": commit_hash, "num_java_files": 0, "warnings": []}
        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(placeholder, f, indent=2)
        with progress_lock:
            progress_data['processed'] += 1
        return commit_hash, 0.0, True, 0, {}

    # CACHE: 먼저 file_cache(Manager.dict)에서 해시 키로 결과 있는지 확인
    # merged_report 초기화: 실제 java_files 수, warnings 리스트 반영

    merged_report = {
        "commit": commit_hash,
        "num_java_files": len(java_files),
        "warnings_by_rule": {},
        "warnings": []
    }
    to_analyze = []

    for f in java_files:
        # 안전하게 존재 여부 체크
        if not f.exists():
            logger.warning(f"[{worker_name}] - Skipping missing file (pre-cache): {f}")
            continue
        rel = str(f.relative_to(worktree_path))
        try:
            h = compute_file_hash(f)  # CACHE ▶
        except FileNotFoundError:
            logger.warning(f"[{worker_name}] - Cannot hash (pre-cache): {f}, skipping")
            continue

        if h in file_cache:
            entry = file_cache[h]
            # 룰별 카운트를 덧셈으로 합산
            for rule, cnt in entry["warnings_by_rule"].items():
                merged_report["warnings_by_rule"][rule] = (
                        merged_report["warnings_by_rule"].get(rule, 0) + cnt
                )
            merged_report["num_java_files"] += entry["num_java_files"]
        else:
            to_analyze.append(rel)
            # 실제 분석이 필요한 파일만 daemon 호출

    try:
        if not to_analyze:
            logger.info(f"[{worker_name}] No files to analyze for commit {commit_short}. Skipping PMD call.")
        else:
            raw = run_pmd_analysis_http(
                worktree_path, ruleset, aux_classpath, timeout=600,
                files=to_analyze
            )

    except Exception as e:
        # 기존 에러 처리 로직 유지
        logger.error(f"[{worker_name}] - HTTP PMD analysis failed for {commit_short}: {e}")

        with open(error_file, 'w', encoding='utf-8') as f:
            json.dump({"commit": commit_hash, "error": str(e)}, f, indent=2)
        with progress_lock:
            progress_data['processed'] += 1

        return commit_hash, 0.0, False, -1, {}

    file_reports = raw.get("fileReports", raw.get("files", []))

    for fr in file_reports:
        # PMD가 준 상대경로 얻기
        rel = fr.get("file", fr.get("filename"))
        file_path = worktree_path / rel

        if not file_path.exists():
            logger.warning(f"[{worker_name}] - Skipping missing file (post-PMD): {file_path}")
            continue
        try:
            fh = compute_file_hash(file_path)
        except FileNotFoundError:
            logger.warning(f"[{worker_name}] - Cannot hash (post-PMD): {file_path}, skipping")
            continue

        if not rel:
            # 키 이름이 또 다를 경우 로그 남기고 스킵
            logger.warning(f"Unknown file key in PMD report: {fr.keys()}")
            continue
        # violations 목록에서 rule별 카운트 집계
        vb = {}

        for v in fr.get("violations", []):
            rule = v.get("rule") or v.get("ruleSet") or "UNKNOWN"
            vb[rule] = vb.get(rule, 0) + 1
        # 이 해시는 파일 하나이므로 num_java_files=1
        file_cache[fh] = {
            "warnings_by_rule": vb,
            "num_java_files": 1
        }
        # merge violations list
        if "violations" in raw and isinstance(raw["violations"], list):
            merged_report["warnings"] = raw["violations"]
        else:
            # flatten per-file violations
            vs = []
            for fr in file_reports:
                vs.extend(fr.get("violations", []))
            merged_report["warnings"] = vs

        # carry through metadata and detailed files array
        for key in ("formatVersion", "pmdVersion", "timestamp", "metrics"):
            if key in raw:
                merged_report[key] = raw[key]
        merged_report["files"] = file_reports

        # write result
        with open(result_file, 'w') as f:
            json.dump(merged_report, f, indent=2)
        success_flag = True
        pmd_code = 0

        duration = time.time() - start_time
        # 커밋별 소요 시간 로그
        logger.info(f"[{worker_name}] Commit {commit_short} done in {duration:.2f}s")
        with progress_lock:
            progress_data['processed'] += 1
            if progress_data['processed'] % 100 == 0 or progress_data['processed'] == progress_data['total']:
                logger.info(f"[Main] Progress: {progress_data['processed']}/{progress_data['total']}")

        return commit_hash, duration, success_flag, pmd_code, new_cache_dict


def generate_summary_json(output_dir, pmd_results_dir):
    """
    repository mining 결과를 종합하여 summary.json으로 저장
    """
    summary = {'location': str(pmd_results_dir)}
    commit_files = list(pmd_results_dir.glob('*.json'))
    # .error.json 제외
    commit_files = [f for f in commit_files if not f.name.endswith('.error.json')]
    number_of_commits = len(commit_files)

    total_java = 0
    total_warnings = 0
    warnings_count = {}

    for file in commit_files:
        data = json.load(file.open(encoding='utf-8'))
        # files 배열 안의 각 fileReport를 직접 순회
        file_reports = data.get('files', [])
        num_files = len(file_reports)
        total_java += num_files

        # 경고는 파일별 violations 배열에서 집계

        for fr in file_reports:
            vs = fr.get('violations', [])
            total_warnings += len(vs)

            for v in vs:
                # v["rule"] 우선, 없으면 ruleSet, 그래도 없으면 UNKNOWN
                rule = v.get('rule') or v.get('ruleSet') or 'UNKNOWN'
                warnings_count[rule] = warnings_count.get(rule, 0) + 1

    summary['stat_of_repository'] = {
        'number_of_commits': number_of_commits,
        'avg_of_num_java_files': (total_java / number_of_commits) if number_of_commits else 0,
        'avg_of_num_warnings': (total_warnings / number_of_commits) if number_of_commits else 0
    }
    summary['stat_of_warnings'] = warnings_count

    summary_path = output_dir / 'summary.json'
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2)
    logger.info(f"Saved summary JSON to {summary_path}")


def analyze_repository_parallel(repo_location, output_dir_base, pmd_path, ruleset, aux_classpath, num_workers, extra_pmd_flags = None):
    start_overall_time = time.time()

    if extra_pmd_flags is None:
        extra_pmd_flags = []

    # --- Directory Setup ---
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(output_dir_base) / f"analysis_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Analysis results will be saved in: {output_dir}")

    base_repo_path = output_dir / "repo_base"
    worktrees_base_path = output_dir / "worktrees"
    worktrees_base_path.mkdir(parents=True, exist_ok=True)
    pmd_results_dir = output_dir / "pmd_results"
    pmd_results_dir.mkdir(parents=True, exist_ok=True)
    cache_path = output_dir / "file_hash_cache.json"
    file_cache.clear()
    file_cache.update(load_cache(cache_path))

    # --- Repository Setup ---
    run_command(['git', 'worktree', 'prune'],
                cwd=str(base_repo_path), check=False, suppress_stderr=True)


    if base_repo_path.exists() and (base_repo_path / ".git").is_dir():
        logger.info(f"Base repository exists at {base_repo_path}. Fetching updates...")
        try:
            run_command(['git', 'fetch', 'origin', '--prune'], cwd=base_repo_path, check=True)  # Add prune
            logger.info("Fetch complete.")
        except subprocess.CalledProcessError as e:
            logger.error(f"Checkout failed (code {e.returncode})")
            logger.error("stderr:\n%s", e.stderr or "<empty>")
        except Exception as e:
            logger.error(f"Error fetching updates: {e}. Proceeding with existing local repo.")
    else:
        if base_repo_path.exists():
            logger.warning(f"Path {base_repo_path} exists but is not a valid git repo. Removing.")
            try:
                shutil.rmtree(base_repo_path)
            except OSError as e:
                logger.critical(f"Failed to remove existing invalid repo directory {base_repo_path}: {e}. Exiting.")
                exit(1)
        logger.info(f"Cloning repository from {repo_location} to {base_repo_path}...")
        try:
            run_command(['git', 'clone', repo_location, str(base_repo_path)], check=True)
            logger.info("Base repository cloned successfully.")
        except Exception as e:
            logger.critical(f"Failed to clone repository: {e}. Exiting.")
            exit(1)

    # --- Get Commits ---
    commit_hashes = get_commit_hashes(base_repo_path)
    if not commit_hashes:
        logger.error("No commits found or failed to retrieve commits. Exiting.")
        return
    total_commits = len(commit_hashes)
    logger.info(f"Found {total_commits} commits to analyze.")

    # --- Worker Setup ---
    if not num_workers:
        try:
            num_workers = len(os.sched_getaffinity(0))
            logger.info(f"Using available CPUs: {num_workers}")
        except AttributeError:
            num_workers = os.cpu_count() or 1
            logger.info(f"Using CPU count: {num_workers}")
    num_workers = min(num_workers, total_commits)
    logger.info(f"Setting number of worker processes to: {num_workers}")

    logger.info("Cleaning up potentially stale worktrees...")
    try:
        run_command(['git', 'worktree', 'prune'], cwd=str(base_repo_path), check=False, suppress_stderr=True)
    except Exception as e:
        logger.warning(f"git worktree prune failed (this might be ok if no stale trees exist): {e}")

    existing_wt_dirs = set(
        item for item in worktrees_base_path.iterdir() if item.is_dir() and item.name.startswith("wt_"))
    logger.debug(f"Found existing worktree dirs: {existing_wt_dirs}")

    registered_worktrees = set()
    try:
        wt_list_result = run_command(['git', 'worktree', 'list', '--porcelain'], cwd=str(base_repo_path), check=True)
        current_path = None
        for line in wt_list_result.stdout.splitlines():
            if line.startswith('worktree '):
                current_path = Path(line.split(' ', 1)[1])
                registered_worktrees.add(current_path)
            elif line == '' and current_path:
                current_path = None
        logger.debug(f"Found registered worktrees: {registered_worktrees}")
    except Exception as e:
        logger.warning(f"Could not list registered worktrees: {e}")

    for wt_path in registered_worktrees:
        if wt_path.name.startswith("wt_"):
            logger.warning(f"Attempting to remove registered worktree: {wt_path.name}")
            try:

                run_command(['git', 'worktree', 'remove', '--force', wt_path.name], cwd=str(base_repo_path),
                            check=False, suppress_stderr=True)
            except Exception as e:
                logger.error(f"Error removing registered worktree {wt_path.name} using git: {e}")

    for wt_path in existing_wt_dirs:
        if wt_path.exists():
            logger.warning(f"Force removing potentially stale worktree directory: {wt_path}")
            try:
                shutil.rmtree(wt_path)
            except OSError as e:
                logger.error(f"Failed to remove directory {wt_path}: {e}. Analysis might fail.")

    logger.info("Stale worktree cleanup finished.")

    initial_commit_hash = commit_hashes[0]
    logger.info("Creating fresh worktrees...")
    worktree_paths = []
    for i in range(num_workers):
        wt_path = worktrees_base_path / f"wt_{i}"
        worktree_paths.append(wt_path)
        logger.info(f"Creating worktree {i} at {wt_path} linked to {initial_commit_hash[:8]}")
        try:
            run_command(
                ['git', '-C', str(base_repo_path), 'worktree', 'add', '--detach', str(wt_path), initial_commit_hash],
                check=True)
        except Exception as e:
            logger.critical(f"Failed to create worktree {i} at {wt_path}. Error: {e}. Exiting.")
            cleanup_worktrees(base_repo_path, worktrees_base_path, i + 1)
            exit(1)

    manager = Manager()
    progress_data = manager.dict({'processed': 0, 'total': total_commits})
    progress_lock = manager.Lock()
    worktree_locks = [manager.Lock() for _ in range(num_workers)]

    pool_args = []
    for i, commit_hash in enumerate(commit_hashes):
        prev_hash = commit_hashes[i - 1] if i > 0 else None
        pool_args.append((
            commit_hash,
            prev_hash,
            base_repo_path,
            worktree_paths[i % num_workers],
            pmd_path,
            ruleset,
            aux_classpath,
            output_dir,
            pmd_results_dir,
            progress_lock,
            progress_data,
            worktree_locks[i % num_workers],
            extra_pmd_flags
        ))

    logger.info(f"Starting analysis with {num_workers} worker processes...")
    results = []
    total_duration = 0
    successful_commits = 0
    pmd_failed_commits = 0
    git_failed_commits = 0
    skipped_commits = 0
    pmd_error_codes = {}
    interrupted = False
    pool = None

    try:
        pool = Pool(processes=num_workers)
        # imap_unordered: 결과가 준비되는 즉시 리턴해 줌
        results = pool.starmap(analyze_commit, pool_args)

        for i, (commit_hash, duration, success_flag, pmd_code, new_cache) in enumerate(results, start=1):

            # A) 캐시 업데이트
            file_cache.update(new_cache)

            # B) 기존 로직대로 성공/실패 집계
            if success_flag and duration == 0:
                skipped_commits += 1
            elif success_flag:
                successful_commits += 1
                total_duration += duration
            else:
                if pmd_code == -1:
                    git_failed_commits += 1
                else:
                    pmd_failed_commits += 1
                    pmd_error_codes[pmd_code] = pmd_error_codes.get(pmd_code, 0) + 1
            processed = skipped_commits + successful_commits + pmd_failed_commits + git_failed_commits
            # 200 커밋마다 중간 저장 및 로그
            if processed % 200 == 0 or processed == total_commits:
                logger.info(f"[MainProcess] - Intermediate Progress: {processed}/{total_commits} tasks processed.")
                logger.info(f"[Main] Saving file-hash cache at {processed} commits")
                save_cache(cache_path, dict(file_cache))

        pool.close()
        pool.join()


    except KeyboardInterrupt:
        interrupted = True
        logger.warning("Keyboard interrupt received. Terminating workers...")
        if pool:
            pool.terminate()
        logger.warning("Workers terminated due to interrupt.")
    except Exception as e:
        logger.error(f"An error occurred during the main analysis pool processing: {e}", exc_info=True)
        if pool:
            pool.terminate()
    finally:
        run_command(['git', 'worktree', 'prune'],
                    cwd=str(base_repo_path), check=False, suppress_stderr=True)
        if pool:
            pool.close()
            pool.join()

        save_cache(cache_path, dict(file_cache))

        if interrupted:
            # 중단 시점의 진행률만 찍기
            processed = progress_data.get('processed', 0)
            total = progress_data.get('total', 0)
            elapsed = time.time() - start_overall_time
            avg_sec = elapsed / processed if processed else 0
            logger.info(f"중단 시점 처리 완료: {processed}/{total} 커밋 (평균 {avg_sec:.2f}s/커밋)")
            return
        else:
            # 정상 종료 시에만 summary 생성
            generate_summary_json(output_dir, pmd_results_dir)

        cleanup_worktrees(base_repo_path, worktrees_base_path, num_workers)

    end_overall_time = time.time()
    overall_duration = end_overall_time - start_overall_time
    attempted_commits = (skipped_commits + successful_commits + pmd_failed_commits + git_failed_commits)
    avg_time_successful = total_duration / successful_commits if successful_commits > 0 else 0
    avg_time_attempted = overall_duration / attempted_commits if attempted_commits > 0 else 0

    logger.info("-" * 50)
    logger.info("Analysis Summary:")
    logger.info(f"  Total commits found:        {total_commits}")
    logger.info(f"  Commits skipped (exists):   {skipped_commits}")
    logger.info(f"  Commits attempted:          {attempted_commits}")
    logger.info(f"  Successfully processed:     {successful_commits}")
    logger.info(f"  PMD execution errors:       {pmd_failed_commits}")
    if pmd_failed_commits > 0:
        logger.info(f"    PMD Error Codes:        {pmd_error_codes}")
    logger.info(f"  Git/Script errors:        {git_failed_commits}")
    logger.info(f"  Total analysis time:        {overall_duration:.2f} seconds ({num_workers} workers).")
    logger.info(f"  Avg. time / successful commit: {avg_time_successful:.2f} seconds")
    logger.info(f"  Overall avg. time / commit: {avg_time_attempted:.2f} seconds")

    perf_limit = 1.0  # Example target
    if avg_time_attempted <= perf_limit:
        logger.info(f"  Performance requirement (<= {perf_limit:.1f}s/commit overall) met.")
    else:
        logger.warning(f"  Performance requirement (<= {perf_limit:.1f}s/commit overall) NOT met.")
    logger.info("-" * 50)


def cleanup_worktrees(base_repo_path, worktrees_base_path, num_worktrees_to_clean):
    logger.info("Cleaning up worktrees...")
    if not base_repo_path.exists() or not (base_repo_path / ".git").is_dir():
        logger.warning(
            f"Base repository path '{base_repo_path}' does not exist or is not a git repo. Skipping git cleanup.")
    else:
        try:
            run_command(['git', '-C', str(base_repo_path), 'worktree', 'prune'], check=False, suppress_stderr=True)
        except Exception as e:
            logger.warning(f"git worktree prune failed during final cleanup: {e}")

        for i in range(num_worktrees_to_clean):
            wt_name = f"wt_{i}"
            logger.debug(f"Attempting git worktree remove for {wt_name}")
            try:
                run_command(['git', '-C', str(base_repo_path), 'worktree', 'remove', '--force', wt_name], check=False,
                            suppress_stderr=True)
            except Exception as e:
                logger.warning(f"Final git worktree remove command failed for {wt_name}: {e}")

    if worktrees_base_path.exists():
        for i in range(num_worktrees_to_clean):
            wt_path = worktrees_base_path / f"wt_{i}"
            if wt_path.exists():
                logger.info(f"Removing worktree directory: {wt_path}")
                try:
                    shutil.rmtree(wt_path)
                except OSError as e:
                    logger.error(f"Failed to remove worktree directory {wt_path} during final cleanup: {e}")
    logger.info("Worktree cleanup finished.")


def build_pmd_flags(args):
    flags = ["--verbose" if args.pmd_debug else "--no-cache"]
    if args.pmd_debug:
        flags += ["--debug"]
    if args.strict_errors:
        flags += ["--fail-on-processing-error"]
    return flags

def safe_git_checkout(commit, wt_path, base_repo, retry=2):
    lock = Path(base_repo) / '.git' / 'worktrees' / wt_path.name / 'index.lock'
    for _ in range(retry + 1):
        try:
            run_command(['git','checkout','-f',commit], cwd=wt_path,
                        suppress_stderr=True, check=True)
            return True
        except subprocess.CalledProcessError as e:
            if 'index.lock' in (e.stderr or '') and lock.exists():
                lock.unlink(missing_ok=True)
                time.sleep(0.3)
            else:
                raise
    return False


def main():
    parser = argparse.ArgumentParser(description="Analyze Git repository history with PMD in parallel using worktrees.")
    parser.add_argument("repo_location", help="URL or local path of the Git repository.")
    parser.add_argument(
        "--aux-jars", nargs="+", default=[],
        help="PMD 분석 시 사용할 추가 JAR 파일 경로 리스트. 예: --aux-jars libs/junit.jar libs/commons-lang.jar"
    )
    parser.add_argument("-o", "--output-dir", default="analysis_results_parallel",
                        help="Base directory to store analysis results and repository data (timestamped subfolder will be created).")
    parser.add_argument("-r", "--ruleset", required=True, help="Path to the PMD ruleset XML file.")
    parser.add_argument("-w", "--workers", type=int, default=None,
                        help="Number of worker processes (defaults to available CPUs).")
    parser.add_argument("--pmd-debug", action="store_true", help="Pass --debug to PMD")
    parser.add_argument("--strict-errors", action="store_true", help="PMD --fail-on-processing-error")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging.")
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="suppress PMD warnings and INFO logs"
    )

    args = parser.parse_args()
    import logging

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%H:%M:%S",
    )
    if args.quiet:
        # PMD 쪽 noisy 로그만 죽임
        logging.getLogger("HTTP-Dispatcher").setLevel(logging.ERROR)
        logging.getLogger("urllib3").setLevel(logging.ERROR)
        logging.getLogger().setLevel(logging.ERROR)

    ruleset_path = Path(args.ruleset).expanduser().resolve()
    if not ruleset_path.is_file():
        logger.critical("Ruleset not found: %s", ruleset_path)
        exit(1)

    aux_classpath = os.pathsep.join([
        str(Path(p).expanduser().resolve()) for p in args.aux_jars if Path(p).is_file()
    ])

    output_dir_base = Path(args.output_dir).resolve()

    logger.info(f"Using ruleset: {ruleset_path}")

    # 분석 실행
    try:
        analyze_repository_parallel(repo_location=args.repo_location, output_dir_base=output_dir_base,
                                    pmd_path="/app/pmd-daemon.jar", ruleset=ruleset_path, aux_classpath=aux_classpath,
                                    num_workers=args.workers, extra_pmd_flags=build_pmd_flags(args))
    except subprocess.CalledProcessError as cpe:
        if cpe.returncode == 4:  # only processing errors
            logger.warning("PMD processing errors encountered (exit 4) – continuing.")
        else:
            raise
    except Exception:
        logger.exception("Fatal error")
        exit(1)


if __name__ == "__main__":
    main()
