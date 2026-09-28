"""풀어서 쓰는 묶음 전용 자동 시작. 묶을 때 app/ 으로 들어간다.

왜 이게 있나
------------
스마트 앱 컨트롤(SAC)은 서명 없는 프로그램만 막는 게 아니라 **출처 불명
스크립트(.bat 포함)도 막는다.** 실기에서 시작하기.bat 이 그대로 걸렸다.
그래서 켜는 버튼을 스크립트에서 없애고, **이름만 바꾼 python.exe 복사본**으로
바꿨다. Authenticode 서명은 파일 내용에 붙고 파일 이름과 무관하므로, 복사해
이름을 바꿔도 Python Software Foundation 서명은 그대로 유효하다.

그 exe 를 두 번 누르면 파이썬이 대화형으로 뜬다. site 초기화 때 이 파일이
자동으로 import 되므로, 여기서 커넥터를 띄우고 프로세스를 끝낸다.

언제 끼어드나
-------------
인자 없이 대화형으로 들어올 때만이다 (두 번 누르면 sys.argv == ['']).
`python.exe -m pibo_connector` 처럼 인자를 주면 건드리지 않는다 — CI 와
개발자용 경로를 막으면 안 되고, 여기서 다시 main() 을 부르면 겹친다.
PIBO_CONNECT_NO_AUTOSTART=1 이면 언제나 빠진다.

무엇을 하나
-----------
서버를 띄운다. 로봇 한 대를 짚어 보려면(--check) 검은 창에서
    pibo-connect.exe -m pibo_connector --check 192.168.0.51
처럼 준다 — 인자를 주면 여기는 빠지고 평소 경로로 간다.
"""

import os
import sys

NO_AUTOSTART = "PIBO_CONNECT_NO_AUTOSTART"
NO_BROWSER = "PIBO_CONNECT_NO_BROWSER"


def _double_clicked() -> bool:
    """두 번 눌러 들어온 대화형 진입인가."""
    if os.environ.get(NO_AUTOSTART):
        return False
    return len(sys.argv) == 1 and not sys.argv[0]


def _exe_dir():
    from pathlib import Path
    return Path(sys.executable).resolve().parent


def _argv() -> list:
    """넘길 인자. 두 번 눌러 켜는 길이므로 기본은 없음이다."""
    args = []
    if os.environ.get(NO_BROWSER):
        args.append("--no-browser")
    return args


def _pause(msg: str) -> None:
    """창이 그냥 사라지면 선생님이 아무것도 못 읽는다."""
    print("\n" + msg)
    try:
        input()
    except Exception:
        pass


def _run() -> int:
    # 로봇 목록은 묶음 폴더 옆 data\ 에. 다음 버전으로 바꿔도 목록이 남게.
    os.environ.setdefault("PIBO_CONNECT_DATA", str(_exe_dir() / "data"))
    from pibo_connector.__main__ import main
    return main(_argv())


if _double_clicked():
    code = 0
    try:
        code = _run() or 0
    except KeyboardInterrupt:
        pass          # Ctrl+C 로 끝낸 것. 정상이다
    except SystemExit as ex:
        code = int(getattr(ex, "code", 0) or 0)
    except BaseException:
        import traceback
        traceback.print_exc()
        code = 1
        _pause("문제가 생겼어요. 위에 적힌 글을 그대로 알려주세요. (엔터를 누르면 닫혀요)")
    else:
        if code:
            _pause("엔터를 누르면 닫혀요.")
    # site 초기화 중이라 그냥 돌아가면 대화형 파이썬이 뜬다. 여기서 끝낸다.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass
    os._exit(code)
