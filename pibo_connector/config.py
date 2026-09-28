"""실행 설정과 파일 경로. exe(PyInstaller) 로 묶였을 때와 소스 실행을 둘 다 맞춘다."""

import os
import sys
from pathlib import Path

# 로봇 쪽 고정값 — 전부 openpibo-os.pibo 코드에서 확인한 값이다.
IDE_PORT = 80        # ide/run_ide.py  (socket.io 서버)
# 2024년 판 OS(240110v4 ~ 240701v1)는 IDE 가 Node.js 다 — ide/main.js 를 인자 없이
# 띄우는데, main.js 의 포트 결정 줄이 process.argc(Node 에 없는 속성) 를 보는 탓에
# 늘 50000 이다. socket.io 이벤트 이름과 형태는 신형과 같아 포트만 맞추면 그대로 된다.
# (포트 50000 자체는 220921v2 까지 거슬러 올라가도 같다. 막는 건 아래 '기준' 참고.)
IDE_PORT_LEGACY = 50000
SYS_PORT = 8080      # system/booting.py
TRIG_PORT = 50055    # 동시 시작 트리거용 UDP 포트 (커넥터가 직접 쏜다)

# executeb 에는 is_protect 검사가 없다 (ide/run_ide.py 의 execute 와 비교).
# codepath 는 하드코딩하고 UI 에 절대 노출하지 않는다.
CODEPATH = "/home/pi/code/_fleet.py"

SYNC_MARK = "# --- GO ---"

# IDE 의 작업 폴더 (ide/run_ide.py 의 PATH). [찾아보기] 의 시작점이고,
# 상대 경로로 파일을 실행하면 여기 기준이다.
ROBOT_HOME = "/home/pi/code"

# 기본 서버 설정
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8900

# 목록·설정을 둘 곳을 밖에서 정할 때 쓰는 환경변수.
# 풀어서 쓰는 묶음(build/make_portable.py)의 시작하기.bat 이 이걸 묶음 폴더 옆의
# data\ 로 지정한다. 그러면 다음 버전으로 python\ 과 app\ 만 덮어써도
# 찾아둔 로봇 목록이 남는다.
DATA_ENV = "PIBO_CONNECT_DATA"


def frozen() -> bool:
    """PyInstaller 로 묶인 실행 파일인가."""
    return getattr(sys, "frozen", False)


def resource_dir() -> Path:
    """정적 파일(static/) 이 들어있는 디렉토리."""
    if frozen():
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent


def static_dir() -> Path:
    return resource_dir() / "static"


def examples_dir() -> Path:
    """화면의 [예제] 메뉴가 읽는 곳. 실행 파일에는 spec 의 datas 로 같이 묶인다."""
    if frozen():
        return resource_dir() / "examples"
    return Path(__file__).resolve().parent.parent / "examples"


def _writable(base: Path) -> bool:
    """그 폴더를 만들 수 있고 실제로 쓸 수 있는지 본다."""
    try:
        base.mkdir(parents=True, exist_ok=True)
        probe = base / ".write_test"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except Exception:
        return False


def data_dir() -> Path:
    """목록·설정을 저장할 곳.

    1. 환경변수 PIBO_CONNECT_DATA 가 있으면 그곳 (풀어서 쓰는 묶음이 쓴다)
    2. exe 는 임시 폴더에 풀리므로 실행 파일 옆
    3. 소스 실행은 리포 루트
    쓰기가 막힌 경로면(예: Program Files) 사용자 홈으로 물러난다.
    """
    want = os.environ.get(DATA_ENV, "").strip()
    if want:
        base = Path(want).expanduser()
        if _writable(base):
            return base
        # 지정한 곳이 안 되면 잠자코 홈으로 간다. 목록 때문에 앱이 안 뜨면 안 된다.
    elif frozen():
        base = Path(sys.executable).resolve().parent
        if _writable(base):
            return base
    else:
        base = Path(__file__).resolve().parent.parent
        if _writable(base):
            return base

    home = Path(os.path.expanduser("~"))
    new, old = home / ".pibo-connect", home / ".pibo-connector"
    # 이름을 바꾸기 전에 쓰던 폴더가 있으면 그대로 쓴다. 로봇 목록을 잃지 않게.
    if not new.exists() and old.is_dir():
        return old
    new.mkdir(parents=True, exist_ok=True)
    return new


def fleet_path() -> Path:
    return data_dir() / "fleet.json"


def rules_path() -> Path:
    return data_dir() / "rules.json"
