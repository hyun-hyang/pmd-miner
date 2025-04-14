# app/git_utils.py

import os
import shutil
from git import Repo


def clone_repo(repo_url: str, target_dir: str) -> str:
    """
    주어진 repo_url을 target_dir에 클론한다.
    만약 target_dir이 이미 존재하면 삭제 후 재클론한다.

    Args:
        repo_url (str): 클론할 Git 저장소 URL.
        target_dir (str): 저장할 로컬 디렉토리 경로.

    Returns:
        str: 클론된 저장소의 경로.
    """
    if os.path.exists(target_dir):
        shutil.rmtree(target_dir)
    print(f"Cloning repository from {repo_url} into {target_dir} ...")
    Repo.clone_from(repo_url, target_dir)
    return os.path.abspath(target_dir)


def get_all_commits(repo_path: str) -> list:
    """
    저장소 경로(repo_path)에서 모든 커밋 해시를 가져온다.
    (기본적으로 현재 활성 브랜치의 커밋들을 시간순(초기 -> 최신)으로 반환)

    Args:
        repo_path (str): Git 저장소 로컬 경로.

    Returns:
        list: 커밋 해시 문자열 리스트.
    """
    repo = Repo(repo_path)
    # 사용 중인 기본 브랜치가 무엇인지 감안하여 가져온다.
    # 기본적으로 현재 체크아웃 된 브랜치의 커밋 목록.
    commits = list(repo.iter_commits(repo.active_branch.name))
    commits.reverse()  # 초기 커밋부터 최신 커밋 순으로 정렬
    return [commit.hexsha for commit in commits]


def checkout_commit(repo_path: str, commit_hash: str):
    """
    저장소(repo_path)를 지정된 commit_hash로 체크아웃한다.

    Args:
        repo_path (str): Git 저장소 로컬 경로.
        commit_hash (str): 체크아웃할 커밋 해시.
    """
    repo = Repo(repo_path)
    print(f"Checking out commit {commit_hash} ...")
    repo.git.checkout(commit_hash)
