import argparse
import json
import os
import shutil
import subprocess
import time
import logging
from pathlib import Path
import multiprocessing
import math


logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - [%(processName)s] - %(message)s')


def run_command(command, cwd=None, check=True, capture=False):
    logging.debug(f"Running command: {' '.join(command)} in {cwd or os.getcwd()}")
    try:
        current_env = os.environ.copy()
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=capture,
            text=True,
            check=check,
            encoding='utf-8',
            errors='ignore',
            env = current_env
        )
        if capture:
            logging.debug(f"Command stdout: {result.stdout[:100]}...")
            logging.debug(f"Command stderr: {result.stderr[:100]}...")
        return result
    except subprocess.CalledProcessError as e:
        logging.error(f"Command failed: {' '.join(command)}")
        logging.error(f"Return code: {e.returncode}")
        if e.stderr: logging.error(f"Stderr: {e.stderr}")
        if e.stdout: logging.error(f"Stdout: {e.stdout}")
        raise
    except FileNotFoundError:
        logging.error(f"Command not found: {command[0]}. Is it installed/in PATH?")
        raise
    except Exception as e:
        logging.error(f"Error running command {' '.join(command)}: {e}")
        raise

def count_java_files(directory):
    count = 0
    try:
        for root, _, files in os.walk(directory):
            for file in files:
                if file.endswith(".java"):
                    count += 1
    except Exception as e:
        logging.error(f"Error counting files in {directory}: {e}")
    return count

def run_pmd_for_commit(pmd_path, project_dir, ruleset_path, output_file):

    cmd = [
        str(pmd_path), 'check',
        '--dir', str(project_dir),
        '--rulesets', str(ruleset_path),
        '--format', 'json',
        '--report-file', str(output_file),
        '--fail-on-violation', 'false'
    ]
    logging.debug(f"Running PMD command: {' '.join(cmd)}")
    try:
        result = run_command(cmd, check=False, capture=True)

        if result.returncode not in [0, 4]:
            logging.error(f"PMD execution failed for {project_dir} with code {result.returncode}")
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
                 logging.error(f"Error processing PMD results {output_file}: {e}")
                 return False, 0, {}
        else:
            logging.debug(f"PMD found no violations or output empty for {project_dir}.")

        return True, warnings_count, warnings_by_rule

    except FileNotFoundError:
        logging.error(f"PMD executable not found at: {pmd_path}")
        return False, 0, {}
    except Exception as e:
        logging.error(f"An error occurred while running PMD for {project_dir}: {e}")
        return False, 0, {}


def analyze_commit_task(args_tuple):
    commit_hash, base_repo_path, worktree_path, pmd_path, ruleset_path, results_path = args_tuple
    worker_name = multiprocessing.current_process().name
    logging.info(f"Processing commit {commit_hash[:8]}")
    commit_start_time = time.time()


    try:
        run_command(['git', 'checkout', commit_hash, '--force'], cwd=worktree_path)
        logging.debug(f"Checked out {commit_hash[:8]} in {worktree_path.name}")
    except Exception as e:
        logging.error(f"Git checkout failed for {commit_hash[:8]} in {worktree_path.name}: {e}")
        return commit_hash, False, 0, 0, {}, time.time() - commit_start_time # Return failure data


    java_files_count = count_java_files(worktree_path)
    logging.debug(f"Found {java_files_count} Java files in {worktree_path.name}.")

    commit_output_file = results_path / f"{commit_hash}.json"
    pmd_success, warnings_count, warnings_by_rule = run_pmd_for_commit(
        pmd_path, worktree_path, ruleset_path, commit_output_file
    )

    commit_duration = time.time() - commit_start_time
    logging.info(f"Commit {commit_hash[:8]} processed in {commit_duration:.2f}s by {worker_name}.")
    if commit_duration > 1.0 and pmd_success:
         logging.warning(f"Commit {commit_hash[:8]} took longer than 1.0s ({commit_duration:.2f}s) by {worker_name}")

    return commit_hash, pmd_success, java_files_count, warnings_count, warnings_by_rule, commit_duration


def analyze_repository_parallel(repo_location, output_dir, pmd_path, ruleset_path, num_workers):
    start_time_total = time.time()
    output_path = Path(output_dir).resolve()
    base_repo_path = output_path / 'repo_base'
    results_path = output_path / 'pmd_results'
    summary_file = output_path / 'summary.json'
    worktree_base_path = output_path / 'worktrees'

    # Create output directories
    results_path.mkdir(parents=True, exist_ok=True)
    worktree_base_path.mkdir(parents=True, exist_ok=True)

    repo_cloned_ok = False
    initial_commit_hash = None

    try:
        if not base_repo_path.exists() or not (base_repo_path / ".git").is_dir():
            logging.info(f"Cloning repository from {repo_location} to {base_repo_path}...")
            run_command(['git', 'clone', repo_location, str(base_repo_path)], capture=False)
            logging.info("Base repository cloned successfully.")
        else:
            logging.info(f"Base repository exists at {base_repo_path}. Fetching updates...")
            run_command(['git', 'fetch', '--all', '--prune'], cwd=base_repo_path, capture=False)
            logging.info("Fetch complete.")
        repo_cloned_ok = True


        result = run_command(['git', 'rev-list', '--all', '--reverse'], cwd=base_repo_path, capture=True)
        commits = [line for line in result.stdout.strip().split('\n') if line]
        num_commits = len(commits)
        if num_commits == 0:
            logging.error("No commits found in the repository.")
            return
        initial_commit_hash = commits[0]
        logging.info(f"Found {num_commits} commits to analyze.")

    except Exception as e:
        logging.error(f"Failed during repository setup or commit listing: {e}")
        return

    if not repo_cloned_ok:
        logging.error("Repository cloning/setup failed.")
        return

    worktree_paths = []
    active_worktrees = []
    try:
        for i in range(num_workers):
            wt_path = worktree_base_path / f"wt_{i}"
            worktree_paths.append(wt_path)
            if wt_path.exists():
                logging.warning(f"Worktree directory {wt_path} already exists. Attempting to remove and recreate.")
                try:

                    run_command(['git', 'worktree', 'remove', '--force', str(wt_path.name)], cwd=worktree_base_path)
                except Exception:
                    pass
                try:
                    if wt_path.exists():
                        shutil.rmtree(wt_path)
                except Exception as e:
                     logging.error(f"Could not cleanup existing worktree dir {wt_path}: {e}. Aborting.")
                     raise

            logging.info(f"Creating worktree {i} at {wt_path} linked to {initial_commit_hash[:8]}")
            run_command(['git', '-C', str(base_repo_path), 'worktree', 'add', '--detach', str(wt_path), initial_commit_hash])
            active_worktrees.append(wt_path)


        tasks = []
        for i, commit_hash in enumerate(commits):
            worker_index = i % num_workers
            worktree_path = worktree_paths[worker_index]
            tasks.append((commit_hash, base_repo_path, worktree_path, pmd_path, ruleset_path, results_path))


        logging.info(f"Starting analysis with {num_workers} worker processes...")
        pool_results = []
        with multiprocessing.Pool(processes=num_workers) as pool:

            results_iterator = pool.imap_unordered(analyze_commit_task, tasks)
            total_processed = 0
            for result in results_iterator:
                pool_results.append(result)
                total_processed += 1
                if total_processed % 100 == 0:
                     logging.info(f"Progress: {total_processed}/{num_commits} commits processed.")


        logging.info("All worker tasks completed.")


        processed_ok_commits = 0
        all_java_files_counts = []
        all_warnings_counts = []
        total_warnings_by_rule = {}
        failed_commits_count = 0

        for result_tuple in pool_results:
            commit_hash, pmd_success, java_files_count, warnings_count, warnings_by_rule, _ = result_tuple
            if pmd_success:
                processed_ok_commits += 1
                all_java_files_counts.append(java_files_count)
                all_warnings_counts.append(warnings_count)
                for rule, count in warnings_by_rule.items():
                    total_warnings_by_rule[rule] = total_warnings_by_rule.get(rule, 0) + count
            else:
                failed_commits_count += 1
                # Optionally log the failed commit hash here if not logged sufficiently in worker
                logging.debug(f"Commit {commit_hash[:8]} analysis failed or PMD had errors.")


        if processed_ok_commits > 0:

            avg_java_files = sum(all_java_files_counts) / processed_ok_commits if processed_ok_commits > 0 else 0
            avg_warnings = sum(all_warnings_counts) / processed_ok_commits if processed_ok_commits > 0 else 0
            summary_data = {
                "location": repo_location,
                "stat_of_repository": {
                    "number_of_commits_analyzed_successfully": processed_ok_commits,
                    "number_of_commits_failed_or_skipped": failed_commits_count,
                    "total_commits_in_repo": num_commits,
                    "avg_of_num_java_files": round(avg_java_files, 2),
                    "avg_of_num_warnings": round(avg_warnings, 2),
                },
                "stat_of_warnings": dict(sorted(total_warnings_by_rule.items())) # Sort rules alphabetically
            }
        else:
             summary_data = {
                "location": repo_location,
                "stat_of_repository": {
                    "number_of_commits_analyzed_successfully": 0,
                    "number_of_commits_failed_or_skipped": failed_commits_count,
                    "total_commits_in_repo": num_commits,
                    "avg_of_num_java_files": 0,
                    "avg_of_num_warnings": 0,
                },
                "stat_of_warnings": {}
            }
             logging.warning("No commits were successfully processed with PMD.")

        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary_data, f, indent=4, ensure_ascii=False)
        logging.info(f"Summary report saved to {summary_file}")

    except Exception as e:
        logging.error(f"An error occurred during the main analysis process: {e}", exc_info=True)
    finally:
        logging.info("Cleaning up worktrees...")
        for wt_path in active_worktrees:
             if wt_path.exists():
                try:
                    logging.debug(f"Removing worktree: {wt_path.name}")

                    run_command(['git', '-C', str(base_repo_path), 'worktree', 'remove', '--force', str(wt_path.name)])
                    if wt_path.exists():
                         logging.debug(f"Force removing directory {wt_path}")
                         shutil.rmtree(wt_path, ignore_errors=True)
                except Exception as e:
                    logging.warning(f"Could not remove worktree {wt_path}: {e}. Manual cleanup might be required.")
        logging.info("Worktree cleanup finished.")



    end_time_total = time.time()
    total_duration = end_time_total - start_time_total
    avg_time_per_commit = total_duration / num_commits if num_commits > 0 else 0
    logging.info(f"Total analysis time: {total_duration:.2f} seconds using {num_workers} workers.")
    logging.info(f"Overall average time per commit: {avg_time_per_commit:.2f} seconds")

    if avg_time_per_commit <= 1.0:
        logging.info("Performance requirement (<= 1.0s/commit overall) met.")
    else:
        logging.warning("Performance requirement (> 1.0s/commit overall) NOT met.")

if __name__ == "__main__":
    default_workers = max(1, os.cpu_count() - 1 if os.cpu_count() else 1) # Leave one core free usually

    parser = argparse.ArgumentParser(description="Analyze Git repository history with PMD in parallel.")
    parser.add_argument("repo_location", help="URL or local path of the Git repository.")
    parser.add_argument("-o", "--output-dir", default="analysis_results_parallel", help="Directory to store results.")
    parser.add_argument("-p", "--pmd-path", required=True, help="Path to the PMD executable.")
    parser.add_argument("-r", "--ruleset", required=True, help="Path to the PMD ruleset XML file.")
    parser.add_argument("-w", "--workers", type=int, default=default_workers, help=f"Number of parallel worker processes (Default: {default_workers})")

    args = parser.parse_args()


    pmd_exec_path = Path(args.pmd_path).resolve()
    ruleset_file_path = Path(args.ruleset).resolve()
    output_dir_path = Path(args.output_dir).resolve()

    if not pmd_exec_path.exists():
        print(f"Error: PMD executable not found at '{pmd_exec_path}'")
        exit(1)
    if not ruleset_file_path.is_file():
        print(f"Error: PMD ruleset file not found at '{ruleset_file_path}'")
        exit(1)
    if args.workers < 1:
        print("Error: Number of workers must be at least 1.")
        exit(1)

    analyze_repository_parallel(
        args.repo_location,
        output_dir_path,
        pmd_exec_path,
        ruleset_file_path,
        args.workers
    )