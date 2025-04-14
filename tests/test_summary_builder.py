# tests/test_summary_builder.py

import sys
import os
import tempfile
import unittest
import json

# 프로젝트 루트 경로 추가
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.summary_builder import SummaryBuilder

class TestSummaryBuilder(unittest.TestCase):

    def setUp(self):
        self.summary = SummaryBuilder()

    def test_add_commit(self):
        # 첫번째 커밋: 3개의 자바 파일, 2개의 위반 (UnusedVariable, LongMethod)
        warnings_dict = {
            "files": [
                {
                    "name": "Test.java",
                    "violations": [
                        {"rule": "UnusedVariable", "message": "Unused variable found."},
                        {"rule": "LongMethod", "message": "Method is too long."}
                    ]
                }
            ]
        }
        self.summary.add_commit(3, warnings_dict)

        # 두번째 커밋: 4개의 자바 파일, 위반 없음
        warnings_no_violations = {
            "files": [
                {
                    "name": "AnotherTest.java",
                    "violations": []
                }
            ]
        }
        self.summary.add_commit(4, warnings_no_violations)

        # 커밋 수, 총 자바 파일 수, 총 경고 수 검증
        self.assertEqual(self.summary.commit_count, 2)
        self.assertEqual(self.summary.total_java_files, 7)
        self.assertEqual(self.summary.total_warnings, 2)

        # 위반 rule별 누적 카운드 검증
        self.assertEqual(self.summary.warning_counts.get("UnusedVariable"), 1)
        self.assertEqual(self.summary.warning_counts.get("LongMethod"), 1)

    def test_save(self):
        # 임의 커밋 데이터 추가: 5개의 자바 파일, UnusedVariable 1건
        warnings_dict = {
            "files": [
                {
                    "name": "Test.java",
                    "violations": [
                        {"rule": "UnusedVariable", "message": "Unused variable found."}
                    ]
                }
            ]
        }
        self.summary.add_commit(5, warnings_dict)

        # 임시 파일에 summary 저장
        with tempfile.NamedTemporaryFile(delete=False, mode="w+", encoding="utf-8") as tmp_file:
            summary_path = tmp_file.name

        output_location = "dummy_output"
        self.summary.save(summary_path, output_location)

        # 생성된 summary 파일 읽어서 내용 검증
        with open(summary_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        os.remove(summary_path)  # 임시 파일 삭제

        self.assertEqual(data["location"], output_location)
        self.assertEqual(data["stat_of_repository"]["number_of_commits"], 1)
        self.assertEqual(data["stat_of_repository"]["avg_of_num_java_files"], 5)
        self.assertEqual(data["stat_of_repository"]["avg_of_num_warnings"], 1)
        self.assertEqual(data["stat_of_warnings"].get("UnusedVariable"), 1)

if __name__ == '__main__':
    unittest.main()
