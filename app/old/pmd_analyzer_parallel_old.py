import argparse
import json
import os
import shutil
import subprocess
import time
import logging
from pathlib import Path
from git import Repo, GitCommandError
from multiprocessing import Pool, cpu_count, Manager
import uuid


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(processName)s - %(levelname)s - %(message)s')


def count_java_files(directory):
    """지정된 디렉토리 내의 .java 파일 개수를 셉니다."""
    count = 0

    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for file in files:
            if file.endswith(".java"):
                count += 1
    return count

def run_pmd(pmd_path, project_dir, ruleset_path, output_file, cache_path):
    """PMD를 실행하고 결과를 JSON 파일로 저장합니다. 캐시 옵션 추가."""

    cmd = [
        pmd_path, 'check',
        '--dir', str(project_dir),
        '--rulesets', str(ruleset_path),
        '--format', 'json',
        '--report-file', str(output_file),
        '--cache', str(cache_path)
    ]

    logging.debug(f"Running PMD for {project_dir}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, encoding='utf-8', errors='ignore')

        if result.returncode != 0 and result.returncode != 4:
            logging.error(f"PMD execution failed for {project_dir} (return code {result.returncode})")

            return False, 0, {}

        warnings_count = 0
        warnings_by_rule = {}
        if output_file.exists() and output_file.stat().st_size > 0:
             try:
                 with open(output_file, 'r', encoding='utf-8') as f:
                     pmd_result = json.load(f)
                 for file_report in pmd_result.get('files', []):
                     for violation in file_report.get('violations', []):
                         warnings_count += 1
                         rule_name = violation.get('rule')
                         if rule_name:
                             warnings_by_rule[rule_name] = warnings_by_rule.get(rule_name, 0) + 1
                 logging.debug(f"PMD found {warnings_count} warnings in {project_dir}.")
             except json.JSONDecodeError:
                 logging.error(f"Failed to parse PMD output JSON: {output_file}")
                 return False, 0, {}
             except Exception as e:
                 logging.error(f"Error processing PMD results for {output_file}: {e}")
                 return False, 0, {}
        else:
            logging.debug(f"PMD ran for {project_dir}, but no violations found or output file is empty.")

        return True, warnings_count, warnings_by_rule

    except FileNotFoundError:
        logging.error(f"PMD executable not found at: {pmd_path}")
        return False, 0, {}
    except Exception as e:
        logging.error(f"An error occurred while running PMD for {project_dir}: {e}")
        return False, 0, {}


def worker_process_commit(args):
    """개별 커밋을 처리하는 워커 함수 (병렬 실행용)"""
    commit_hash, repo_path_str, pmd_path, ruleset_path, results_path_str, worktree_base_path_str, pmd_cache_base_path_str = args
    repo_path = Path(repo_path_str)
    results_path = Path(results_path_str)
    worktree_base_path = Path(worktree_base_path_str)
    pmd_cache_base_path = Path(pmd_cache_base_path_str)


    worktree_name = f"worktree_{commit_hash[:8]}_{uuid.uuid4().hex[:8]}"
    worktree_path = worktree_base_path / worktree_name
    pmd_cache_path = pmd_cache_base_path / f"{commit_hash[:8]}_cache" # 커밋별 캐시 사용

    start_time = time.time()
    logging.info(f"Processing commit: {commit_hash[:8]}")

    try:
        # 1. Git Worktree 생성
        logging.debug(f"Creating worktree for {commit_hash[:8]} at {worktree_path}")
        subprocess.run(['git', '-C', str(repo_path), 'worktree', 'add', '--detach', str(worktree_path), commit_hash],
                       check=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
        logging.debug(f"Worktree created for {commit_hash[:8]}")

        # 2. Java 파일 수 계산
        java_files_count = count_java_files(worktree_path)
        logging.debug(f"{commit_hash[:8]}: Found {java_files_count} Java files.")

        # 3. PMD 실행
        commit_output_file = results_path / f"{commit_hash}.json"
        pmd_success, warnings_count, warnings_by_rule = run_pmd(
            pmd_path, worktree_path, ruleset_path, commit_output_file, pmd_cache_path
        )

        # 4. 결과 반환 준비
        duration = time.time() - start_time
        result = {
            "commit": commit_hash,
            "java_files": java_files_count,
            "pmd_success": pmd_success,
            "warnings": warnings_count if pmd_success else 0,
            "warnings_by_rule": warnings_by_rule if pmd_success else {},
            "duration": duration,
        }
        logging.info(f"Commit {commit_hash[:8]} processed in {duration:.2f} seconds.")
        if duration > 1.5:
             logging.warning(f"Commit {commit_hash[:8]} took longer than expected ({duration:.2f}s)")

        return result

    except subprocess.CalledProcessError as e:
        logging.error(f"Git worktree command failed for {commit_hash[:8]}: {e.stderr}")
        return {"commit": commit_hash, "pmd_success": False, "error": "git worktree error", "duration": time.time() - start_time}
    except Exception as e:
        logging.error(f"Error processing commit {commit_hash[:8]} in worker: {e}")
        return {"commit": commit_hash, "pmd_success": False, "error": str(e), "duration": time.time() - start_time}
    finally:
        # 5. Git Worktree 정리
        if worktree_path.exists():
            logging.debug(f"Removing worktree for {commit_hash[:8]} at {worktree_path}")
            try:
                subprocess.run(['git', '-C', str(repo_path), 'worktree', 'prune'], capture_output=True, text=True, check=False)
                subprocess.run(['git', '-C', str(repo_path), 'worktree', 'remove', '--force', str(worktree_path)],
                               check=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
            except subprocess.CalledProcessError as e:
                logging.warning(f"Failed to remove worktree {worktree_path}: {e.stderr}. Manual cleanup might be needed.")
            except Exception as e_rm:
                 logging.warning(f"Error during worktree removal {worktree_path}: {e_rm}. Manual cleanup might be needed.")
        if pmd_cache_path.exists():
             try:
                 shutil.rmtree(pmd_cache_path)
             except Exception as e_cache:
                 logging.warning(f"Could not remove PMD cache {pmd_cache_path}: {e_cache}")



def analyze_repository_parallel(repo_location, output_dir, pmd_path, ruleset_path, num_workers=None):
    """Git 저장소를 병렬로 분석하고 PMD 결과를 수집 및 요약합니다."""
    start_time_total = time.time()
    repo_base_path = Path(output_dir) / 'repo'
    results_path = Path(output_dir) / 'pmd_results'
    worktree_base_path = Path(output_dir) / 'worktrees'
    pmd_cache_base_path = Path(output_dir) / 'pmd_cache'
    summary_file = Path(output_dir) / 'summary.json'

    results_path.mkdir(parents=True, exist_ok=True)
    worktree_base_path.mkdir(parents=True, exist_ok=True)
    pmd_cache_base_path.mkdir(parents=True, exist_ok=True)

    repo = None
    original_branch_name = "main"
    try:
        if repo_base_path.exists():
            logging.info(f"Opening existing repository at {repo_base_path}...")
            repo = Repo(repo_base_path)
            try:
                original_branch_name = repo.active_branch.name
            except TypeError:
                 logging.warning("Repository is in detached HEAD state. Assuming 'main' or 'master' as target.")
                 try:
                     original_branch_name = repo.git.symbolic_ref('refs/remotes/origin/HEAD').split('/')[-1]
                     logging.info(f"Detected default branch: {original_branch_name}")
                 except GitCommandError:
                     original_branch_name = "main"
            logging.info(f"Using branch: {original_branch_name}. Fetching latest changes...")
            try:
                repo.remotes.origin.fetch()
            except Exception as e:
                logging.warning(f"Could not fetch from origin: {e}")
        else:
            logging.info(f"Cloning repository from {repo_location} to {repo_base_path}...")
            repo = Repo.clone_from(repo_location, repo_base_path)
            original_branch_name = repo.active_branch.name
            logging.info(f"Repository cloned successfully. Active branch: {original_branch_name}")

        # 커밋 목록 가져오기
        commits = list(repo.iter_commits(rev=original_branch_name, reverse=True))
        num_commits = len(commits)
        if num_commits == 0:
            logging.warning("No commits found in the repository.")
            return
        logging.info(f"Found {num_commits} commits to analyze on branch '{original_branch_name}'.")

        # 병렬 처리 준비
        if num_workers is None:
            num_workers = cpu_count()
        logging.info(f"Using {num_workers} parallel workers.")

        # 워커에 전달할 인자 목록 생성
        tasks = [(c.hexsha, str(repo_base_path), pmd_path, ruleset_path, str(results_path), str(worktree_base_path), str(pmd_cache_base_path)) for c in commits]

        all_results = []
        # 멀티프로세싱 풀 생성 및 실행
        with Pool(processes=num_workers) as pool:
            # imap_unordered는 결과를 받는 순서대로 처리하여 메모리 효율적일 수 있음
            for result in pool.imap_unordered(worker_process_commit, tasks):
                if result: # None이 아닌 경우 (오류 발생 시에도 딕셔너리 반환)
                   all_results.append(result)
                   logging.info(f"Completed processing for commit: {result.get('commit', 'unknown')[:8]}. Success: {result.get('pmd_success', False)}")


        # 최종 요약 통계 계산
        processed_commits_count = 0
        total_java_files = 0
        total_warnings = 0
        total_warnings_by_rule = {}
        successful_commits = []

        for res in all_results:
            if res and res.get("pmd_success"):
                successful_commits.append(res)
                processed_commits_count += 1
                total_java_files += res.get("java_files", 0)
                total_warnings += res.get("warnings", 0)
                for rule, count in res.get("warnings_by_rule", {}).items():
                    total_warnings_by_rule[rule] = total_warnings_by_rule.get(rule, 0) + count
            elif res:
                 logging.warning(f"Commit {res.get('commit', 'unknown')[:8]} failed processing. Error: {res.get('error', 'unknown')}")


        if processed_commits_count > 0:
            avg_java_files = total_java_files / processed_commits_count
            avg_warnings = total_warnings / processed_commits_count
            summary_data = {
                "location": repo_location,
                "stat_of_repository": {
                    "number_of_commits_analyzed": processed_commits_count,
                    "total_commits_in_repo": num_commits,
                    "avg_of_num_java_files": round(avg_java_files, 2),
                    "avg_of_num_warnings": round(avg_warnings, 2),
                },
                "stat_of_warnings": total_warnings_by_rule
            }
        else:
            summary_data = {
                "location": repo_location,
                "stat_of_repository": {
                    "number_of_commits_analyzed": 0,
                    "total_commits_in_repo": num_commits,
                    "avg_of_num_java_files": 0,
                    "avg_of_num_warnings": 0,
                },
                "stat_of_warnings": {}
            }
            logging.warning("No commits were successfully analyzed.")

        # 요약 파일 저장
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary_data, f, indent=4, ensure_ascii=False)
        logging.info(f"Summary report saved to {summary_file}")

    except GitCommandError as e:
        logging.error(f"Git error during setup: {e}")
    except Exception as e:
        logging.error(f"An unexpected error occurred in main process: {e}")
    finally:
        if repo:
            repo.close()
            del repo
        pass

    end_time_total = time.time()
    total_duration = end_time_total - start_time_total
    avg_time_per_commit = total_duration / num_commits if num_commits > 0 else 0
    logging.info(f"Total analysis time: {total_duration:.2f} seconds for {num_commits} commits.")
    logging.info(f"Average time per commit (overall): {avg_time_per_commit:.2f} seconds")

    # 성능 요구사항(R10)
    if avg_time_per_commit <= 1.0:
        logging.info("Performance requirement (<= 1.0s/commit overall) met.")
    else:
        logging.warning("Performance requirement (> 1.0s/commit overall) NOT met.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze Git repository history with PMD using parallel processing.")
    parser.add_argument("repo_location", help="URL or local path of the Git repository (must be a Java project).")
    parser.add_argument("-o", "--output-dir", default="analysis_results_parallel", help="Directory to store PMD results and summary.")
    parser.add_argument("-p", "--pmd-path", required=True, help="Path to the PMD executable.")
    parser.add_argument("-r", "--ruleset", required=True, help="Path to the PMD ruleset XML file.")
    parser.add_argument("-w", "--workers", type=int, default=None, help=f"Number of parallel workers (default: number of CPU cores, which is {cpu_count()})")

    args = parser.parse_args()

    if not Path(args.pmd_path).exists():
        print(f"Error: PMD executable not found at '{args.pmd_path}'")
        exit(1)
    if not Path(args.ruleset).exists():
        print(f"Error: PMD ruleset file not found at '{args.ruleset}'")
        exit(1)

    analyze_repository_parallel(args.repo_location, args.output_dir, args.pmd_path, args.ruleset, args.workers)