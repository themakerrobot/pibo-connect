"""풀어서 쓰는 묶음(zip) 이 실제로 켜지는지 본다. 윈도우에서만 뜻이 있다.

    python -m tests.portable_smoke dist/pibo-connect-windows-portable.zip

선생님이 하는 그대로 한다 — zip 을 임시 폴더에 풀고, 그 폴더의 런처를 누른다.
빌드 폴더에 남아 있던 것에 기대고 있으면 여기서 걸린다.

보는 것
  1. 런처와 python.exe 에 PSF 서명이 남아 있나. 이 묶음의 존재 이유다 —
     스마트 앱 컨트롤은 서명 없는 프로그램도, 출처 불명 .bat 도 막는다.
     그래서 켜는 버튼이 '이름만 바꾼 서명된 python.exe' 여야 한다
  2. 묶음 안에 스크립트 켜는 버튼이 남아 있지 않나 (루트에 .bat 금지)
  3. 런처에 -m pibo_connector 를 줘서 뜨나 (._pth 와 의존성)
  4. 런처를 그냥 눌렀을 때 뜨나 (app/sitecustomize.py 자동 시작)
     + 목록을 묶음 옆 data\ 에 두나
"""

import argparse
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "build"))

from make_portable import (BUNDLE, LAUNCH_CHECK, LAUNCH_RUN, LAUNCHERS,  # noqa: E402
                           PY_TAG, blob_names_signer, pe_cert_blob,
                           verify_signature)
from tests._launch import Server, utf8_console                          # noqa: E402

PAGES = (("/", "파이보 커넥터"), ("/static/app.js", ""),
         ("/static/maker-ui.css", "--paper"),
         ("/static/fonts/pretendard.css", "Pretendard"),
         ("/static/img/pibo-logo.png", ""), ("/favicon.ico", ""))


def serve(cmd, cwd: Path, log: Path, timeout: float, label: str, env=None) -> tuple:
    """띄워서 /api/info 와 화면을 받아 본다. (info, 실패목록)"""
    fails = []
    with Server(cmd, log, cwd=str(cwd), env=env) as srv:
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
    for need in (*LAUNCHERS, "먼저-읽어보세요.txt", "python.exe", "python311.dll",
                 f"python{PY_TAG}._pth", "app/sitecustomize.py",
                 "app/pibo_connector/static/app.js", "app/examples"):
        if not (root / need).exists():
            print(f"!! 묶음에 없다: {need}")
            fails.append(need)
    if fails:
        print("실패: " + ", ".join(fails))
        return 1
    print("ok  런처·런타임·앱이 다 있다")

    # 켜는 버튼이 스크립트면 SAC 가 막는다. 루트에 .bat 이 있으면 안 된다.
    stray = sorted(p.name for p in root.glob("*.bat"))
    if stray:
        print(f"!! 루트에 .bat 이 있다 — SAC 가 막는다: {stray}")
        fails.append("루트 .bat")
    else:
        print("ok  루트에 스크립트 켜는 버튼이 없다")

    # ._pth 에 줄 끝 \r 이 남으면 sys.path 에 'app\r' 이 들어가 조용히 깨진다.
    pth = (root / f"python{PY_TAG}._pth").read_bytes()
    if b"\r" in pth:
        print("!! ._pth 에 CR 이 있다")
        fails.append("._pth/CR")
    elif b"import site" not in pth:
        print("!! ._pth 에 import site 가 없다 — sitecustomize 가 안 불린다")
        fails.append("._pth/site")
    else:
        print("ok  ._pth 가 LF 이고 import site 가 있다")

    print("\n서명 확인")
    for name in ("python.exe", *LAUNCHERS):
        try:
            print(f"  · {name}")
            verify_signature(root / name)
        except SystemExit as ex:
            print(f"!! {ex}")
            fails.append(f"서명/{name}")

    if sys.platform != "win32":
        print("\n(윈도우가 아니라 기동 시험은 생략한다 — 묶음 안의 python.exe 는 윈도우용이다)")
        if fails:
            print("실패: " + ", ".join(fails))
            return 1
        print("묶음 구조 정상")
        return 0

    log = Path(tempfile.gettempdir())
    # 실행 파일은 절대경로로 준다. 윈도우의 CreateProcess 는 상대 실행 파일을
    # Popen 의 cwd= 가 아니라 이 프로세스의 현재 폴더 기준으로 찾는다.
    runner = root / LAUNCH_RUN

    # 1) 인자를 주는 길. ._pth 와 의존성이 맞는지 본다 (sitecustomize 는 빠진다).
    print(f"\n1) {LAUNCH_RUN} -m pibo_connector")
    _, f1 = serve([str(runner), "-m", "pibo_connector", "--no-browser"],
                  root, log / "portable_m.log", args.timeout, "-m 으로")
    fails += f1

    # 2) 선생님이 하는 길 — 인자 없이 두 번 누르기. sitecustomize 가 띄운다.
    #    브라우저는 열지 않게 환경변수로 말한다 (.bat 이 없어졌으니 이 길밖에 없다).
    print(f"\n2) {LAUNCH_RUN} (두 번 누르기)")
    env = dict(os.environ, PIBO_CONNECT_NO_BROWSER="1")
    env.pop("PIBO_CONNECT_DATA", None)
    info, f2 = serve([str(runner)], root, log / "portable_click.log",
                     args.timeout, "두 번 누르기", env=env)
    fails += f2
    if info:
        # 목록은 묶음 폴더 옆 data\ 에 남아야 한다. 다음 버전으로 바꿔도 안 날아가게.
        got, want = Path(info.get("data_dir", "")), root / "data"
        if got.resolve() == want.resolve():
            print(f"ok  목록 자리 = {got}")
        else:
            print(f"!! 목록 자리가 묶음 옆 data\\ 가 아니다: {got} (기대 {want})")
            fails.append("data_dir")

    if fails:
        print("\n실패: " + ", ".join(fails))
        return 1
    print(f"\n묶음 정상 — [{LAUNCH_RUN}] 두 번 누르면 켜진다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
