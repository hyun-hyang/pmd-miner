import os
import subprocess
import json
import tempfile
from lxml import etree


def run_pmd(repo_path: str, ruleset: str, verbose: bool = False) -> tuple:
    """
    해당 repository (repo_path)에 대해 PMD를 실행하여 정적 분석 경고를 수집하고,
    repository 내의 Java 파일 수와 함께 결과를 반환한다.

    Args:
        repo_path (str): 분석할 Git 저장소의 로컬 경로.
        ruleset (str): PMD 룰셋 XML 파일 경로.
        verbose (bool): verbose 모드(-debug) 활성화 여부.

    Returns:
        tuple: (warnings_dict, java_file_count)
    """
    # 1. Java 파일 개수 세기
    java_file_count = 0
    for root, dirs, files in os.walk(repo_path):
        for file in files:
            if file.endswith(".java"):
                java_file_count += 1

    # PMD 실행 커맨드를 실행파일 이름 (Docker 환경에서는 PATH에 추가되어 있으므로 "pmd"로 사용)
    pmd_exec = "pmd"

    # 3. ruleset 경로 처리
    ruleset_path = os.path.abspath(ruleset)
    if not os.path.exists(ruleset_path):
        fallback_rule = os.path.abspath("app/quickstart.xml")
        print(f"Warning: Provided ruleset '{ruleset_path}' not found. Using built-in default rule reference: {fallback_rule}")
        rule_argument = fallback_rule
    else:
        rule_argument = ruleset_path

    # 4. PMD 결과를 저장할 임시 파일 생성 (-r 옵션 사용)
    temp_report = tempfile.NamedTemporaryFile(delete=False, suffix=".xml")
    temp_report_path = temp_report.name
    temp_report.close()

    # 5. PMD 명령어 구성
    # 이미 "-D" 옵션으로 필요한 JAVA 옵션들을 전달하고 있으므로, verbose 옵션은 추가 시 중복되지 않도록 합니다.
    command = [
        pmd_exec,
        "check",
        "-d", repo_path,
        "-R", rule_argument,
        "-f", "xml",
        "-r", temp_report_path,
        "-D", "pmd.website.baseurl=https://pmd.github.io",
        "-D", "pmd.incrementalAnalysis=false"
    ]

    if verbose and "-debug" not in command:
        command.append("-debug")

    # # 만약 verbose 모드가 활성화된 경우, 이미 리스트에 "-debug"가 없는지 확인 후 추가
    # if verbose and "-debug" not in command:
    #     command.append("-debug")
    #
    # # 디버깅을 위해 실행할 커맨드를 로그로 출력할 수 있습니다.
    # if verbose:
    #     print("Executing PMD command: ", " ".join(command))

    # 6. JAVA_OPTS 환경변수 제거 (증분 분석 옵션 관련 문제 방지를 위해)
    env = os.environ.copy()
    if "JAVA_OPTS" in env:
        del env["JAVA_OPTS"]

    # 7. PMD 실행 (non-zero returncode인 경우 에러 메시지 출력)
    try:
        result = subprocess.run(
            command,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False
        )
        if result.returncode != 0:
            print("Error running PMD:", result.stderr.strip())
    except Exception as e:
        print("Exception while running PMD:", str(e))

    # 8. PMD 결과 XML 파일 읽기
    xml_output = ""
    if os.path.exists(temp_report_path):
        try:
            with open(temp_report_path, "r", encoding="utf-8") as f:
                xml_output = f.read()
        except Exception as e:
            print("Error reading PMD report file:", e)
        finally:
            try:
                os.remove(temp_report_path)
            except Exception as e:
                print("Error removing temporary report file:", e)

    # 9. XML 파싱: 결과 데이터를 dictionary로 변환 (파싱 예외 발생 시 메시지 출력)
    warnings_dict = {}
    if xml_output:
        try:
            root_elem = etree.fromstring(xml_output.encode("utf-8"))
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
        warnings_dict["files"] = []

    return warnings_dict, java_file_count


def parse_pmd_output(warnings_dict: dict) -> str:
    return json.dumps(warnings_dict, indent=2)
