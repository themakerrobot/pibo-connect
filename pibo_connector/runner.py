"""실행 — 여러 대에 같은 코드를 던지고 출력을 되받는다.

  run()  : executeb 를 동시에 던진다. 시작 시각은 대당 수백 ms 어긋난다.
  sync() : 무거운 import 를 먼저 끝내게 해두고, 전부 [ready] 가 되면
           UDP 한 방으로 동시에 푼다.

파이썬 CLI(pibofan) 는 고정 초를 기다린 뒤 트리거를 쐈지만,
여기서는 실제 [ready] 개수를 세서 전부 준비되면 곧바로 쏜다.
"""

import asyncio
import os
import posixpath
import time
from typing import Callable, Dict, List, Optional, Tuple

from . import config, net, robot
from .store import Fleet

Emit = Callable[[dict], None]


def _noop(_: dict) -> None:
    pass


# 동시 시작 래퍼. 사용자 코드는 '# --- GO ---' 한 줄로 앞뒤를 나눈다.
# 앞은 준비(import 등), 뒤가 본편이다.
WRAP = '''# pibo-connect sync wrapper
import socket as _pc_s
_pc_k = _pc_s.socket(_pc_s.AF_INET, _pc_s.SOCK_DGRAM)
_pc_k.setsockopt(_pc_s.SOL_SOCKET, _pc_s.SO_REUSEADDR, 1)
_pc_k.bind(('', {port}))

{body}

print('[ready]', flush=True)
_pc_k.settimeout({wait})
try:
    _pc_k.recvfrom(64)
except OSError:
    _pc_k.close()
    raise SystemExit('[timeout] 트리거가 안 왔다 (공유기의 AP isolation / 브로드캐스트 차단 확인)')
_pc_k.close()

{main}
'''


def normalize_path(path: str) -> str:
    """상대 경로는 ROBOT_HOME 기준. 항상 로봇(리눅스) 경로다."""
    p = (path or "").strip()
    if not p:
        raise ValueError("경로가 비었다")
    if not p.startswith("/"):
        p = posixpath.join(config.ROBOT_HOME, p)
    return posixpath.normpath(p)


def launcher_for(path: str) -> Tuple[str, str]:
    """로봇에 이미 있는 파일을 실행하는 짧은 코드. (codetext, codetype).

    executeb 는 codetext 를 _fleet.py 로 쓰고 실행하므로, 대상 파일 자체는
    손대지 않는다. .py 는 runpy 로 __main__ 처럼, .sh 는 sh 로 돌린다.
    없는 파일이면 '[missing] 경로' 를 찍고 끝나 출력칸에서 바로 보인다.
    """
    p = normalize_path(path)
    d = posixpath.dirname(p) or "/"
    if p.endswith(".sh"):
        def q(x):   # 셸 한따옴표 이스케이프
            return "'" + x.replace("'", "'\\''") + "'"
        return (f"[ -f {q(p)} ] || {{ echo '[missing]' {q(p)}; exit 1; }}\n"
                f"cd {q(d)} && exec sh {q(p)}\n"), "shell"
    code = (
        "# pibo-connect: 로봇에 있는 파일을 그 자리에서 실행한다\n"
        "import os, runpy, sys\n"
        f"_p = {p!r}\n"
        "if not os.path.isfile(_p):\n"
        "    raise SystemExit('[missing] ' + _p)\n"
        "sys.argv = [_p]\n"
        "os.chdir(os.path.dirname(_p))\n"
        "sys.path.insert(0, os.path.dirname(_p))\n"
        "runpy.run_path(_p, run_name='__main__')\n"
    )
    return code, "python"


def tail_of(record: str, n: int = 1) -> str:
    lines = [l for l in (record or "").strip().split("\n") if l.strip()]
    return "\n".join(lines[-n:]) if lines else ""


class Job:
    """진행 중인 실행 하나. 동시에 하나만 돌린다."""

    def __init__(self, kind: str, targets: List[str], emit: Emit):
        self.kind = kind
        self.targets = targets
        self.emit = emit
        self.started = time.time()
        self.links: Dict[str, robot.RobotLink] = {}
        self.records: Dict[str, str] = {sn: "" for sn in targets}
        self.state: Dict[str, str] = {sn: "pending" for sn in targets}
        self.task: Optional[asyncio.Task] = None
        self.cancelled = False

    def snapshot(self) -> dict:
        # 로봇별 상태는 'states' 다. 'state' 는 job 이벤트의 단계(start/end…)가
        # 쓰는 키라, 여기서 같은 이름을 쓰면 emit 의 **snapshot() 이 덮어써서
        # 화면이 실행이 끝난 줄 모른다. 실제로 그랬다.
        return {
            "kind": self.kind,
            "elapsed": round(time.time() - self.started, 1),
            "states": dict(self.state),
            "tails": {sn: tail_of(rec) for sn, rec in self.records.items()},
        }


class Runner:
    def __init__(self, fleet: Fleet, emit: Emit = _noop):
        self.fleet = fleet
        self.emit = emit
        self.job: Optional[Job] = None
        # 실행이 끝나면 job 은 사라진다. 전체 로그를 나중에 펼쳐 볼 수 있게 남긴다.
        self.last_records: Dict[str, str] = {}

    def busy(self) -> bool:
        return self.job is not None and self.job.task is not None \
            and not self.job.task.done()

    # ── 공통 ────────────────────────────────────────────────────────
    async def _open(self, job: Job, sn: str) -> Optional[robot.RobotLink]:
        ip = self.fleet.ip_of(sn)
        if not ip:
            job.state[sn] = "no-ip"
            self.emit({"type": "run", "sn": sn, "state": "no-ip"})
            return None
        try:
            link = robot.RobotLink(ip, timeout=10.0)

            def on_record(rec: str, _sn=sn, _job=job):
                _job.records[_sn] = rec
                self.emit({"type": "output", "sn": _sn, "tail": tail_of(rec),
                           "len": len(rec)})

            link.on_record = on_record
            await link.connect()
            job.links[sn] = link
            job.state[sn] = "connected"
            self.emit({"type": "run", "sn": sn, "state": "connected"})
            return link
        except Exception as ex:
            job.state[sn] = "error"
            job.records[sn] = f"!! 접속 실패: {ex}"
            self.emit({"type": "run", "sn": sn, "state": "error", "detail": str(ex)})
            return None

    async def _close_all(self, job: Job) -> None:
        for link in job.links.values():
            try:
                await link.close()
            except Exception:
                pass
        job.links.clear()

    # ── 그냥 실행 ───────────────────────────────────────────────────
    async def run(self, targets: List[str], code: str, codetype: str = "python",
                  timeout: float = 300.0, kind: str = "run") -> dict:
        job = Job(kind, targets, self.emit)
        self.job = job
        self.emit({"type": "job", "state": "start", "kind": kind,
                   "targets": targets})
        try:
            links = await asyncio.gather(*(self._open(job, sn) for sn in targets))
            live = [(sn, l) for sn, l in zip(targets, links) if l]
            if not live:
                return {"ok": False, "reason": "접속된 로봇이 없다", **job.snapshot()}

            for sn, link in live:
                await link.execute(code, codetype)
                job.state[sn] = "running"
            self.emit({"type": "job", "state": "running",
                       "targets": [sn for sn, _ in live]})

            async def wait_one(sn: str, link: robot.RobotLink):
                done = await link.wait_exit(timeout)
                job.state[sn] = "done" if done else "timeout"
                job.records[sn] = link.record
                self.emit({"type": "run", "sn": sn, "state": job.state[sn],
                           "tail": tail_of(link.record)})

            await asyncio.gather(*(wait_one(sn, l) for sn, l in live))
            return {"ok": True, **job.snapshot()}
        finally:
            await self._close_all(job)
            self.last_records = dict(job.records)
            self.emit({"type": "job", "state": "end", **job.snapshot()})
            self.job = None

    async def run_path(self, targets: List[str], path: str,
                       timeout: float = 300.0) -> dict:
        """로봇에 이미 있는 파일을 경로로 실행한다. 편집기 내용은 쓰지 않는다."""
        code, codetype = launcher_for(path)
        return await self.run(targets, code, codetype, timeout, kind="run_path")

    # ── 동시 시작 ───────────────────────────────────────────────────
    async def sync(self, targets: List[str], code: str,
                   ready_timeout: float = 60.0, wait: float = 120.0,
                   timeout: float = 300.0) -> dict:
        body, main = (code.split(config.SYNC_MARK, 1)
                      if config.SYNC_MARK in code else ("", code))
        wrapped = WRAP.format(port=config.TRIG_PORT, wait=wait,
                              body=body, main=main)

        job = Job("sync", targets, self.emit)
        self.job = job
        self.emit({"type": "job", "state": "start", "kind": "sync",
                   "targets": targets})
        try:
            links = await asyncio.gather(*(self._open(job, sn) for sn in targets))
            live = [(sn, l) for sn, l in zip(targets, links) if l]
            if not live:
                return {"ok": False, "reason": "접속된 로봇이 없다", **job.snapshot()}

            for sn, link in live:
                await link.execute(wrapped, "python")
                job.state[sn] = "preparing"
            self.emit({"type": "job", "state": "preparing",
                       "targets": [sn for sn, _ in live]})

            # 전부 [ready] 를 찍을 때까지 기다린다. 고정 초를 쓰지 않는다.
            deadline = time.time() + ready_timeout
            ready: set = set()
            while time.time() < deadline and len(ready) < len(live):
                for sn, link in live:
                    if sn not in ready and "[ready]" in (link.record or ""):
                        ready.add(sn)
                        job.state[sn] = "ready"
                        self.emit({"type": "run", "sn": sn, "state": "ready"})
                if len(ready) < len(live):
                    await asyncio.sleep(0.1)

            not_ready = [sn for sn, _ in live if sn not in ready]
            ips = [self.fleet.ip_of(sn) for sn, _ in live if self.fleet.ip_of(sn)]

            # 트리거. 브로드캐스트가 막혀 있어도 유니캐스트로 한 번 더 간다.
            sent = await asyncio.get_running_loop().run_in_executor(
                None, lambda: net.udp_broadcast(b"GO", config.TRIG_PORT, 3, ips))
            self.emit({"type": "job", "state": "trigger", "sent_to": sent,
                       "ready": sorted(ready), "not_ready": not_ready})

            async def wait_one(sn: str, link: robot.RobotLink):
                done = await link.wait_exit(timeout)
                job.state[sn] = "done" if done else "timeout"
                job.records[sn] = link.record
                self.emit({"type": "run", "sn": sn, "state": job.state[sn],
                           "tail": tail_of(link.record)})

            await asyncio.gather(*(wait_one(sn, l) for sn, l in live))
            return {"ok": True, "ready": sorted(ready), "not_ready": not_ready,
                    "trigger_sent_to": sent, **job.snapshot()}
        finally:
            await self._close_all(job)
            self.last_records = dict(job.records)
            self.emit({"type": "job", "state": "end", **job.snapshot()})
            self.job = None

    # ── 정지 ────────────────────────────────────────────────────────
    async def stop(self, targets: List[str]) -> dict:
        """run_ide.py 의 stop 핸들러 — 프로세스 kill, servo init, play/llama pkill."""
        job = self.job
        if job:
            job.cancelled = True
            if job.task and not job.task.done():
                job.task.cancel()

        async def one(sn: str):
            ip = self.fleet.ip_of(sn)
            if not ip:
                return sn, "no-ip"
            try:
                async with robot.RobotLink(ip, timeout=5.0) as link:
                    await link.stop()
                    await asyncio.sleep(0.3)
                return sn, "stopped"
            except Exception as ex:
                return sn, f"error: {ex}"

        res = await asyncio.gather(*(one(sn) for sn in targets))
        out = {sn: state for sn, state in res}
        self.emit({"type": "job", "state": "stopped", "result": out})
        return out
