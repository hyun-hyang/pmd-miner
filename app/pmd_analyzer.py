import argparse
import json
import os
import shutil
import subprocess
import time
import logging
from pathlib import Path
from git import Repo, GitCommandError

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def count_java_files(directory):
    """지정된 디렉토리 내의 .java 파일 개수를 셉니다."""
    count = 0
    for _, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".java"):
                count += 1
    return count

def run_pmd(pmd_path, project_dir, ruleset_path, output_file):
    """PMD를 실행하고 결과를 JSON 파일로 저장합니다."""
    cmd = [
        pmd_path, 'check',
        '--dir', str(project_dir),
        '--rulesets', str(ruleset_path),
        '--format', 'json',
        '--report-file', str(output_file)
    ]
    logging.info(f"Running PMD: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, encoding='utf-8', errors='ignore')
        if result.returncode != 0 and result.returncode != 4:
            logging.error(f"PMD execution failed with return code {result.returncode}")
            logging.error(f"Stderr: {result.stderr}")
            logging.error(f"Stdout: {result.stdout}")
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
                 logging.info(f"PMD found {warnings_count} warnings.")

             except json.JSONDecodeError:
                 logging.error(f"Failed to parse PMD output JSON: {output_file}")
                 return False, 0, {} # 파싱 실패
             except Exception as e:
                 logging.error(f"Error processing PMD results for {output_file}: {e}")
                 return False, 0, {}
        else:
            logging.info("PMD ran successfully, but no violations found or output file is empty.")

        return True, warnings_count, warnings_by_rule

    except FileNotFoundError:
        logging.error(f"PMD executable not found at: {pmd_path}")
        return False, 0, {}
    except Exception as e:
        logging.error(f"An error occurred while running PMD: {e}")
        return False, 0, {}


def analyze_repository(repo_location, output_dir, pmd_path, ruleset_path):
    """Git 저장소를 분석하고 PMD 결과를 수집 및 요약합니다."""
    start_time_total = time.time()
    repo_path = Path(output_dir) / 'repo'
    results_path = Path(output_dir) / 'pmd_results'
    summary_file = Path(output_dir) / 'summary.json'

    # 출력 디렉토리 생성
    results_path.mkdir(parents=True, exist_ok=True)

    repo = None
    original_branch = None
    try:
        # 저장소 클론 또는 열기
        if repo_path.exists():
            logging.info(f"Repository already exists at {repo_path}. Opening...")
            repo = Repo(repo_path)
            original_branch = repo.active_branch
            logging.info("Fetching latest changes...")
            repo.remotes.origin.fetch()
        else:
            logging.info(f"Cloning repository from {repo_location} to {repo_path}...")
            repo = Repo.clone_from(repo_location, repo_path)
            original_branch = repo.active_branch
            logging.info("Repository cloned successfully.")

        # 커밋 목록 가져오기
        commits = list(repo.iter_commits(rev=original_branch, reverse=True))
        num_commits = len(commits)
        logging.info(f"Found {num_commits} commits to analyze.")

        all_java_files_counts = []
        all_warnings_counts = []
        total_warnings_by_rule = {}
        processed_commits = 0

        # 각 커밋 처리
        for i, commit in enumerate(commits):
            commit_hash = commit.hexsha
            commit_time_start = time.time()
            logging.info(f"Processing commit {i+1}/{num_commits}: {commit_hash[:8]} ({commit.summary})")

            try:
                # 해당 커밋으로 체크아웃
                repo.git.checkout(commit_hash, force=True)
                logging.debug(f"Checked out commit {commit_hash[:8]}")

                # Java 파일 수 계산
                java_files_count = count_java_files(repo_path)
                all_java_files_counts.append(java_files_count)
                logging.debug(f"Found {java_files_count} Java files.")

                # PMD 실행 및 결과 저장
                commit_output_file = results_path / f"{commit_hash}.json"
                pmd_success, warnings_count, warnings_by_rule = run_pmd(pmd_path, repo_path, ruleset_path, commit_output_file)

                if pmd_success:
                    all_warnings_counts.append(warnings_count)
                    for rule, count in warnings_by_rule.items():
                        total_warnings_by_rule[rule] = total_warnings_by_rule.get(rule, 0) + count
                    processed_commits += 1
                else:
                    logging.warning(f"Skipping statistics for commit {commit_hash[:8]} due to PMD error.")

                commit_time_end = time.time()
                commit_duration = commit_time_end - commit_time_start
                logging.info(f"Commit {commit_hash[:8]} processed in {commit_duration:.2f} seconds.")

                if commit_duration > 1.0:
                     logging.warning(f"Commit {commit_hash[:8]} took longer than 1.0s ({commit_duration:.2f}s)")


            except GitCommandError as e:
                logging.error(f"Git error during checkout for commit {commit_hash[:8]}: {e}")
                continue
            except Exception as e:
                logging.error(f"Unexpected error processing commit {commit_hash[:8]}: {e}")
                continue

        # 원래 브랜치로 복귀
        logging.info(f"Returning to original branch: {original_branch.name}")
        repo.git.checkout(original_branch.name, force=True)

        # 최종 요약 통계 계산
        if processed_commits > 0:
            avg_java_files = sum(all_java_files_counts) / len(all_java_files_counts) if all_java_files_counts else 0
            avg_warnings = sum(all_warnings_counts) / processed_commits if processed_commits > 0 else 0
            summary_data = {
                "location": repo_location,
                "stat_of_repository": {
                    "number_of_commits_analyzed": processed_commits,
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
             logging.warning("No commits were successfully processed with PMD.")


        # 요약 파일 저장 (R8 충족)
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary_data, f, indent=4, ensure_ascii=False)
        logging.info(f"Summary report saved to {summary_file}")

    except GitCommandError as e:
        logging.error(f"Git error: {e}")
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
    finally:
        if repo_path.exists():
            logging.info(f"Cleaning up temporary repository at {repo_path}...")
            try:
                if repo:
                    repo.close()
            except Exception as e:
                logging.warning(f"Could not completely clean up {repo_path}: {e}")
        pass

    end_time_total = time.time()
    total_duration = end_time_total - start_time_total
    avg_time_per_commit = total_duration / num_commits if num_commits > 0 else 0
    logging.info(f"Total analysis time: {total_duration:.2f} seconds")
    logging.info(f"Average time per commit: {avg_time_per_commit:.2f} seconds")

    if avg_time_per_commit <= 1.0:
        logging.info("Performance requirement (<= 1.0s/commit) met.")
    else:
        logging.warning("Performance requirement (> 1.0s/commit) NOT met.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze Git repository history with PMD.")
    parser.add_argument("repo_location", help="URL or local path of the Git repository (must be a Java project).") # R5
    parser.add_argument("-o", "--output-dir", default="analysis_results", help="Directory to store PMD results and summary. (Default: analysis_results)") # R7 (Optional Parameter)
    parser.add_argument("-p", "--pmd-path", required=True, help="Path to the PMD executable (e.g., '/path/to/pmd-bin-X.Y.Z/bin/pmd' or 'pmd.bat').")
    parser.add_argument("-r", "--ruleset", required=True, help="Path to the PMD ruleset XML file.") # R9

    args = parser.parse_args()

    if not Path(args.pmd_path).exists():
        print(f"Error: PMD executable not found at '{args.pmd_path}'")
        exit(1)
    if not Path(args.ruleset).exists():
        print(f"Error: PMD ruleset file not found at '{args.ruleset}'")
        exit(1)

    analyze_repository(args.repo_location, args.output_dir, args.pmd_path, args.ruleset)