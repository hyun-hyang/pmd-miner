# tests/test_git_utils.py

import sys
import os

# 프로젝트 루트 디렉토리를 sys.path에 추가 (테스트 파일이 tests 폴더 안에 있으므로)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

import tempfile
import unittest
from app.old.git_utils import clone_repo, get_all_commits, checkout_commit
from git import Repo


class TestGitUtils(unittest.TestCase):
    def setUp(self):
        # 테스트용 임시 디렉토리 생성
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_url = "https://github.com/apache/commons-lang"
        self.target_dir = os.path.join(self.temp_dir.name, "test_repo")

    def tearDown(self):
        # 테스트 후 임시 디렉토리 정리
        # TemporaryDirectory의 cleanup()을 호출하여 디렉토리 삭제 (shutil.rmtree 대신)
        self.temp_dir.cleanup()

    def test_clone_repo(self):
        # 저장소 클론 후 .git 폴더가 존재하는지 확인
        cloned_path = clone_repo(self.repo_url, self.target_dir)
        git_folder = os.path.join(cloned_path, ".git")
        self.assertTrue(os.path.exists(git_folder), "'.git' 폴더가 존재해야 합니다.")

    def test_get_all_commits(self):
        # 클론한 저장소에서 커밋 리스트를 제대로 불러오는지 검증
        cloned_path = clone_repo(self.repo_url, self.target_dir)
        commits = get_all_commits(cloned_path)
        self.assertGreater(len(commits), 0, "커밋이 하나 이상 있어야 합니다.")

    def test_checkout_commit(self):
        # 첫 번째 커밋으로 체크아웃 후 HEAD가 맞는지 검증
        cloned_path = clone_repo(self.repo_url, self.target_dir)
        commits = get_all_commits(cloned_path)
        self.assertGreater(len(commits), 0, "커밋이 하나 이상 있어야 합니다.")
        first_commit = commits[0]

        # 첫 번째 커밋으로 체크아웃
        checkout_commit(cloned_path, first_commit)

        # 현재 HEAD가 첫 번째 커밋인지 확인
        repo = Repo(cloned_path)
        current_commit = repo.git.rev_parse("HEAD")
        self.assertEqual(current_commit, first_commit, "HEAD가 첫 번째 커밋과 같아야 합니다.")


if __name__ == '__main__':
    unittest.main()
