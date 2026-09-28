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
               test_server):
        fn()
    print()
    if FAIL:
        print(f"실패 {len(FAIL)}건: " + ", ".join(FAIL))
        return 1
    print("전부 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
