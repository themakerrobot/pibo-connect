"""가짜 파이보 한 대. 기기 없이 찾기·판별·실행 경로를 통째로 돌려본다.

    python -m tests.mock_pibo --sn cd488e95 --os piBo_260915v1-ph

로봇 쪽 두 서버를 흉내 낸다 — 응답 모양은 openpibo-os.pibo 코드 그대로다.
  :80   socket.io   init → 'system' (system.sh CSV), executeb → 'update'
  :8080 HTTP        /wifi, /wifi_scan, /device/{pkt}
"""

import argparse
import asyncio

import socketio
from aiohttp import web


def build(sn: str, os_version: str, ip: str, with_device: bool, legacy: bool = False):
    sio = socketio.AsyncServer(async_mode="aiohttp", cors_allowed_origins="*")
    app80 = web.Application()
    sio.attach(app80, socketio_path="/socket.io")

    # system/system.sh 의 echo 순서. 판마다 칸 수와 순서가 다르다.
    if legacy:
        # 구형 240701v1 (9칸): … WLAN0, SSID0, ETH1. PSK 칸이 아예 없다.
        system_row = [
            "10000000" + sn, os_version, "12345.6", "48.3'C", "3900000", "2100000",
            ip, "classroom-5g", "",
        ]
    else:
        # 신형 (12칸). 인덱스 9 는 PSK 평문이다 — 커넥터가 이걸 받고도
        # 어디에도 남기지 않는지 보려고 일부러 넣는다.
        system_row = [
            "10000000" + sn, os_version, "12345.6", "48.3'C", "3900000", "2100000",
            ip, "", "classroom-5g", "LeakCanary!234", "", "wpa-psk",
        ]

    @sio.event
    async def connect(sid, environ):
        pass

    @sio.on("init")
    async def on_init(sid):
        await sio.emit("system", system_row)
        await sio.emit("init", {"codepath": "/home/pi/code/main.py",
                                "codetext": "", "path": "/home/pi/code"})

    # 가짜 파일 트리. run_ide.py 의 read_directory 가 주는 모양 그대로.
    TREE = {
        "/home/pi/code": [
            {"name": "lib", "type": "folder", "protect": False},
            {"name": "dance.py", "type": "file", "protect": False},
            {"name": "hello.sh", "type": "file", "protect": False},
        ],
        "/home/pi/code/lib": [
            {"name": "util.py", "type": "file", "protect": False},
        ],
    }
    FILES = {
        "/home/pi/code/dance.py": "print('dance from robot')\n",
        "/home/pi/code/hello.sh": "echo hello from robot\n",
        "/home/pi/code/lib/util.py": "X = 1\n",
    }
    state = {"path": "/home/pi/code"}

    @sio.on("load_directory")
    async def on_load_directory(sid, p):
        if p in TREE:
            state["path"] = p
        await sio.emit("update_file_manager",
                       {"data": TREE.get(state["path"], []), "path": state["path"]})

    @sio.on("load")
    async def on_load(sid, p):
        if p in FILES:
            await sio.emit("update", {"code": FILES[p], "filepath": p})
        else:
            await sio.emit("update", {"dialog": "err_load", "detail": f"no such file: {p}"})

    @sio.on("executeb")
    async def on_executeb(sid, d):
        # run_ide.py 의 execute() 처럼 record 를 누적해 보낸다
        code = d.get("codetext", "")
        rec = "[mock]: \n\n"
        await sio.emit("update", {"record": rec})
        # 커넥터의 '로봇 파일 실행' 런처를 흉내 낸다
        import re as _re
        m = _re.search(r"^_p = '(.+)'$", code, _re.M) or \
            _re.search(r"exec sh '(.+?)'", code)
        if m:
            target = m.group(1)
            rec += (f"[mock] ran {target}\n" + FILES[target]) if target in FILES \
                else f"[missing] {target}\n"
            await sio.emit("update", {"record": rec})
            rec += "\n종료됨." if legacy else "\n[exit]"
            await sio.emit("update", {"record": rec, "exit": True})
            return
        for line in code.splitlines():
            if line.startswith("print("):
                rec += line[6:-1].strip("'\"") + "\n"
                await sio.emit("update", {"record": rec})
                await asyncio.sleep(0.05)
        if "[ready]" in code or "print('[ready]'" in code:
            rec += "[ready]\n"
            await sio.emit("update", {"record": rec})
            await asyncio.sleep(0.3)
        # 구형 main.js 는 '종료됨.' 을 찍는다. 커넥터는 exit 플래그를 보므로 상관없다.
        rec += "\n종료됨." if legacy else "\n[exit]"
        await sio.emit("update", {"record": rec, "exit": True})

    @sio.on("stop")
    async def on_stop(sid):
        await sio.emit("update", {"record": "[stopped]", "exit": True})

    app8080 = web.Application()

    async def wifi(_req):
        # booting.py 는 psk 를 평문으로 돌려준다
        return web.json_response({"result": "ok", "ssid": "classroom-5g",
                                  "psk": "LeakCanary!234", "ipaddress": ip,
                                  "eth1": "", "identity": "", "key-mgmt": "wpa-psk"})

    async def wifi_scan(_req):
        return web.json_response([
            {"essid": "classroom-5g", "signal_quality": 88, "encryption": "on"},
            {"essid": "pibo-deadbeef", "signal_quality": 41, "encryption": "on"},
        ])

    async def device(req):
        pkt = req.match_info["pkt"]
        if not with_device:
            return web.json_response("")
        if pkt == "#40:!":
            return web.json_response("#40:12-0-1-0-99:!")
        return web.json_response(f"Error: unknown {pkt}")

    app8080.router.add_get("/wifi", wifi)
    app8080.router.add_get("/wifi_scan", wifi_scan)
    app8080.router.add_get("/device/{pkt}", device)
    return app80, app8080


async def run(args):
    app80, app8080 = build(args.sn, args.os, args.ip, not args.no_device, args.legacy)
    r1 = web.AppRunner(app80)
    await r1.setup()
    await web.TCPSite(r1, args.bind, args.ide_port).start()
    r2 = web.AppRunner(app8080)
    await r2.setup()
    await web.TCPSite(r2, args.bind, args.sys_port).start()
    print(f"mock pibo  SN={args.sn}  OS={args.os}  "
          f"http://{args.bind}:{args.ide_port} (ide) / :{args.sys_port} (sys)")
    await asyncio.Event().wait()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sn", default="cd488e95")
    ap.add_argument("--os", default="piBo_260915v1-ph")
    ap.add_argument("--ip", default="127.0.0.1")
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--ide-port", type=int, default=0, help="0 이면 판에 맞춰 고른다")
    ap.add_argument("--sys-port", type=int, default=8080)
    ap.add_argument("--no-device", action="store_true")
    ap.add_argument("--legacy", action="store_true",
                    help="구형 240701v1 흉내 — IDE 50000, system.sh 9칸, '종료됨.'")
    args = ap.parse_args()
    if not args.ide_port:
        args.ide_port = 50000 if args.legacy else 80
    if args.legacy and args.os == "piBo_260915v1-ph":
        args.os = "piBo_240701v1"
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
