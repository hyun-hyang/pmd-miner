# tests/test_pmd_runner.py

import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import json

# 프로젝트 루트 디렉토리를 sys.path에 추가 (tests 폴더가 하위에 있으므로)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.pmd_runner import run_pmd, parse_pmd_output


class TestPMDRunner(unittest.TestCase):
    def setUp(self):
        # 더미 Git 저장소 역할을 할 임시 디렉토리 생성
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_path = self.temp_dir.name

        # 더미 Java 파일 생성 (Java 파일 개수 검증을 위해)
        self.java_file_path = os.path.join(self.repo_path, "Dummy.java")
        with open(self.java_file_path, "w", encoding="utf-8") as f:
            f.write("public class Dummy {}")

        # 룰셋 파일 경로 (더미 값)
        self.ruleset = "dummy_ruleset.xml"

        # PMD의 더미 XML 출력 (실제 PMD 명령 대신 사용)
        self.dummy_xml = """<?xml version="1.0" encoding="UTF-8"?>
<pmd>
  <file name="Dummy.java">
    <violation rule="DummyRule">This is a dummy violation message</violation>
  </file>
</pmd>
"""

    def tearDown(self):
        # 임시 디렉토리 삭제
        self.temp_dir.cleanup()

    @patch("app.pmd_runner.subprocess.run")
    def test_run_pmd(self, mock_run):
        # subprocess.run을 mocking해서 더미 XML을 리턴하도록 설정
        mock_result = MagicMock()
        mock_result.stdout = self.dummy_xml
        mock_result.stderr = ""
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        # PMD 실행 함수 호출
        warnings_dict, java_file_count = run_pmd(self.repo_path, self.ruleset)

        # Java 파일 개수가 1개인지 확인
        self.assertEqual(java_file_count, 1)

        # warnings_dict에 파일 및 위반 정보가 올바르게 파싱되었는지 검사
        self.assertIn("files", warnings_dict)
        self.assertEqual(len(warnings_dict["files"]), 1)
        file_info = warnings_dict["files"][0]
        self.assertEqual(file_info["name"], "Dummy.java")
        self.assertEqual(len(file_info["violations"]), 1)
        self.assertEqual(file_info["violations"][0]["rule"], "DummyRule")
        self.assertEqual(file_info["violations"][0]["message"], "This is a dummy violation message")

    def test_parse_pmd_output(self):
        # 더미 PMD 결과 dictionary 생성
        dummy_warnings = {
            "files": [
                {
                    "name": "Dummy.java",
                    "violations": [
                        {"rule": "DummyRule", "message": "Dummy message"}
                    ]
                }
            ]
        }

        # JSON 문자열로 변환 후, 다시 파싱하여 검사
        json_str = parse_pmd_output(dummy_warnings)
        data = json.loads(json_str)
        self.assertIn("files", data)
        self.assertEqual(data["files"][0]["name"], "Dummy.java")


if __name__ == '__main__':
    unittest.main()
