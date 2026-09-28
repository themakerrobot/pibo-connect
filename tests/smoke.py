"""기기 없이 할 수 있는 검증. CI 와 손으로 같은 걸 돌린다.

    python -m tests.smoke

보는 것:
  1) system.sh CSV 파싱 — 특히 인덱스 9(WiFi 비밀번호)가 어디에도 안 남는지
  2) 기종 판별 (OS_VERSION 기준)
  3) 목록 저장소가 psk 계열 필드를 통째로 거르는지
  4) AP SSID 패턴
  5) 동시 실행 래퍼가 문법에 맞는 파이썬인지
  6) 서버가 실제로 떠서 /api/info 를 주는지
"""

import ast
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pibo_connector import config, detect, robot, runner, scan   # noqa: E402
from pibo_connector.store import Fleet                           # noqa: E402
from tests._launch import Server, utf8_console                   # noqa: E402

FAIL = []


def check(name, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def test_parse_system():
    print("system.sh CSV 파싱")
    # system/system.sh 의 echo 순서 그대로. 인덱스 9 가 PSK 다.
    row = ["100000001cd488e95", "piBo_260915v1-ph", "12345.6", "48.3'C",
           "3900000", "2100000", "192.168.0.51", "", "classroom-5g",
           "SuperSecret!234", "", "wpa-psk"]
    d = robot.parse_system(row)
    check("SN 은 시리얼 뒤 8자리", d["sn"] == "cd488e95", d["sn"])
    check("OS_VERSION", d["os"] == "piBo_260915v1-ph")
    check("IP 는 wlan0 우선", d["ip"] == "192.168.0.51")
    check("SSID", d["ssid"] == "classroom-5g")
    blob = json.dumps(d, ensure_ascii=False)
    check("PSK 가 파싱 결과에 없다", "SuperSecret" not in blob, blob)

    d2 = robot.parse_system(["100000001cd488e95", "piBo_x"])
    check("짧은 배열도 안 터진다", d2["sn"] == "cd488e95" and d2["ip"] == "")

    # 구형 240701v1 은 9칸이고 순서가 다르다: … WLAN0, SSID0, ETH1 (PSK 없음)
    old = ["100000001cd488e95", "piBo_240701v1", "12345.6", "48.3'C",
           "3900000", "2100000", "192.168.0.51", "classroom-5g", ""]
    d3 = robot.parse_system(old)
    check("구형 9칸: IP 가 wlan0", d3["ip"] == "192.168.0.51", d3)
    check("구형 9칸: SSID 가 [7]", d3["ssid"] == "classroom-5g", d3)
    old_eth = old[:6] + ["", "classroom-5g", "10.0.0.7"]
    check("구형 9칸: wlan0 없으면 eth1 을 IP 로",
          robot.parse_system(old_eth)["ip"] == "10.0.0.7")


def test_detect():
    print("기종 판별 (OS_VERSION)")
    k, c, _ = detect.classify("piBo_260915v1-ph")
    check("piBo_… → pibo", (k, c) == (detect.PIBO, "high"), f"{k}/{c}")
    k, c, _ = detect.classify("piBrain_260915v1")
    check("piBrain_… → pibrain", (k, c) == (detect.PIBRAIN, "high"), f"{k}/{c}")
    k, _, _ = detect.classify("pibrain-pibo-mix")
    check("pibrain 이 pibo 보다 먼저 걸린다", k == detect.PIBRAIN, k)
    k, c, _ = detect.classify("something-else-v1")
    check("모르는 이름은 unknown", k == detect.UNKNOWN, k)
    k, _, _ = detect.classify("", device_reply="#40:12-0-1-0-99:!")
    check("OS 없으면 device 패킷으로 pibo 추정", k == detect.PIBO, k)
    k, _, _ = detect.classify("", device_reply="Error: no device")
    check("device 에러면 pibrain 쪽", k == detect.PIBRAIN, k)


def test_store():
    print("목록 저장소")
    with tempfile.TemporaryDirectory() as td:
        f = Fleet(path=Path(td) / "fleet.json")
        f.upsert({"sn": "CD488E95", "os": "piBo_1", "ip": "192.168.0.51",
                  "psk": "SuperSecret!234", "wifi_password": "nope",
                  "kind": "pibo"})
        f.rename("cd488e95", "1번")
        f.save()
        raw = (Path(td) / "fleet.json").read_text(encoding="utf-8")
        check("SN 은 소문자 키", "cd488e95" in raw)
        check("PSK 가 파일에 없다", "SuperSecret" not in raw and "nope" not in raw, raw)
        check("이름이 남는다", '"1번"' in raw)

        # 다시 스캔해도 사람이 붙인 이름은 보존된다
        f.upsert({"sn": "cd488e95", "ip": "192.168.0.77", "os": "piBo_2"})
        check("재스캔 후에도 이름 유지", f.get("cd488e95")["name"] == "1번")
        check("IP 는 갱신", f.get("cd488e95")["ip"] == "192.168.0.77")

        f.set_roster(["cd488e95", "DEADBEEF", "cd488e95"])
        st = f.roster_status()
        check("점호: 중복 제거", st["expected"] == 2, st)
        check("점호: 접속 1대", st["present"] == ["cd488e95"], st)
        check("점호: 미확인 1대", st["missing"] == ["deadbeef"], st)


def test_ap_rx():
    print("AP SSID 패턴")
    check("pibo-<SN> 만 잡는다", bool(scan.AP_RX.match("pibo-cd488e95")))
    check("교실 공유기 SSID 는 안 잡힌다", not scan.AP_RX.match("pibo-classroom"))
    check("길이가 다르면 안 잡힌다", not scan.AP_RX.match("pibo-cd488e9"))


def test_wrap():
    print("동시 실행 래퍼")
    code = "import openpibo\n" + config.SYNC_MARK + "\nprint('go')\n"
    body, main = code.split(config.SYNC_MARK, 1)
    wrapped = runner.WRAP.format(port=config.TRIG_PORT, wait=120.0,
                                 body=body, main=main)
    try:
        ast.parse(wrapped)
        ok = True
    except SyntaxError as ex:
        ok = False
        print(wrapped)
        print(ex)
    check("래퍼가 파이썬 문법에 맞는다", ok)
    check("트리거 포트가 박혀 있다", f"bind(('', {config.TRIG_PORT}))" in wrapped)
    check("[ready] 를 찍는다", "print('[ready]'" in wrapped)

    # 사용자 코드에 중괄호가 있어도 format 이 깨지면 안 된다
    w2 = runner.WRAP.format(port=1, wait=1, body="d = {'a': 1}", main="print(d['a'])")
    try:
        ast.parse(w2)
        ok2 = True
    except SyntaxError:
        ok2 = False
    check("중괄호가 든 코드도 통과", ok2)


def test_launcher():
    """로봇에 있는 파일을 그 자리에서 실행하는 런처. 경로 이스케이프가 핵심이다."""
    print("로봇 파일 런처")
    code, kind = runner.launcher_for("dance.py")
    check("상대 경로는 ROBOT_HOME 기준", "_p = '/home/pi/code/dance.py'" in code, code)
    check("파이썬은 runpy __main__", kind == "python" and "run_name='__main__'" in code)
    try:
        ast.parse(code); ok = True
    except SyntaxError:
        ok = False
    check("런처가 파이썬 문법에 맞는다", ok)

    weird = "/home/pi/code/it's here/a b.py"
    code, _ = runner.launcher_for(weird)
    try:
        ast.parse(code); ok = True
    except SyntaxError:
        ok = False
    check("따옴표·공백 든 경로도 파이썬 런처 통과", ok and repr(weird) in code)

    code, kind = runner.launcher_for("/home/pi/code/it's here/run.sh")
    check("셸은 sh 로", kind == "shell" and "exec sh" in code)
    check("셸 한따옴표 이스케이프", "it'\\''s here" in code, code)
    check("없는 파일은 [missing]", "[missing]" in code)

    code, _ = runner.launcher_for("../code/x.py")
    check("normpath 로 정리", "_p = '/home/pi/code/x.py'" in code, code)

    try:
        runner.launcher_for("   "); ok = False
    except ValueError:
        ok = True
    check("빈 경로는 거부", ok)


def test_release_notes():
    """지금 __version__ 에 해당하는 CHANGELOG 절이 있는가.

    없으면 태그를 찍는 순간 릴리스 워크플로가 멈춘다. 여기서 먼저 잡는다.
    """
    print("릴리스 노트")
    sys.path.insert(0, str(ROOT / "build"))
    import release_notes
    from pibo_connector import __version__ as ver
    sec = release_notes.section_for("v" + ver)
    check(f"CHANGELOG 에 v{ver} 절이 있다", bool(sec),
          f"CHANGELOG.md 맨 위에 '## v{ver} — 날짜' 절을 더할 것")
    if sec:
        body = release_notes.build("v" + ver, "deadbeef")
        check("본문에 바뀐 내용이 들어간다", sec.splitlines()[0] in body)
        check("본문에 받기·실행 안내가 있다", "### 받기" in body and "### 실행하기" in body)
        check("제목", release_notes.title_for("v" + ver) == f"파이보 커넥터 v{ver}")
    check("nightly 는 CHANGELOG 없이도 된다", "시험용" in release_notes.build("nightly", "x"))


def test_spec_paths():
    """spec 이 정적 파일을 푸는 자리와 config.static_dir() 이 보는 자리가 같은가.

    이게 어긋나면 소스 실행은 멀쩡한데 묶은 실행 파일만 StaticFiles 에서
    'Directory does not exist' 로 죽는다. 실제로 한 번 그랬다.
    """
    print("실행 파일 번들 경로")
    spec = (ROOT / "build" / "pibo-connect.spec").read_text(encoding="utf-8")
    # frozen 일 때 static_dir() 은 sys._MEIPASS / 'static' 이다.
    # 그러므로 datas 의 대상도 'static' 이어야 한다.
    check("spec 의 datas 에 (STATIC → 'static')",
          '(str(STATIC), "static")' in spec,
          [l for l in spec.splitlines() if "datas=" in l])
    check("static_dir 이 resource_dir 바로 아래",
          config.static_dir().name == "static"
          and config.static_dir().parent == config.resource_dir())
    check("정적 파일이 실제로 있다",
          (config.static_dir() / "index.html").exists()
          and (config.static_dir() / "app.js").exists())
    check("spec 의 datas 에 examples 도 있다",
          '(str(EXAMPLES), "examples")' in spec)
    check("examples_dir 이 resource_dir 바로 아래 (frozen 기준)",
          config.examples_dir().name == "examples")
    check("예제가 실제로 있다", (config.examples_dir() / "hello.py").exists())


def test_portable():
    """풀어서 쓰는 묶음(build/make_portable.py) 의 자리와 런처가 맞는가.

    묶음은 소스 실행(frozen=False) 과 같은 배치를 쓴다. 그래서 spec 처럼
    따로 맞출 게 없지만, 확인은 해 둔다 — app/ 안의 배치가 틀리면
    풀어 쓴 PC 에서만 static 이 404 다.

    켜는 버튼은 스크립트가 아니어야 한다. 스마트 앱 컨트롤은 서명 없는
    프로그램만이 아니라 출처 불명 .bat 도 막는다 (실기에서 확인했다).
    그래서 버튼은 '이름만 바꾼 서명된 python.exe 복사본' 이고, 두 번 눌렀을 때
    app/sitecustomize.py 가 커넥터를 띄운다.
    """
    print("풀어서 쓰는 묶음")
    sys.path.insert(0, str(ROOT / "build"))
    import make_portable as mp

    pkg = Path(mp.__file__).resolve().parent.parent / "pibo_connector"
    check("static 은 패키지 바로 아래 (pibo_connector/ 를 통째로 넣으면 맞는다)",
          config.static_dir() == pkg / "static", config.static_dir())
    check("examples 는 패키지의 부모 아래 (app/examples 가 맞는다)",
          config.examples_dir() == pkg.parent / "examples", config.examples_dir())

    pth, A, R, L = mp.PTH_LINES, mp.APP_DIR, mp.RUNTIME_DIR, mp.LIB_DIR
    check("._pth 가 표준 라이브러리 zip 을 먼저 본다",
          pth[0] == f"{A}\\{R}\\python{mp.PY_TAG}.zip", pth)
    check("._pth 에 app/runtime 이 있다 (.pyd 가 거기 있다)", f"{A}\\{R}" in pth, pth)
    check("._pth 에 app 이 있다 (pibo_connector·sitecustomize)", A in pth, pth)
    check("._pth 에 app/lib 이 있다", f"{A}\\{L}" in pth, pth)
    # import site 가 없으면 sitecustomize 가 안 불려서 두 번 눌러도 안 켜진다.
    check("._pth 에 import site 가 있다", "import site" in pth, pth)
    # ._pth 는 실행 파일(=루트) 기준이다. .. 로 올라갈 일이 없다.
    check("._pth 에 .. 가 없다", not any(l.startswith("..") for l in pth), pth)
    # 실행 파일 옆에 있어야 하는 것들. 옮기면 "python311.dll 을 찾을 수 없습니다" 다.
    check("루트에 남기는 것이 DLL 두 종류뿐이다",
          mp.ROOT_KEEP == ("python3*.dll", "vcruntime*.dll"), mp.ROOT_KEEP)

    # ── 켜는 버튼 ──
    check("켜는 버튼이 .exe 다 (스크립트면 SAC 가 막는다)",
          mp.LAUNCHER.endswith(".exe"), mp.LAUNCHER)
    # 탐색기의 zip 풀기가 한글 이름을 못 살리는 경우가 있다 (실기에서 확인).
    check("묶음이 만드는 이름이 ASCII 다",
          mp.LAUNCHER.isascii() and mp.README_NAME.isascii(),
          (mp.LAUNCHER, mp.README_NAME))
    sc = (ROOT / "build" / "sitecustomize.py").read_text(encoding="utf-8")
    ns = {}
    exec(compile(sc.split("if _double_clicked():")[0], "sitecustomize", "exec"), ns)
    check("sitecustomize 가 목록 자리를 실행 파일 옆 data 로 준다",
          f'"{config.DATA_ENV}"' in sc and "data" in sc,
          "환경변수 이름이 config.DATA_ENV 와 같아야 한다")
    # 두 번 눌러 들어온 대화형(argv == ['']) 일 때만 끼어들어야 한다.
    # 안 그러면 -m pibo_connector 가 스스로를 두 번 띄운다.
    for argv, want in (([""], True), (["-m"], False), (["x.py", "--check"], False)):
        old_argv, sys.argv = sys.argv, list(argv)
        try:
            got = ns["_double_clicked"]()
        finally:
            sys.argv = old_argv
        check(f"argv={argv} 일 때 자동 시작 {'함' if want else '안 함'}", got is want)

    # 스크립트는 묶는 쪽에서도 만들지 않는다. SAC 가 막는 종류를 두지 않는다.
    # 주석·설명에는 .bat 이야기가 나오므로 '파일 이름' 문자열만 본다.
    src = (ROOT / "build" / "make_portable.py").read_text(encoding="utf-8")
    named = [n.value for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Constant) and isinstance(n.value, str)
             and n.value.lower().endswith((".bat", ".cmd"))]
    check("묶는 코드가 만드는 파일 중 스크립트가 없다", not named, named)

    # 환경변수 우회가 실제로 먹는지. 안 먹으면 목록이 묶음 밖에 생긴다.
    import os
    with tempfile.TemporaryDirectory() as td:
        want_dir = Path(td) / "data"
        old = os.environ.get(config.DATA_ENV)
        os.environ[config.DATA_ENV] = str(want_dir)
        try:
            got_dir = config.data_dir()
        finally:
            if old is None:
                os.environ.pop(config.DATA_ENV, None)
            else:
                os.environ[config.DATA_ENV] = old
        check(f"{config.DATA_ENV} 가 목록 자리를 바꾼다", got_dir == want_dir, got_dir)
    check("환경변수를 지우면 원래대로", config.data_dir() == ROOT, config.data_dir())

    # PE 인증서 테이블을 읽는 오프셋 계산. 이게 틀리면 서명 없는 python.exe 를
    # '서명 있다' 로 통과시켜 묶음의 존재 이유가 사라진다. 합성 PE 로 확인한다.
    import struct
    def fake_pe(cert_off, cert_size, ctype=0x0002, magic=0x20B, payload=b""):
        e = 0x80
        b = bytearray(0x400)
        b[0:2] = b"MZ"
        struct.pack_into("<I", b, 0x3C, e)
        b[e:e + 4] = b"PE\0\0"
        struct.pack_into("<H", b, e + 24, magic)          # optional header magic
        dd = e + 24 + (112 if magic == 0x20B else 96)     # 데이터 디렉토리 시작
        struct.pack_into("<II", b, dd + 4 * 8, cert_off, cert_size)  # 4번 = Certificate
        if cert_off:
            struct.pack_into("<IHH", b, cert_off, cert_size, 0x0200, ctype)
            b[cert_off + 8:cert_off + 8 + len(payload)] = payload   # PKCS#7 자리
        return bytes(b)

    with tempfile.TemporaryDirectory() as td:
        def ask(data):
            f = Path(td) / "t.exe"
            f.write_bytes(data)
            return mp.pe_cert_blob(f)
        check("서명 있는 PE32+ 를 알아본다", ask(fake_pe(0x200, 0x100))[0] is True)
        check("서명 있는 PE32 도 알아본다", ask(fake_pe(0x200, 0x100, magic=0x10B))[0] is True)
        check("Certificate Table 이 비면 '서명 없음'", ask(fake_pe(0, 0))[0] is False)
        check("PKCS#7 이 아니면 거른다", ask(fake_pe(0x200, 0x100, ctype=0x0001))[0] is False)
        check("PE 가 아니면 거른다", ask(b"\x7fELF" + bytes(0x400))[0] is False)
        # 잘라낸 blob 이 PKCS#7 자리인지. 여기서 주체 이름을 찾으므로 어긋나면
        # 'PSF 가 아니다' 로 멀쩡한 배포본을 거른다.
        mark = mp.SIGNER.encode()
        got = ask(fake_pe(0x200, 0x100, payload=mark))[1]
        check("blob 이 WIN_CERTIFICATE 헤더 뒤부터다", got.startswith(mark), got[:40])
        check("blob 길이가 size - 8 이다", len(got) == 0x100 - 8, len(got))

    # 주체 이름 찾기. 체인 확인이 안 되는 러너에서 이게 1차 관문이다.
    check("PSF 이름을 찾는다", mp.blob_names_signer(b"xx" + mp.SIGNER.encode() + b"yy"))
    check("UTF-16 로 들어 있어도 찾는다",
          mp.blob_names_signer(b"\x00" + mp.SIGNER.encode("utf-16-le")))
    check("다른 이름은 거른다", not mp.blob_names_signer(b"Some Other Corp, Ltd."))


def test_server():
    """소스 실행이 실제로 뜨는지. 포트는 고정으로 가정하지 않는다 —
    _free_port 가 막힌 포트를 피해 옮기므로 서버가 찍는 주소를 읽는다."""
    print("서버 기동")
    log = Path(tempfile.gettempdir()) / "smoke_server.log"
    with Server([sys.executable, str(ROOT / "run.py"), "--no-browser"],
                log, cwd=str(ROOT)) as srv:
        info, died = srv.wait_ready(60.0)
        check("/api/info 가 200", info is not None,
              (f"exit {srv.proc.returncode}" if died else "기동 안 됨")
              + " — " + srv.log().strip()[-500:])
        if not info:
            return
        check("codepath 고정", info["codepath"] == config.CODEPATH, info["codepath"])
        check("트리거 포트", info["trigger_port"] == config.TRIG_PORT)
        try:
            st, html = srv.get("/", 5)
            check("화면이 나온다", st == 200 and "파이보 커넥터" in html)
            # codepath(_fleet.py) 를 UI 에 노출하지 않는다 (executeb 에 is_protect 가 없다).
            # /home/pi/code 폴더 자체는 [로봇 안의 파일] 의 기본 위치라 화면에 있어도 된다.
            check("화면에 codepath 가 없다",
                  config.CODEPATH not in html and "_fleet" not in html)
            check("화면에 codepath 를 바꾸는 입력칸이 없다",
                  'name="codepath"' not in html and 'id="codepath"' not in html)
        except Exception as ex:
            check("화면이 나온다", False, str(ex))
        for path in ("/static/app.js", "/static/maker-ui.css", "/static/style.css",
                     "/static/fonts/pretendard.css",
                     "/static/fonts/woff2-dynamic-subset/PretendardVariable.subset.0.woff2",
                     "/static/img/favicon.png", "/static/img/pibo-logo.png",
                     "/static/img/pibo-hello.png", "/favicon.ico"):
            try:
                st, _ = srv.get(path, 5)
                check(f"서빙 {path}", st == 200, f"status {st}")
            except Exception as ex:
                check(f"서빙 {path}", False, str(ex))
        check("화면이 학습지 테마를 부른다", 'maker-ui.css' in html and 'fonts/pretendard.css' in html)
        check("파이보 얼굴 파비콘", 'img/favicon.png' in html)


def main() -> int:
    utf8_console(sys.stdout, sys.stderr)
    for fn in (test_parse_system, test_detect, test_store, test_ap_rx,
               test_wrap, test_launcher, test_release_notes, test_spec_paths,
               test_portable, test_server):
        fn()
    print()
    if FAIL:
        print(f"실패 {len(FAIL)}건: " + ", ".join(FAIL))
        return 1
    print("전부 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
