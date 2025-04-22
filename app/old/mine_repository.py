import argparse
import json
import os
import subprocess
import shutil
import time
import logging
from collections import defaultdict
from pathlib import Path

# --- Configuration ---
# Adjust PMD_CMD if your PMD executable is named differently or needs a full path
# Example for downloaded distribution: '/path/to/pmd-bin-X.Y.Z/bin/pmd'
# If PMD is in PATH, 'pmd' should work. Check with 'pmd --version' in your terminal.
PMD_CMD = os.environ.get("PMD_RUN_SCRIPT", "pmd") # Use environment variable or default to 'pmd'
# Use 'run.sh' for older PMD versions if 'pmd' doesn't work

LOG_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

# --- Helper Functions ---

def run_command(command, cwd=None, capture=True, check=True, timeout=None):
    """Executes a shell command."""
    logging.debug(f"Running command: {' '.join(command)} in {cwd or os.getcwd()}")
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=capture, # Pass capture argument here
            text=True,
            check=check,            # check=True will raise CalledProcessError on non-zero exit
            timeout=timeout
        )
        # ----- FIX -----
        # Only try to log stdout/stderr if capture was True
        if capture:
            # Check if stdout/stderr are not None before slicing, just in case
            stdout_snippet = (result.stdout or "")[:100]
            stderr_snippet = (result.stderr or "")[:100]
            logging.debug(f"Command stdout: {stdout_snippet}...")
            logging.debug(f"Command stderr: {stderr_snippet}...")
        # ---------------
        return result
    except subprocess.CalledProcessError as e:
        # Log details from the exception object if check=True caused the failure
        logging.error(f"Command failed: {' '.join(command)}")
        logging.error(f"Return code: {e.returncode}")
        # Exception object 'e' might have stdout/stderr even if capture was initially False
        if e.stderr:
            logging.error(f"Stderr: {e.stderr}")
        if e.stdout:
             logging.error(f"Stdout: {e.stdout}")
        # If check=True, this exception means the command failed, re-raise it
        # If check=False, this block won't be reached for non-zero exits unless another error occurs
        raise
    except FileNotFoundError:
        logging.error(f"Command not found: {command[0]}. Is it installed and in PATH?")
        raise
    except subprocess.TimeoutExpired as e:
        logging.error(f"Command timed out after {timeout} seconds: {' '.join(command)}")
        # Log output/error if available on timeout exception
        if e.stderr:
            logging.error(f"Timeout Stderr: {e.stderr}")
        if e.stdout:
             logging.error(f"Timeout Stdout: {e.stdout}")
        raise

def count_java_files(directory):
    """Counts the number of .java files in a directory."""
    count = 0
    for _, _, files in os.walk(directory):
        for filename in files:
            if filename.lower().endswith(".java"):
                count += 1
    return count

# --- Core Logic ---

def get_commit_hashes(repo_path):
    """Gets a list of all commit hashes in reverse chronological order."""
    result = run_command(['git', 'rev-list', '--all'], cwd=repo_path)
    hashes = result.stdout.strip().split('\n')
    # Process oldest first for chronological analysis
    return [h for h in reversed(hashes) if h]

def analyze_commit(commit_hash, repo_path, ruleset_path, output_dir):
    """Checks out a commit, runs PMD, and parses the results."""
    commit_start_time = time.time()
    commit_output_file = output_dir / f"{commit_hash}.json"
    pmd_report_temp_file = output_dir / f"{commit_hash}_pmd_report.json"

    # 1. Checkout the specific commit
    try:
        # Use --force to discard potential local changes from previous checkouts
        run_command(['git', 'checkout', commit_hash, '--force'], cwd=repo_path, capture=False, timeout=60)
        logging.info(f"Checked out commit: {commit_hash}")
    except Exception as e:
        logging.error(f"Failed to checkout commit {commit_hash}: {e}")
        return None # Indicate failure for this commit

    # 2. Count Java files (do this *after* checkout)
    num_java_files = count_java_files(repo_path)

    # 3. Run PMD
    # PMD Command: pmd check -d <source_dir> -f json -R <ruleset> --report-file <output>
    pmd_command = [
        PMD_CMD, 'check',
        '-d', str(repo_path),
        '-f', 'json',
        '-R', str(ruleset_path),
        '--report-file', str(pmd_report_temp_file),
        # Add other PMD options if needed, e.g., -cache <path>, --fail-on-violation false
        '--fail-on-violation', 'false' # Important: Don't stop analysis if violations found
    ]

    num_warnings = 0
    warnings_by_rule = defaultdict(int)
    pmd_success = False

    try:
        # Run PMD. Don't use check=True initially, as PMD might exit with non-zero status
        # even on successful analysis with warnings found.
        # Set a reasonable timeout (e.g., 5 minutes)
        pmd_result = run_command(pmd_command, cwd=None, capture=True, check=False, timeout=300)

        # Check if PMD report file was created
        if pmd_report_temp_file.exists() and pmd_report_temp_file.stat().st_size > 0:
             # Check PMD's specific exit codes if needed (see PMD docs)
             # 0 = success, no violations
             # 4 = success, violations found (if --fail-on-violation false)
             # Other non-zero usually indicates an error.
             if pmd_result.returncode not in [0, 4] and "INFO: Ruleset processing summary" not in pmd_result.stderr : # Simple check for error indicators
                 logging.warning(f"PMD may have encountered issues for commit {commit_hash}. Stderr: {pmd_result.stderr}")
                 # Decide if you want to trust the potentially incomplete JSON output or skip

             # 4. Parse PMD JSON Output
             try:
                 with open(pmd_report_temp_file, 'r', encoding='utf-8') as f:
                     pmd_data = json.load(f)

                 # PMD JSON format v6+: Contains 'files' array
                 if 'files' in pmd_data:
                     for file_entry in pmd_data.get('files', []):
                         violations = file_entry.get('violations', [])
                         num_warnings += len(violations)
                         for violation in violations:
                             rule_name = violation.get('rule')
                             if rule_name:
                                 warnings_by_rule[rule_name] += 1
                     pmd_success = True # Mark as successfully processed
                 else:
                      logging.warning(f"PMD JSON format unexpected or empty for {commit_hash}. Keys: {pmd_data.keys()}")


             except json.JSONDecodeError as e:
                 logging.error(f"Failed to parse PMD JSON output for commit {commit_hash}: {e}")
             except Exception as e:
                  logging.error(f"Error processing PMD results for {commit_hash}: {e}")

        else:
            logging.error(f"PMD report file not found or empty for commit {commit_hash}. PMD stderr: {pmd_result.stderr}")
            # If PMD command itself failed earlier, the exception would have been caught

    except subprocess.TimeoutExpired:
        logging.error(f"PMD timed out for commit {commit_hash}")
    except Exception as e:
        logging.error(f"Failed to run PMD for commit {commit_hash}: {e}")
    finally:
        # Save per-commit results (even if PMD failed, might want basic info)
        commit_data = {
            "commit_hash": commit_hash,
            "pmd_success": pmd_success,
            "num_java_files": num_java_files,
            "num_warnings": num_warnings,
            "warnings_by_rule": dict(warnings_by_rule), # Convert defaultdict for JSON
            "analysis_duration_sec": time.time() - commit_start_time
        }
        try:
            with open(commit_output_file, 'w', encoding='utf-8') as f:
                json.dump(commit_data, f, indent=4)
        except Exception as e:
             logging.error(f"Failed to write commit JSON {commit_output_file}: {e}")

        # Clean up the temporary PMD report file
        if pmd_report_temp_file.exists():
            try:
                pmd_report_temp_file.unlink()
            except OSError as e:
                logging.warning(f"Could not delete temp PMD report {pmd_report_temp_file}: {e}")

    if pmd_success:
        logging.info(f"Commit {commit_hash}: {num_java_files} Java files, {num_warnings} warnings.")
        return commit_data
    else:
        logging.warning(f"PMD analysis failed or produced no valid output for commit {commit_hash}.")
        # Return the commit data structure but indicate failure
        return commit_data # Or return None if you prefer to exclude failed commits from aggregate stats

# --- Main Execution ---

def main():
    parser = argparse.ArgumentParser(description="Run PMD analysis on each commit of a Git repository.")
    parser.add_argument("repo_url", help="URL or local path of the Git repository.")
    parser.add_argument("ruleset", help="Path to the PMD ruleset XML file.")
    parser.add_argument("output_dir", help="Directory to store analysis results.")
    parser.add_argument("--clone-dir", help="Temporary directory to clone the repository into (default: output_dir/repo).", default=None)
    parser.add_argument("--keep-repo", action="store_true", help="Keep the cloned repository after analysis.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging.")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    start_time = time.time()

    # --- Validate Inputs ---
    ruleset_path = Path(args.ruleset).resolve()
    if not ruleset_path.is_file():
        logging.error(f"Ruleset file not found: {ruleset_path}")
        return 1

    output_path = Path(args.output_dir).resolve()
    commit_results_path = output_path / "commit_results"

    # Create output directories
    try:
        output_path.mkdir(parents=True, exist_ok=True)
        commit_results_path.mkdir(exist_ok=True)
    except OSError as e:
        logging.error(f"Failed to create output directories in {output_path}: {e}")
        return 1

    clone_path = Path(args.clone_dir).resolve() if args.clone_dir else output_path / "repo"

    # --- Setup Repository ---
    repo_exists = clone_path.exists() and (clone_path / ".git").is_dir()

    if repo_exists:
        logging.info(f"Repository already exists at {clone_path}. Fetching updates...")
        try:
            # Fetch latest changes and reset to origin's main/master if needed
            # Be cautious with reset if local changes are important
            run_command(['git', 'fetch', '--all'], cwd=clone_path, timeout=120)
            # Optional: Reset to remote default branch if you always want the latest history
            # run_command(['git', 'reset', '--hard', 'origin/HEAD'], cwd=clone_path) # Adjust 'origin/HEAD' if needed
        except Exception as e:
            logging.warning(f"Failed to update existing repository at {clone_path}: {e}. Proceeding with existing data.")
    else:
        logging.info(f"Cloning repository {args.repo_url} into {clone_path}...")
        try:
            run_command(['git', 'clone', args.repo_url, str(clone_path)], timeout=600) # Increased timeout for large clones
        except Exception as e:
            logging.error(f"Failed to clone repository: {e}")
            return 1

    # --- Get Commit List ---
    try:
        commit_hashes = get_commit_hashes(clone_path)
        if not commit_hashes:
            logging.error("No commits found in the repository.")
            return 1
        logging.info(f"Found {len(commit_hashes)} commits to analyze.")
    except Exception as e:
        logging.error(f"Failed to get commit list: {e}")
        return 1

    # --- Analyze Each Commit ---
    all_commit_data = []
    total_commits_processed = 0
    total_java_files = 0
    total_warnings = 0
    aggregate_warning_counts = defaultdict(int)
    failed_commits = 0

    initial_branch = ""
    try: # Remember initial branch/state to restore later
        result = run_command(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], cwd=clone_path)
        initial_branch = result.stdout.strip()
    except Exception:
        logging.warning("Could not determine initial git branch.")


    for i, commit_hash in enumerate(commit_hashes):
        logging.info(f"--- Processing commit {i+1}/{len(commit_hashes)}: {commit_hash} ---")
        commit_data = analyze_commit(commit_hash, clone_path, ruleset_path, commit_results_path)

        if commit_data:
            all_commit_data.append(commit_data) # Store raw data if needed later
            if commit_data["pmd_success"]:
                total_commits_processed += 1
                total_java_files += commit_data["num_java_files"]
                total_warnings += commit_data["num_warnings"]
                for rule, count in commit_data["warnings_by_rule"].items():
                    aggregate_warning_counts[rule] += count
            else:
                failed_commits += 1
        else:
            # analyze_commit logged the error
            failed_commits += 1

        # Performance check
        current_duration = time.time() - start_time
        avg_time_per_commit = current_duration / (i + 1) if (i + 1) > 0 else 0
        logging.info(f"Commit {i+1} done. Average time/commit: {avg_time_per_commit:.2f}s")
        if avg_time_per_commit > 1.5 and i > 10: # Give some buffer over 1.0s/commit
            logging.warning(f"Processing speed is slower than target ({avg_time_per_commit:.2f}s/commit)")


    # --- Restore Git Repo State ---
    if initial_branch and initial_branch != "HEAD": # Avoid checking out detached HEAD if it started there
         try:
            logging.info(f"Restoring repository to initial branch: {initial_branch}")
            run_command(['git', 'checkout', initial_branch], cwd=clone_path, capture=False, timeout=30)
         except Exception as e:
             logging.warning(f"Could not restore initial git state: {e}")
    else:
         try: # Try checking out a default branch like 'main' or 'master'
             for branch in ['main', 'master']:
                 try:
                     run_command(['git', 'checkout', branch], cwd=clone_path, capture=False, timeout=30)
                     logging.info(f"Restored repository to branch: {branch}")
                     break
                 except Exception:
                     continue # Try next default branch name
         except Exception as e:
              logging.warning(f"Could not restore repository to a default branch: {e}")


    # --- Generate Summary Report (R8) ---
    summary_data = {
        "location": str(clone_path),
        "stat_of_repository": {
            "number_of_commits_analyzed": total_commits_processed,
            "number_of_commits_total": len(commit_hashes),
            "number_of_commits_failed": failed_commits,
            "avg_of_num_java_files": (total_java_files / total_commits_processed) if total_commits_processed > 0 else 0,
            "avg_of_num_warnings": (total_warnings / total_commits_processed) if total_commits_processed > 0 else 0,
        },
        "stat_of_warnings": dict(sorted(aggregate_warning_counts.items())), # Sort for consistent output
    }

    summary_file = output_path / "summary.json"
    try:
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary_data, f, indent=4)
        logging.info(f"Summary report saved to: {summary_file}")
    except Exception as e:
        logging.error(f"Failed to write summary JSON file: {e}")

    # --- Cleanup ---
    if not args.keep_repo:
        logging.info(f"Removing cloned repository at {clone_path}...")
        try:
            shutil.rmtree(clone_path)
        except OSError as e:
            logging.error(f"Failed to remove repository directory {clone_path}: {e}")
    else:
        logging.info(f"Keeping cloned repository at {clone_path}.")

    # --- Finish ---
    end_time = time.time()
    total_duration = end_time - start_time
    avg_time = total_duration / len(commit_hashes) if commit_hashes else 0
    logging.info(f"Analysis finished in {total_duration:.2f} seconds.")
    logging.info(f"Average time per commit: {avg_time:.2f} seconds.")
    if avg_time > 1.0:
         logging.warning("Average processing time exceeded the target of 1.0s/commit.")

    return 0 # Success

if __name__ == "__main__":
    exit(main())