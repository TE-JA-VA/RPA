"""조각 방식의 시작 스크립트 - 배포본에서는 app\\_start.py (설계 2026-11-11 조각 빌드 4절).

시작 파일(tools/launcher.c 로 만든 ERPia_RPA.exe 등)이 내장 Python 으로 이 파일을 실행한다. 스크립트로 돌기 때문에
sys.path[0] 이 app\\ 이다 - 프로그램 폴더의 rpa_status.py 보다 app\\ 의 조각(.pyd)이 먼저 잡힌다.
"""
import os
import sys

START = {"erpia_rpa.exe": "run_routine", "prepare_rpa.exe": "web_runner", "prepare_observer.exe": "rpa_observer"}
MISSING = "오토파일럿을 시작하지 못했습니다. 다시 설치하여 주십시오. ({})"


def tell(text):
    """콘솔·부른 쪽이 있으면 stderr 로, 없으면 (창 프로그램) 알림 창. --check 는 창을 띄우지 않는다."""
    if sys.stderr is not None:
        try:
            sys.stderr.buffer.write((text + "\n").encode("utf-8"))
            sys.stderr.flush()
            return
        except Exception:
            pass
    if "--check" not in sys.argv[1:]:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, "오토파일럿", 0x10)


def main():
    os.environ.pop("PYTHONHOME", None)          # 시작 파일이 내장 Python 을 찾으라고 준 값 - 자식 프로세스에 물려주지 않는다
    exe = sys.executable
    sys.argv[0] = exe                           # 옵저버의 관리자 재실행 등이 exe 자리로 쓴다
    root = os.path.dirname(exe)
    lib = os.path.join(root, "lib")
    name = START.get(os.path.basename(exe).lower())
    if name is None or not os.path.isdir(lib):
        tell(MISSING.format(exe if name is None else lib))
        return 2
    import importlib
    import site
    site.addsitedir(lib)                        # pywin32 의 .pth 까지
    return importlib.import_module(name).run_main()


if __name__ == "__main__":
    sys.exit(main())
