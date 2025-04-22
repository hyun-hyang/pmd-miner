# app/summary_builder.py

import json


class SummaryBuilder:
    def __init__(self):
        self.commit_count = 0
        self.total_java_files = 0
        self.total_warnings = 0
        self.warning_counts = {}  # 각 rule별 누적 경고 수

    def add_commit(self, java_file_count: int, warnings: dict):
        """
        각 커밋에서 생성된 결과 데이터를 누적한다.

        Args:
            java_file_count (int): 해당 커밋에서 검출된 자바 파일 수.
            warnings (dict): PMD 실행 결과 파싱한 dictionary.
                              'files' 키 내에 각 파일의 'violations' 리스트 존재.
        """
        self.commit_count += 1
        self.total_java_files += java_file_count

        commit_warning_count = 0
        if warnings and "files" in warnings:
            for file_info in warnings["files"]:
                violations = file_info.get("violations", [])
                commit_warning_count += len(violations)
                for violation in violations:
                    rule = violation.get("rule", "UnknownRule")
                    self.warning_counts[rule] = self.warning_counts.get(rule, 0) + 1

        self.total_warnings += commit_warning_count

    def save(self, summary_path: str, output_location: str):
        """
        누적한 데이터를 바탕으로 summary JSON 파일을 작성한다.

        Args:
            summary_path (str): 저장할 summary JSON 파일의 전체 경로.
            output_location (str): 출력 디렉토리 위치 (summary의 location 필드에 기입).
        """
        if self.commit_count > 0:
            avg_java_files = self.total_java_files / self.commit_count
            avg_warnings = self.total_warnings / self.commit_count
        else:
            avg_java_files = 0
            avg_warnings = 0

        summary_data = {
            "location": output_location,
            "stat_of_repository": {
                "number_of_commits": self.commit_count,
                "avg_of_num_java_files": round(avg_java_files, 2),
                "avg_of_num_warnings": round(avg_warnings, 2)
            },
            "stat_of_warnings": self.warning_counts
        }

        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary_data, f, indent=2)
