"""풀어서 쓰는 묶음(zip) 이 실제로 켜지는지 본다. 윈도우에서만 뜻이 있다.

    python -m tests.portable_smoke dist/pibo-connect-windows-portable.zip

선생님이 하는 그대로 한다 — zip 을 임시 폴더에 풀고, 그 폴더에서 켠다.
빌드 폴더에 남아 있던 것에 기대고 있으면 여기서 걸린다.

세 가지를 본다.
  1. python.exe 에 PSF 서명이 남아 있나 (이 묶음의 존재 이유다)
  2. python\python.exe -m pibo_connector 가 뜨나 (._pth 와 의존성)
  3. 시작하기.bat 이 뜨나 + 목록을 묶음 옆 data\ 에 두나 (런처)
"""

import argparse
import json
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "build"))

from make_portable import BUNDLE, PY_TAG, verify_signature   # noqa: E402
from tests._launch import Server, utf8_console               # noqa: E402

PAGES = (("/", "파이보 커넥터"), ("/static/app.js", ""),
         ("/static/maker-ui.css", "--paper"),
         ("/static/fonts/pretendard.css", "Pretendard"),
         ("/static/img/pibo-logo.png", ""), ("/favicon.ico", ""))


def serve(cmd, cwd: Path, log: Path, timeout: float, label: str) -> tuple:
    """띄워서 /api/info 와 화면을 받아 본다. (info, 실패목록)"""
    fails = []
    with Server(cmd, log, cwd=str(cwd)) as srv:
        info, died = srv.wait_ready(timeout)
        if info is None:
            print(f"!! {label}: " + (f"그냥 끝났다 (exit {srv.proc.returncode})" if died
                                     else f"{timeout:.0f}초 안에 뜨지 않았다"))
            fails.append(label)
        else:
            print(f"ok  {label} — {srv.base}")
            print("    " + json.dumps(info, ensure_ascii=False))
            if info.get("frozen"):
                print("!! frozen 이 True 다 — 묶음은 소스 실행이어야 한다")
                fails.append(f"{label}/frozen")
            for path, want in PAGES:
                try:
                    st, body = srv.get(path, 8)
                    ok = st == 200 and (not want or want in body)
                except Exception as ex:
                    st, ok = f"예외 {ex}", False
                print(("ok  " if ok else "!! ") + f"  {path}" + ("" if ok else f" (status {st})"))
                if not ok:
                    fails.append(f"{label}{path}")
        out = srv.log().strip()
    if out or fails:
        print(f"─── {label} 출력 " + "─" * 34)
        print(out or "(출력 없음)")
        print("─" * 52)
    return info, fails


def main() -> int:
    utf8_console(sys.stdout, sys.stderr)
    ap = argparse.ArgumentParser()
    ap.add_argument("zip")
    ap.add_argument("--timeout", type=float, default=120.0)
    args = ap.parse_args()

    src = Path(args.zip).resolve()
    if not src.exists():
        print(f"!! 묶음이 없다: {src}")
        return 1
    print(f"zip: {src}  ({src.stat().st_size / 1e6:.1f} MB)")

    tmp = Path(tempfile.mkdtemp(prefix="pibo_portable_"))
    with zipfile.ZipFile(src) as z:
        names = z.namelist()
        z.extractall(tmp)
    root = tmp / BUNDLE
    print(f"풀린 곳: {root}  ({len(names)}개 파일)")

    fails = []
    for need in ("시작하기.bat", "로봇 확인하기.bat", "먼저-읽어보세요.txt",
                 "python/python.exe", f"python/python{PY_TAG}._pth",
                 "app/pibo_connector/static/app.js", "app/examples"):
        if not (root / need).exists():
            print(f"!! 묶음에 없다: {need}")
            fails.append(need)
    if fails:
        print("실패: " + ", ".join(fails))
        return 1

    # .bat 에 한글이 들어가면 한글 안 쓰는 윈도우에서 깨진다. ASCII 만 허용한다.
    for bat in root.glob("*.bat"):
        raw = bat.read_bytes()
        if raw[:3] == b"\xef\xbb\xbf":
            print(f"!! {bat.name} 에 BOM 이 있다 — cmd.exe 가 첫 줄을 못 읽는다")
            fails.append(f"{bat.name}/BOM")
        try:
            raw.decode("ascii")
            print(f"ok  {bat.name} 은 ASCII 다")
        except UnicodeDecodeError as ex:
            print(f"!! {bat.name} 에 ASCII 아닌 글자가 있다: {ex}")
            fails.append(f"{bat.name}/ascii")

    print("\n서명 확인 (풀린 묶음의 python.exe)")
    try:
        verify_signature(root / "python" / "python.exe")
    except SystemExit as ex:
        print(f"!! {ex}")
        fails.append("서명")

    if sys.platform != "win32":
        print("\n(윈도우가 아니라 기동 시험은 생략한다 — 묶음 안의 python.exe 는 윈도우용이다)")
        if fails:
            print("실패: " + ", ".join(fails))
            return 1
        print("묶음 구조 정상")
        return 0

    log = Path(tempfile.gettempdir())
    # 실행 파일은 **절대경로**로 준다. 윈도우의 CreateProcess 는 상대 실행 파일을
    # Popen 의 cwd= 가 아니라 이 프로세스의 현재 폴더 기준으로 찾는다 — 상대경로로
    # 주면 WinError 2 다. 묶음 안의 파이썬을 쓰는지는 경로 자체가 보증한다.
    py = root / "python" / "python.exe"
    print(f"\n1) {py} -m pibo_connector")
    _, f1 = serve([str(py), "-m", "pibo_connector", "--no-browser"],
                  root, log / "portable_py.log", args.timeout, "python.exe")
    fails += f1

    print("\n2) 시작하기.bat")
    # .bat 은 스스로 cd /d "%~dp0" 하므로 cwd 와 무관하지만, 찾는 쪽도 절대경로로.
    info, f2 = serve(["cmd", "/c", str(root / "시작하기.bat"), "--no-browser"],
                     root, log / "portable_bat.log", args.timeout, "시작하기.bat")
    fails += f2
    if info:
        # 목록은 묶음 폴더 옆 data\ 에 남아야 한다. 다음 버전으로 바꿔도 안 날아가게.
        got = Path(info.get("data_dir", ""))
        want = root / "data"
        if got.resolve() == want.resolve():
            print(f"ok  목록 자리 = {got}")
        else:
            print(f"!! 목록 자리가 묶음 옆 data\\ 가 아니다: {got} (기대 {want})")
            fails.append("data_dir")

    if fails:
        print("\n실패: " + ", ".join(fails))
        return 1
    print("\n묶음 정상 — 이 zip 은 파이썬 없는 PC 에서 켜진다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
