import os
import argparse
from git_utils import clone_repo, get_all_commits, checkout_commit
from pmd_runner import run_pmd, parse_pmd_output
from summary_builder import SummaryBuilder


def main():
    parser = argparse.ArgumentParser(description="PMD Repository Miner")
    parser.add_argument("--repo", required=True, help="Git repository URL")
    parser.add_argument("--ruleset", required=True, help="Path to PMD ruleset XML file")
    parser.add_argument("--output_dir", required=True, help="Directory to save JSON output files")
    parser.add_argument("--temp_dir", default="./temp_repo", help="Temporary directory for cloning repository")

    args = parser.parse_args()

    # 클론 저장소 준비
    print("Cloning repository...")
    repo_path = clone_repo(args.repo, args.temp_dir)

    # 모든 커밋 해시 취득 (초기 -> 최신 순)
    commits = get_all_commits(repo_path)
    print(f"Found {len(commits)} commits.")

    # SummaryBuilder 인스턴스 생성
    summary = SummaryBuilder()

    # 출력 디렉토리 없으면 생성
    if not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir)

    # # 기존 for 루프 대신, 첫 번째 commit만 처리 (예시)
    # if commits:
    #     commit_hash = commits[0]  # 또는 테스트할 commit 해시 직접 지정
    #     print(f"Processing commit: {commit_hash} ...")
    #     checkout_commit(repo_path, commit_hash)
    #     warnings_dict, java_file_count = run_pmd(repo_path, args.ruleset)
    #
    #     commit_file = os.path.join(args.output_dir, f"{commit_hash}.json")
    #     with open(commit_file, "w", encoding="utf-8") as f:
    #         f.write(parse_pmd_output(warnings_dict))
    #
    #     # Summary 업데이트
    #     summary.add_commit(java_file_count, warnings_dict)
    #     # 결과 기록 등 처리
    #
    #     commit_hash = commits[1]  # 또는 테스트할 commit 해시 직접 지정
    #     print(f"Processing commit: {commit_hash} ...")
    #     checkout_commit(repo_path, commit_hash)
    #     warnings_dict, java_file_count = run_pmd(repo_path, args.ruleset)
    #
    #     commit_file = os.path.join(args.output_dir, f"{commit_hash}.json")
    #     with open(commit_file, "w", encoding="utf-8") as f:
    #         f.write(parse_pmd_output(warnings_dict))
    #
    #     # Summary 업데이트
    #     summary.add_commit(java_file_count, warnings_dict)
    #     # 결과 기록 등 처리
    # else:
    #     print("No commits found.")
    #
    # # 전체 결과를 summary.json 파일로 저장
    # summary_file = os.path.join(args.output_dir, "summary.json")
    # summary.save(summary_file, os.path.abspath(args.output_dir))
    #
    # print("Processing complete.")
    # print("Summary saved to:", summary_file)

    # 각 커밋마다 PMD 분석 실행
    for idx, commit_hash in enumerate(commits):
        print(f"[{idx + 1}/{len(commits)}] Processing commit: {commit_hash} ...")
        checkout_commit(repo_path, commit_hash)
        warnings_dict, java_file_count = run_pmd(repo_path, args.ruleset)

        # 커밋별 결과를 JSON 파일로 저장
        commit_file = os.path.join(args.output_dir, f"{commit_hash}.json")
        with open(commit_file, "w", encoding="utf-8") as f:
            f.write(parse_pmd_output(warnings_dict))

        # Summary 업데이트
        summary.add_commit(java_file_count, warnings_dict)

    # 전체 결과를 summary.json 파일로 저장
    summary_file = os.path.join(args.output_dir, "summary.json")
    summary.save(summary_file, os.path.abspath(args.output_dir))

    print("Processing complete.")
    print("Summary saved to:", summary_file)


if __name__ == "__main__":
    main()
