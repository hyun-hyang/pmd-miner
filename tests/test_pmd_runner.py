# tests/test_pmd_runner.py

import sys
import os
import tempfile
import unittest
import shutil
from app.pmd_runner import run_pmd, parse_pmd_output
from app.git_utils import clone_repo


class TestPMDRunner(unittest.TestCase):
    def setUp(self):
        # 테스트용 임시 디렉토리 생성
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_url = "https://github.com/apache/commons-lang"
        # 클론될 경로 (임시 디렉토리 내)
        self.repo_path = os.path.join(self.temp_dir.name, "commons-lang")
        clone_repo(self.repo_url, self.repo_path)
        # ruleset.xml 파일이 tests 폴더에 있으므로, 해당 위치를 지정
        self.ruleset_path = os.path.join(os.path.dirname(__file__), "ruleset.xml")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_pmd_runner(self):
        warnings_dict, java_file_count = run_pmd(self.repo_path, self.ruleset_path)
        json_output = parse_pmd_output(warnings_dict)
        print("Java file count:", java_file_count)
        print("PMD JSON Output:", json_output)
        self.assertGreater(java_file_count, 0, "Expected some Java files in the repository")
        # 만약 PMD가 정상적으로 분석했다면 error 키가 없어야 함.
        self.assertNotIn("error", warnings_dict)


if __name__ == '__main__':
    unittest.main()
