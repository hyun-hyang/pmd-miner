# app/pmd_runner.py

import os
import subprocess
import json
from lxml import etree


def run_pmd(repo_path: str, ruleset: str) -> tuple:
    """
    해당 repository (repo_path)에 대해 PMD를 실행하여 정적 분석 경고를 수집하고,
    repository 내의 Java 파일 수와 함께 결과를 반환한다.

    Args:
        repo_path (str): 분석할 Git 저장소의 로컬 경로.
        ruleset (str): PMD 룰셋 XML 파일 경로.

    Returns:
        tuple: (warnings_dict, java_file_count)
            warnings_dict: PMD 결과를 파싱한 Python dictionary 형태.
            java_file_count: 분석 대상인 Java 파일의 총 개수.
    """
    # Java 파일 개수 세기
    java_file_count = 0
    for root, dirs, files in os.walk(repo_path):
        for file in files:
            if file.endswith(".java"):
                java_file_count += 1

    # PMD 명령어 구성
    command = [
        "pmd",
        "-d", repo_path,
        "-R", ruleset,
        "-f", "xml"
    ]

    try:
        # PMD 실행 (stdout, stderr를 캡처)
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        xml_output = result.stdout
    except subprocess.CalledProcessError as e:
        print("Error running PMD:", e.stderr)
        xml_output = ""

    warnings_dict = {}

    if xml_output:
        try:
            # XML 문자열을 파싱
            root_elem = etree.fromstring(xml_output.encode("utf-8"))
            # 결과 dictionary 초기화: 각 파일의 경고 정보를 담는다.
            warnings_dict["files"] = []
            for file_elem in root_elem.findall("file"):
                file_info = {
                    "name": file_elem.get("name"),
                    "violations": []
                }
                for violation in file_elem.findall("violation"):
                    rule = violation.get("rule")
                    message = violation.text.strip() if violation.text else ""
                    file_info["violations"].append({"rule": rule, "message": message})
                warnings_dict["files"].append(file_info)
        except Exception as e:
            print("Error parsing XML output:", e)
            warnings_dict["error"] = str(e)
    else:
        warnings_dict["error"] = "No PMD output captured."

    return warnings_dict, java_file_count


def parse_pmd_output(warnings_dict: dict) -> str:
    """
    PMD 결과 dictionary를 JSON 문자열로 변환한다.

    Args:
        warnings_dict (dict): PMD 결과 dictionary.

    Returns:
        str: JSON 형식의 문자열.
    """
    return json.dumps(warnings_dict, indent=2)
