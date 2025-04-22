import argparse
import subprocess
import logging
import json
import time
import os
import shutil
from pathlib import Path
from multiprocessing import Pool, Manager, Lock, current_process # Keep Lock
from datetime import datetime


logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - [%(processName)s] - %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger(__name__)



def run_command(command, cwd=None, check=True, suppress_stderr=False):
    """Executes a shell command."""
    cmd_str = ' '.join(map(str, command))
    command = [str(part) for part in command]
    logger.debug(f"Running command: {cmd_str} in {cwd or 'default CWD'}")
    stderr_pipe = subprocess.PIPE if not suppress_stderr else subprocess.DEVNULL
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=check, cwd=cwd, errors='ignore')
        log_level = logging.DEBUG


        if result.returncode != 0:
             log_level = logging.WARNING if not check else logging.ERROR

        if result.stdout:

            if logger.getEffectiveLevel() <= logging.DEBUG or log_level >= logging.WARNING:
                 logger.log(log_level, f"Command stdout: {cmd_str}\n{result.stdout.strip()}")
        if result.stderr and not suppress_stderr:

            logger.warning(f"Command stderr: {cmd_str}\n{result.stderr.strip()}")


        if check and result.returncode != 0:
            result.check_returncode()

        return result
    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed: {' '.join(map(str, e.cmd))}")
        logger.error(f"Return code: {e.returncode}")
        if e.stdout:
             logger.error(f"Output: {e.stdout.strip()}")
        if e.stderr:
             logger.error(f"Error Output: {e.stderr.strip()}")
        if check:
             raise
        return e
    except FileNotFoundError:
        logger.error(f"Command not found: {command[0]}")
        raise
    except Exception as e:
        logger.error(f"An unexpected error occurred running command '{cmd_str}': {e}")
        raise


def get_commit_hashes(repo_path):
    """Gets a list of all commit hashes in reverse chronological order."""
    try:
        result = run_command(['git', 'log', '--format=%H', '--reverse'], cwd=repo_path)
        hashes = [h for h in result.stdout.strip().split('\n') if h]
        return hashes
    except subprocess.CalledProcessError:
        logger.error(f"Failed to get commit hashes from {repo_path}")
        return []


def analyze_commit(args):
    commit_hash, base_repo_path, worktree_path, pmd_path, ruleset, output_dir, pmd_results_dir, progress_lock, progress_data, worktree_lock = args
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
        return commit_hash, 0, True # Indicate skipped

    logger.info(f"[{worker_name}] - Processing commit {commit_short} in {worktree_path.name}")

    pmd_success = False
    try:
        with worktree_lock:
            logger.debug(f"[{worker_name}] - Acquired lock for {worktree_path.name} (checkout)")
            run_command(['git', 'checkout', '-f', commit_hash], cwd=worktree_path, suppress_stderr=True)
            logger.debug(f"[{worker_name}] - Checked out {commit_short} in {worktree_path.name}")
        logger.debug(f"[{worker_name}] - Released lock for {worktree_path.name} after checkout")


        pmd_command = [
            str(pmd_path), 'check',
            '--dir', str(worktree_path),
            '--rulesets', str(ruleset),
            '--format', 'json',
            '--report-file', str(result_file),
            '--encoding', 'UTF-8',
            '--no-cache'
        ]

        pmd_result = run_command(pmd_command, cwd=worktree_path, check=False)

        if pmd_result.returncode == 0 or pmd_result.returncode == 4:
            pmd_success = True
            if not result_file.exists():
                pass

        else:
            logger.error(f"[{worker_name}] - PMD execution failed for {worktree_path.name} (commit {commit_short}) with code {pmd_result.returncode}")

            try:
                with worktree_lock:
                     logger.debug(f"[{worker_name}] - Acquired lock for {worktree_path.name} (reset after PMD error)")
                     run_command(['git', 'reset', '--hard'], cwd=worktree_path, suppress_stderr=True, check=True)
                     logger.debug(f"[{worker_name}] - Reset worktree {worktree_path.name} successfully.")
                logger.debug(f"[{worker_name}] - Released lock for {worktree_path.name} after reset")
            except Exception as reset_e:
                 logger.error(f"[{worker_name}] - Failed to reset worktree {worktree_path.name} after PMD error: {reset_e}")


    except subprocess.CalledProcessError as e:
        return commit_hash, 0, False
    except Exception as e:
        return commit_hash, 0, False

    end_time = time.time()
    duration = end_time - start_time
    if pmd_success:
        logger.info(f"[{worker_name}] - Commit {commit_short} processed in {duration:.2f}s.")

    with progress_lock:
        progress_data['processed'] += 1
        processed = progress_data['processed']
        total = progress_data['total']
        if processed % 100 == 0 or processed == total:
            logger.info(f"[MainProcess] - Progress: {processed}/{total} commits processed.")

    return commit_hash, duration, pmd_success


def analyze_repository_parallel(repo_location, output_dir_base, pmd_path, ruleset, num_workers=None):
    """Analyzes a Git repository in parallel using worktrees."""
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
    if base_repo_path.exists() and (base_repo_path / ".git").exists():
        logger.info(f"Base repository exists at {base_repo_path}. Fetching updates...")
        try:
            run_command(['git', 'fetch', 'origin'], cwd=base_repo_path)
            logger.info("Fetch complete.")
        except subprocess.CalledProcessError:
            logger.warning("Failed to fetch updates. Proceeding with existing local repo.")
        except Exception as e:
             logger.error(f"Error fetching updates: {e}. Proceeding with existing local repo.")
    else:
        if base_repo_path.exists():
             logger.warning(f"Path {base_repo_path} exists but is not a valid repo. Removing.")
             shutil.rmtree(base_repo_path)
        logger.info(f"Cloning repository from {repo_location} to {base_repo_path}...")
        try:
            run_command(['git', 'clone', repo_location, str(base_repo_path)])
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
        num_workers = os.cpu_count() or 1
    num_workers = min(num_workers, total_commits) # Cannot have more workers than commits
    logger.info(f"Using {num_workers} worker processes.")

    # --- Robust Worktree Cleanup (Pre-run) ---
    logger.info("Cleaning up potentially stale worktrees...")
    try:
        run_command(['git', 'worktree', 'prune'], cwd=str(base_repo_path), check=False)
    except Exception as e:
        logger.warning(f"git worktree prune failed (this might be ok): {e}")

    # Check physical directories first
    if worktrees_base_path.exists():
        for item in worktrees_base_path.iterdir():
            if item.is_dir() and item.name.startswith("wt_"):
                logger.warning(f"Found existing worktree directory: {item}. Attempting removal.")
                # Try removing via git first (might be registered)
                try:
                     run_command(['git', 'worktree', 'remove', '--force', item.name], cwd=str(base_repo_path), check=False, suppress_stderr=True)
                except Exception as e:
                     logger.warning(f"Could not remove worktree {item.name} using git (might not be registered): {e}")
                 # Force remove the directory if it still exists
                if item.exists():
                    try:
                        shutil.rmtree(item)
                        logger.info(f"Removed stale worktree directory: {item}")
                    except OSError as e:
                        logger.error(f"Failed to remove directory {item}: {e}. Analysis might fail.")

    logger.info("Stale worktree cleanup finished.")
    # --- End Cleanup Section ---

    # --- Prepare Worktrees ---
    initial_commit_hash = commit_hashes[0]
    logger.info("Creating fresh worktrees...")
    worktree_paths = []
    for i in range(num_workers):
        wt_path = worktrees_base_path / f"wt_{i}"
        worktree_paths.append(wt_path) # Store path for later use
        logger.info(f"Creating worktree {i} at {wt_path} linked to {initial_commit_hash[:8]}")
        try:
            run_command(['git', '-C', str(base_repo_path), 'worktree', 'add', '--detach', str(wt_path), initial_commit_hash])
        except subprocess.CalledProcessError as e:
             logger.critical(f"Failed to create worktree {i} at {wt_path}. Error: {e.stderr}. Exiting.")
             cleanup_worktrees(base_repo_path, worktrees_base_path, i) # Cleanup created trees
             exit(1)
        except Exception as e:
             logger.critical(f"Unexpected error creating worktree {i} at {wt_path}: {e}. Exiting.")
             cleanup_worktrees(base_repo_path, worktrees_base_path, i) # Cleanup created trees
             exit(1)


    # --- Parallel Analysis ---
    manager = Manager()
    progress_data = manager.dict({'processed': 0, 'total': total_commits})
    progress_lock = manager.Lock()
    # Create a lock for each worktree path
    worktree_locks = [manager.Lock() for _ in range(num_workers)]

    pool_args = [
        (
            commit_hash,
            base_repo_path,
            worktree_paths[i % num_workers],
            pmd_path,
            ruleset,
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
    failed_commits = 0
    skipped_commits = 0
    pool = None

    try:
        pool = Pool(processes=num_workers)
        results_iterator = pool.imap_unordered(analyze_commit, pool_args)

        for commit_hash, duration, success_flag in results_iterator:
            if success_flag is True and duration == 0:
                 skipped_commits += 1
            elif success_flag:
                successful_commits += 1
                total_duration += duration
            else:
                failed_commits += 1

    except KeyboardInterrupt:
        logger.warning("Keyboard interrupt received. Terminating workers...")
        if pool:
            pool.terminate()
            pool.join()
        logger.warning("Workers terminated.")
    except Exception as e:
         logger.error(f"An error occurred during the main analysis process: {e}", exc_info=True)
         if pool:
             pool.terminate()
             pool.join()
    finally:
        if pool:
            pool.close()
            pool.join()
        cleanup_worktrees(base_repo_path, worktrees_base_path, num_workers)

    # --- Reporting ---
    end_overall_time = time.time()
    overall_duration = end_overall_time - start_overall_time
    analyzed_count = successful_commits + failed_commits
    avg_time = total_duration / successful_commits if successful_commits > 0 else 0

    logger.info("-" * 50)
    logger.info("Analysis Summary:")
    logger.info(f"  Total commits found:      {total_commits}")
    logger.info(f"  Commits skipped (exists): {skipped_commits}")
    logger.info(f"  Commits analyzed:         {analyzed_count}")
    logger.info(f"  Successfully processed:   {successful_commits}")
    logger.info(f"  Failed processing:        {failed_commits}")
    logger.info(f"  Total analysis time:      {overall_duration:.2f} seconds using {num_workers} workers.")
    logger.info(f"  Avg. time per successful: {avg_time:.2f} seconds")

    perf_limit = 1.0
    overall_avg_time = overall_duration / analyzed_count if analyzed_count > 0 else 0
    logger.info(f"  Overall average time per commit (analyzed): {overall_avg_time:.2f} seconds")
    if overall_avg_time <= perf_limit:
        logger.info(f"  Performance requirement (<= {perf_limit:.1f}s/commit overall) met.")
    else:
        logger.warning(f"  Performance requirement (<= {perf_limit:.1f}s/commit overall) NOT met.")
    logger.info("-" * 50)


def cleanup_worktrees(base_repo_path, worktrees_base_path, num_worktrees_to_clean):
    """Cleans up Git worktrees and directories."""
    logger.info("Cleaning up worktrees...")
    if not base_repo_path.exists() or not (base_repo_path / ".git").exists():
        logger.warning("Base repository path does not exist or is not a git repo. Skipping git cleanup.")
        if worktrees_base_path.exists():
             for i in range(num_worktrees_to_clean):
                 wt_path = worktrees_base_path / f"wt_{i}"
                 if wt_path.exists():
                     try:
                         shutil.rmtree(wt_path)
                         logger.info(f"Removed worktree directory during final cleanup: {wt_path}")
                     except OSError as e:
                         logger.error(f"Failed to remove worktree directory {wt_path} during final cleanup: {e}")
        return

    try:
        run_command(['git', 'worktree', 'prune'], cwd=str(base_repo_path), check=False, suppress_stderr=True)
    except Exception as e:
        logger.warning(f"git worktree prune failed during final cleanup: {e}")

    for i in range(num_worktrees_to_clean):
        wt_name = f"wt_{i}"
        wt_path = worktrees_base_path / f"wt_{i}"
        logger.debug(f"Final cleanup for worktree: {wt_name}")
        try:
            run_command(['git', 'worktree', 'remove', '--force', wt_name], cwd=str(base_repo_path), check=False, suppress_stderr=True)
        except Exception as e:
             logger.warning(f"Final git worktree remove command failed for {wt_name}: {e}")

        if wt_path.exists():
            try:
                shutil.rmtree(wt_path)
                logger.info(f"Removed worktree directory during final cleanup: {wt_path}")
            except OSError as e:
                logger.error(f"Failed to remove worktree directory {wt_path} during final cleanup: {e}")
    logger.info("Worktree cleanup finished.")


def main():
    parser = argparse.ArgumentParser(description="Analyze Git repository history with PMD in parallel using worktrees.")
    parser.add_argument("repo_location", help="URL or local path of the Git repository.")
    parser.add_argument("-o", "--output-dir", default="analysis_results_parallel",
                        help="Base directory to store analysis results and repository data (timestamped subfolder will be created).")
    parser.add_argument("-p", "--pmd-path", required=True, help="Path to the PMD executable script (e.g., /path/to/pmd/bin/pmd).")
    parser.add_argument("-r", "--ruleset", required=True, help="Path to the PMD ruleset XML file.")
    parser.add_argument("-w", "--workers", type=int, default=None,
                        help="Number of worker processes (defaults to CPU count).")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging.")

    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)
        for handler in logging.getLogger().handlers:
             handler.setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled.")
    else:
         logger.setLevel(logging.INFO)
         for handler in logging.getLogger().handlers:
             handler.setLevel(logging.INFO)


    output_dir_base_abs = Path(args.output_dir).resolve()
    pmd_path_abs = Path(args.pmd_path).resolve()
    ruleset_abs = Path(args.ruleset).resolve()

    if not pmd_path_abs.is_file():
        logger.error(f"PMD executable not found at: {pmd_path_abs}")
        exit(1)
    if not os.access(pmd_path_abs, os.X_OK):
         logger.warning(f"PMD path {pmd_path_abs} might not be executable.")
         try:
             os.chmod(pmd_path_abs, os.stat(pmd_path_abs).st_mode | 0o111) # Add execute perm
             logger.info(f"Attempted to set execute permission on {pmd_path_abs}")
             if not os.access(pmd_path_abs, os.X_OK):
                 logger.error(f"Failed to set execute permission. Please ensure {pmd_path_abs} is executable.")
                 exit(1)
         except OSError as e:
             logger.error(f"Could not set execute permission on {pmd_path_abs}: {e}")
             exit(1)


    if not ruleset_abs.is_file():
        logger.error(f"Ruleset file not found at: {ruleset_abs}")
        exit(1)

    try:
        analyze_repository_parallel(
            repo_location=args.repo_location,
            output_dir_base=output_dir_base_abs,
            pmd_path=pmd_path_abs,
            ruleset=ruleset_abs,
            num_workers=args.workers
        )
    except Exception as e:
        logger.critical(f"A critical error occurred in main: {e}", exc_info=True)
        exit(1)

if __name__ == "__main__":
    # from multiprocessing import freeze_support
    # freeze_support() # Uncomment if needed on Windows
    main()