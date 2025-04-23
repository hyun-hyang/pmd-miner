import argparse
import subprocess
import logging
import json
import time
import os
import shutil
import traceback
from pathlib import Path
from multiprocessing import Pool, Manager, Lock, current_process
from datetime import datetime


logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - [%(processName)s] - %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger(__name__)


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
        logger.error(f"An unexpected error occurred running command '{cmd_str}': {e}", exc_info=True) # Add exc_info for full traceback
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


def analyze_commit(args):
    commit_hash, base_repo_path, worktree_path, pmd_path, ruleset, aux_classpath, output_dir, pmd_results_dir, progress_lock, progress_data, worktree_lock = args
    worker_name = current_process().name
    start_time = time.time()
    commit_short = commit_hash[:8]
    result_file = pmd_results_dir / f"{commit_hash}.json"
    error_file = pmd_results_dir / f"{commit_hash}.error.json"


    if result_file.exists() or error_file.exists():
        logger.info(f"[{worker_name}] - Skipping commit {commit_short}: result or error file already exists.")
        with progress_lock:
            progress_data['processed'] += 1
            processed = progress_data['processed']
            total = progress_data['total']
            if processed % 100 == 0 or processed == total:
                 logger.info(f"[MainProcess] - Progress: {processed}/{total} commits processed.")
        return commit_hash, 0, True, None

    logger.info(f"[{worker_name}] - Processing commit {commit_short} in {worktree_path.name}")

    pmd_exit_code = -1
    analysis_successful = False

    try:
        # --- Acquire Lock for Git Operations ---
        with worktree_lock:
            logger.debug(f"[{worker_name}] - Acquired lock for {worktree_path.name} (checkout)")
            run_command(['git', 'checkout', '-f', commit_hash], cwd=worktree_path, suppress_stderr=True, check=True)
            logger.debug(f"[{worker_name}] - Checked out {commit_short} in {worktree_path.name}")
        # --- Release Lock after Git Checkout ---
        logger.debug(f"[{worker_name}] - Released lock for {worktree_path.name} after checkout")



        # --- Skip commits with no Java source files ---

        wt = Path(worktree_path)
        java_files = list(wt.rglob("*.java"))

        if not java_files:
            # Java 파일이 없는 커밋에도 빈 JSON 생성
            placeholder = {
                "commit": commit_hash,
                "num_java_files": 0,
                "warnings": []
            }
            try:
                with open(result_file, 'w', encoding='utf-8') as f:
                    json.dump(placeholder, f, indent=2)
            except IOError as e:
                logger.error(f"[{worker_name}] - Failed to write empty result for {commit_short}: {e}")

            with progress_lock:
                progress_data['processed'] += 1
                processed = progress_data['processed']
                total = progress_data['total']
                if processed % 100 == 0 or processed == total:
                    logger.info(f"[MainProcess] - Progress: {processed}/{total} commits processed.")
            return commit_hash, 0, True, None



        # Define PMD command arguments
        pmd_command = [
            str(pmd_path),
            'check',
            '--aux-classpath', aux_classpath or "",
            '--dir', str(worktree_path),
            '--rulesets', str(ruleset),
            '--format', 'json',
            '--report-file', str(result_file),
            '--encoding', 'UTF-8',
            '--no-cache',
            '--no-fail-on-error',
            # "--verbose",  # ← 추가!
            # '--debug'
        ]

        pmd_result = run_command(pmd_command, cwd=worktree_path, check=False)
        pmd_exit_code = pmd_result.returncode # Store the exit code

        if pmd_exit_code in [0, 4]:
            analysis_successful = True
            if not result_file.exists():
                logger.warning(f"[{worker_name}] - PMD ran for commit {commit_short} but report file {result_file} was not created. Exit code: {pmd_exit_code}.")
                try:
                    with open(result_file, 'w') as f_empty:
                        json.dump({"commit": commit_hash, "processing_info": f"PMD exited with code {pmd_exit_code} but no report file generated.", "files": []}, f_empty, indent=2)
                except IOError as e:
                    logger.error(f"[{worker_name}] - Failed to write placeholder result file {result_file}: {e}")


        else:
            analysis_successful = False
            logger.error(f"[{worker_name}] - PMD execution failed for {worktree_path.name} (commit {commit_short}) with code {pmd_exit_code}")
            if result_file.exists():
                 try: result_file.unlink()
                 except OSError as e: logger.error(f"[{worker_name}] - Failed to remove potentially incomplete result file {result_file}: {e}")

            error_info = {
                "commit": commit_hash,
                "error": f"PMD execution failed with code {pmd_exit_code}",
                "return_code": pmd_exit_code,
                "stderr": pmd_result.stderr.strip() if hasattr(pmd_result, 'stderr') else "N/A",
                "stdout": pmd_result.stdout.strip() if hasattr(pmd_result, 'stdout') else "N/A"
            }
            try:
                with open(error_file, 'w') as f_err:
                    json.dump(error_info, f_err, indent=2)
            except IOError as e:
                logger.error(f"[{worker_name}] - Failed to write error file {error_file}: {e}")

            try:
                with worktree_lock:
                     logger.debug(f"[{worker_name}] - Acquired lock for {worktree_path.name} (reset after PMD error)")
                     run_command(['git', 'reset', '--hard'], cwd=worktree_path, suppress_stderr=True, check=True)
                     logger.info(f"[{worker_name}] - Successfully reset worktree {worktree_path.name} after PMD error.")

                logger.debug(f"[{worker_name}] - Released lock for {worktree_path.name} after reset")
            except Exception as reset_e:
                 logger.error(f"[{worker_name}] - Failed to reset worktree {worktree_path.name} after PMD error: {reset_e}")

    except subprocess.CalledProcessError as e:
        logger.error(f"[{worker_name}] - Git command failed for commit {commit_short} in {worktree_path.name}: {e}")
        if "index.lock" in str(e.stderr):
             logger.error(f"[{worker_name}] - LOCK FILE ERROR DETECTED for {worktree_path.name}. This suggests concurrent git access conflict.")
        error_info = {
            "commit": commit_hash,
            "error": "Git command failed",
            "command": ' '.join(map(str, e.cmd)),
            "return_code": e.returncode,
            "stderr": e.stderr.strip() if hasattr(e, 'stderr') else "N/A",
            "stdout": e.stdout.strip() if hasattr(e, 'stdout') else "N/A"
        }
        try:
            with open(error_file, 'w') as f_err:
                 json.dump(error_info, f_err, indent=2)
        except IOError as io_e:
             logger.error(f"[{worker_name}] - Failed to write git error file {error_file}: {io_e}")
        return commit_hash, 0, False, pmd_exit_code
    except Exception as e:
        logger.error(f"[{worker_name}] - Unexpected error processing commit {commit_short} in {worktree_path.name}: {e}", exc_info=True)

        error_info = {
            "commit": commit_hash,
            "error": f"Unexpected Python error: {type(e).__name__}",
            "message": str(e),
            "traceback": traceback.format_exc()
        }
        try:
             with open(error_file, 'w') as f_err:
                  json.dump(error_info, f_err, indent=2)
        except IOError as io_e:
             logger.error(f"[{worker_name}] - Failed to write unexpected error file {error_file}: {io_e}")
        return commit_hash, 0, False, pmd_exit_code

    end_time = time.time()
    duration = end_time - start_time
    if analysis_successful:
         logger.info(f"[{worker_name}] - Commit {commit_short} processed in {duration:.2f}s.")

    with progress_lock:
        progress_data['processed'] += 1
        processed = progress_data['processed']
        total = progress_data['total']
        if processed % 100 == 0 or processed == total:
            logger.info(f"[MainProcess] - Progress: {processed}/{total} commits processed.")

    return commit_hash, duration if analysis_successful else 0, analysis_successful, pmd_exit_code

def generate_summary_json(output_dir, pmd_results_dir):
    """
    repository mining 결과를 종합하여 summary.json으로 저장
    """
    summary = { 'location': str(output_dir) }
    commit_files = [f for f in pmd_results_dir.iterdir() if f.suffix == '.json' and not f.name.endswith('.error.json')]
    number_of_commits = len(commit_files)

    total_java = 0
    total_warnings = 0
    warnings_count = {}

    for file in commit_files:
        data = json.load(file.open(encoding='utf-8'))
        java_count = data.get('num_java_files', 0)
        warning_list = data.get('warnings', [])
        warning_count = len(warning_list)
        total_java += java_count
        total_warnings += warning_count
        for rule, cnt in data.get('warnings_by_rule', {}).items():
            warnings_count[rule] = warnings_count.get(rule, 0) + cnt

    summary['stat_of_repository'] = {
        'number_of_commits': number_of_commits,
        'avg_of_num_java_files': total_java / number_of_commits if number_of_commits else 0,
        'avg_of_num_warnings': total_warnings / number_of_commits if number_of_commits else 0
    }
    summary['stat_of_warnings'] = warnings_count

    summary_path = output_dir / 'summary.json'
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2)
    logger.info(f"Saved summary JSON to {summary_path}")

def analyze_repository_parallel(repo_location, output_dir_base, pmd_path, ruleset, aux_classpath, num_workers=None):
    start_overall_time = time.time()

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

    # --- Repository Setup ---
    if base_repo_path.exists() and (base_repo_path / ".git").is_dir():
        logger.info(f"Base repository exists at {base_repo_path}. Fetching updates...")
        try:
            run_command(['git', 'fetch', 'origin', '--prune'], cwd=base_repo_path, check=True) # Add prune
            logger.info("Fetch complete.")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to fetch updates: {e.stderr}. Proceeding with existing local repo.")
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


    existing_wt_dirs = set(item for item in worktrees_base_path.iterdir() if item.is_dir() and item.name.startswith("wt_"))
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

                run_command(['git', 'worktree', 'remove', '--force', wt_path.name], cwd=str(base_repo_path), check=False, suppress_stderr=True)
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
            run_command(['git', '-C', str(base_repo_path), 'worktree', 'add', '--detach', str(wt_path), initial_commit_hash], check=True)
        except Exception as e:
             logger.critical(f"Failed to create worktree {i} at {wt_path}. Error: {e}. Exiting.")
             cleanup_worktrees(base_repo_path, worktrees_base_path, i + 1)
             exit(1)



    manager = Manager()
    progress_data = manager.dict({'processed': 0, 'total': total_commits})
    progress_lock = manager.Lock()
    worktree_locks = [manager.Lock() for _ in range(num_workers)]

    pool_args = [
        (
            commit_hash,
            base_repo_path,
            worktree_paths[i % num_workers],
            pmd_path,
            ruleset,
            aux_classpath,
            output_dir,
            pmd_results_dir,
            progress_lock,
            progress_data,
            worktree_locks[i % num_workers]
        )
        for i, commit_hash in enumerate(commit_hashes)
    ]

    logger.info(f"Starting analysis with {num_workers} worker processes...")
    results = []
    total_duration = 0
    successful_commits = 0
    pmd_failed_commits = 0
    git_failed_commits = 0
    skipped_commits = 0
    pmd_error_codes = {}
    pool = None

    try:
        pool = Pool(processes=num_workers)
        results_iterator = pool.imap_unordered(analyze_commit, pool_args)

        for i, result_tuple in enumerate(results_iterator):
            commit_hash, duration, success_flag, pmd_code = result_tuple

            if success_flag is True and duration == 0:
                 skipped_commits += 1
            elif success_flag:
                successful_commits += 1
                total_duration += duration
            else:
                 if pmd_code == -1: # Assume Git error if PMD didn't even run
                     git_failed_commits += 1
                 else:
                     pmd_failed_commits += 1
                     pmd_error_codes[pmd_code] = pmd_error_codes.get(pmd_code, 0) + 1


            processed_count = skipped_commits + successful_commits + pmd_failed_commits + git_failed_commits
            if processed_count % 200 == 0 or processed_count == total_commits:
                 logger.info(f"[MainProcess] - Intermediate Progress: {processed_count}/{total_commits} tasks processed.")


    except KeyboardInterrupt:
        logger.warning("Keyboard interrupt received. Terminating workers...")
        if pool:
            pool.terminate()
        logger.warning("Workers terminated.")
    except Exception as e:
         logger.error(f"An error occurred during the main analysis pool processing: {e}", exc_info=True)
         if pool:
             pool.terminate()
    finally:
        if pool:
            pool.close()
            pool.join()

        generate_summary_json(output_dir, pmd_results_dir)
        cleanup_worktrees(base_repo_path, worktrees_base_path, num_workers)


    end_overall_time = time.time()
    overall_duration = end_overall_time - start_overall_time
    attempted_commits = successful_commits + pmd_failed_commits + git_failed_commits
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

    perf_limit = 1.0 # Example target
    if avg_time_attempted <= perf_limit:
        logger.info(f"  Performance requirement (<= {perf_limit:.1f}s/commit overall) met.")
    else:
        logger.warning(f"  Performance requirement (<= {perf_limit:.1f}s/commit overall) NOT met.")
    logger.info("-" * 50)


def cleanup_worktrees(base_repo_path, worktrees_base_path, num_worktrees_to_clean):
    logger.info("Cleaning up worktrees...")
    if not base_repo_path.exists() or not (base_repo_path / ".git").is_dir():
        logger.warning(f"Base repository path '{base_repo_path}' does not exist or is not a git repo. Skipping git cleanup.")
    else:
        try:
            run_command(['git', '-C', str(base_repo_path), 'worktree', 'prune'], check=False, suppress_stderr=True)
        except Exception as e:
            logger.warning(f"git worktree prune failed during final cleanup: {e}")

        for i in range(num_worktrees_to_clean):
            wt_name = f"wt_{i}"
            logger.debug(f"Attempting git worktree remove for {wt_name}")
            try:
                run_command(['git', '-C', str(base_repo_path), 'worktree', 'remove', '--force', wt_name], check=False, suppress_stderr=True)
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



def main():
    parser = argparse.ArgumentParser(description="Analyze Git repository history with PMD in parallel using worktrees.")
    parser.add_argument("repo_location", help="URL or local path of the Git repository.")
    parser.add_argument(
        "--aux-jars", nargs="+", default=[],
        help="PMD 분석 시 사용할 추가 JAR 파일 경로 리스트. 예: --aux-jars libs/junit.jar libs/commons-lang.jar"
    )
    parser.add_argument("-o", "--output-dir", default="analysis_results_parallel",
                        help="Base directory to store analysis results and repository data (timestamped subfolder will be created).")
    parser.add_argument("-p", "--pmd-path", required=True, help="Path to the PMD executable script (e.g., /path/to/pmd/bin/pmd).")
    parser.add_argument("-r", "--ruleset", required=True, help="Path to the PMD ruleset XML file.")
    parser.add_argument("-w", "--workers", type=int, default=None,
                        help="Number of worker processes (defaults to available CPUs).")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging.")

    args = parser.parse_args()


    if args.verbose:
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        for handler in root_logger.handlers:
             handler.setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled.")
    else:
         root_logger = logging.getLogger()
         root_logger.setLevel(logging.INFO)
         for handler in root_logger.handlers:
             handler.setLevel(logging.INFO)

    import os
    aux_classpath = os.pathsep.join(args.aux_jars)
    output_dir_base_abs = Path(args.output_dir).resolve()
    pmd_path_abs = Path(args.pmd_path).resolve()
    ruleset_abs = Path(args.ruleset).resolve()

    if not pmd_path_abs.is_file():
        logger.critical(f"PMD executable not found at resolved path: {pmd_path_abs}")
        exit(1)
    if not os.access(pmd_path_abs, os.X_OK):
         logger.warning(f"PMD path {pmd_path_abs} might not be executable.")
         try:
             current_mode = os.stat(pmd_path_abs).st_mode
             os.chmod(pmd_path_abs, current_mode | 0o111)
             logger.info(f"Attempted to set execute permission on {pmd_path_abs}")
             if not os.access(pmd_path_abs, os.X_OK):
                 logger.critical(f"Failed to set execute permission. Please ensure {pmd_path_abs} is executable.")
                 exit(1)
         except OSError as e:
             logger.critical(f"Could not set execute permission on {pmd_path_abs}: {e}")
             exit(1)

    if not ruleset_abs.is_file():
        logger.critical(f"Ruleset file not found at resolved path: {ruleset_abs}")
        exit(1)

    logger.info(f"Using PMD executable: {pmd_path_abs}")
    logger.info(f"Using Ruleset: {ruleset_abs}")

    try:
        analyze_repository_parallel(
            repo_location=args.repo_location,
            output_dir_base=output_dir_base_abs,
            pmd_path=pmd_path_abs,
            ruleset=ruleset_abs,
            aux_classpath=aux_classpath,
            num_workers=args.workers
        )
    except Exception as e:
        logger.critical(f"A critical error occurred in main execution: {e}", exc_info=True)
        exit(1)

if __name__ == "__main__":
    main()