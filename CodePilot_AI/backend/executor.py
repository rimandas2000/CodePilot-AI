import re
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


LANGUAGE_CONFIG = {
    "Python": {"extension": ".py", "command": "python"},
    "C": {"extension": ".c", "compiler": "gcc"},
    "C++": {"extension": ".cpp", "compiler": "g++"},
    "Java": {"extension": ".java", "compiler": "javac"},
    "JavaScript": {"extension": ".js", "command": "node"},
}


def _find_command(name):
    return shutil.which(name)


def _run_process(command, cwd, stdin_text="", timeout=5):
    try:
        result = subprocess.run(
            command,
            input=stdin_text,
            text=True,
            capture_output=True,
            cwd=cwd,
            timeout=timeout,
            shell=False,
        )
        return result.returncode, result.stdout, result.stderr, None
    except subprocess.TimeoutExpired:
        return -1, "", "", f"Execution timed out after {timeout} seconds."
    except Exception as exc:
        return -1, "", "", str(exc)


def run_code(language, code, stdin_text="", timeout=5):
    """
    Compile/run code locally.

    Supported: Python, C, C++, Java, JavaScript.
    Returns a dict with status, stdout, stderr and a human-readable message.

    IMPORTANT: This executes arbitrary local code. Use only with trusted code.
    """
    language = language.strip()
    if language not in LANGUAGE_CONFIG:
        return {
            "success": False,
            "status": "Unsupported language",
            "stdout": "",
            "stderr": f"{language} is not supported by the local compiler.",
        }

    if not code.strip():
        return {
            "success": False,
            "status": "No code",
            "stdout": "",
            "stderr": "Please enter some code first.",
        }

    cfg = LANGUAGE_CONFIG[language]

    with tempfile.TemporaryDirectory(prefix="ai_tutor_") as tmp:
        tmp_path = Path(tmp)

        if language == "Java":
            # Keep the public class name predictable for simple snippets.
            code = re.sub(
                r"\bpublic\s+class\s+[A-Za-z_]\w*",
                "public class Main",
                code,
                count=1,
            )
            source = tmp_path / "Main.java"
        else:
            source = tmp_path / f"main{cfg['extension']}"

        source.write_text(code, encoding="utf-8")

        if language in ("Python", "JavaScript"):
            executable = _find_command(cfg["command"])
            if not executable:
                return {
                    "success": False,
                    "status": "Runtime not found",
                    "stdout": "",
                    "stderr": f"'{cfg['command']}' was not found on this computer.",
                }

            returncode, stdout, stderr, error = _run_process(
                [executable, str(source)],
                tmp_path,
                stdin_text,
                timeout,
            )

        elif language in ("C", "C++"):
            compiler = _find_command(cfg["compiler"])
            if not compiler:
                return {
                    "success": False,
                    "status": "Compiler not found",
                    "stdout": "",
                    "stderr": (
                        f"'{cfg['compiler']}' was not found. "
                        "Install GCC/MinGW and make sure it is on PATH."
                    ),
                }

            executable = tmp_path / ("program.exe" if os.name == "nt" else "program")
            compile_result = _run_process(
                [compiler, str(source), "-O2", "-o", str(executable)],
                tmp_path,
                timeout=15,
            )
            returncode, stdout, stderr, error = compile_result

            if error:
                return {
                    "success": False,
                    "status": "Compilation error",
                    "stdout": stdout,
                    "stderr": error,
                }

            if returncode != 0:
                return {
                    "success": False,
                    "status": "Compilation error",
                    "stdout": stdout,
                    "stderr": stderr,
                }

            returncode, stdout, stderr, error = _run_process(
                [str(executable)],
                tmp_path,
                stdin_text,
                timeout,
            )

        elif language == "Java":
            javac = _find_command("javac")
            java = _find_command("java")
            if not javac or not java:
                return {
                    "success": False,
                    "status": "Java not found",
                    "stdout": "",
                    "stderr": "Both 'javac' and 'java' are required and must be on PATH.",
                }

            returncode, stdout, stderr, error = _run_process(
                [javac, str(source)],
                tmp_path,
                timeout=15,
            )

            if error:
                return {
                    "success": False,
                    "status": "Compilation error",
                    "stdout": stdout,
                    "stderr": error,
                }

            if returncode != 0:
                return {
                    "success": False,
                    "status": "Compilation error",
                    "stdout": stdout,
                    "stderr": stderr,
                }

            returncode, stdout, stderr, error = _run_process(
                [java, "-cp", str(tmp_path), "Main"],
                tmp_path,
                stdin_text,
                timeout,
            )

        if error:
            return {
                "success": False,
                "status": "Runtime error",
                "stdout": stdout,
                "stderr": error,
            }

        return {
            "success": returncode == 0,
            "status": "Success" if returncode == 0 else "Runtime error",
            "stdout": stdout,
            "stderr": stderr,
            "returncode": returncode,
        }
