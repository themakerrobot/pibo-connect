"""새 버전이 나왔는지 한 번만 확인한다. 못 하면 조용히 넘어간다.

교실 노트북은 한 번 받은 버전에 그대로 머문다. 고친 것이 나가도 선생님은
모른다. 그래서 켤 때 릴리스를 한 번만 보고, 더 새 것이 있으면 화면 위에
한 줄로 알린다. 그게 전부다 — 내려받지도, 고치지도 않는다.

오프라인 교실이 기본값이라는 점을 잊지 않는다.
  · 서버 기동을 막지 않는다 (뒤에서 돌고, 끝나면 그때 알린다)
  · 못 해도 아무 말 하지 않는다. 실패는 결과가 없는 것과 같다
  · PIBO_CONNECT_NO_UPDATE_CHECK=1 이면 아예 부르지 않는다
"""

import os
import re
from typing import Optional, Tuple

REPO = "themakerrobot/pibo-connect"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"
ENV_OFF = "PIBO_CONNECT_NO_UPDATE_CHECK"

_NUM = re.compile(r"\d+")


def disabled() -> bool:
    return bool(os.environ.get(ENV_OFF, "").strip())


def _parts(v: str) -> Tuple[int, ...]:
    """'v0.5.3' → (0, 5, 3). 숫자만 본다 — 'nightly' 같은 건 ()."""
    return tuple(int(x) for x in _NUM.findall(v or ""))


def newer(latest: str, current: str) -> bool:
    """latest 가 current 보다 새 것인가.

    숫자를 못 뽑으면(nightly 등) 새 것이 아니라고 본다. 틀려서 알리는 것보다
    조용한 쪽이 낫다 — 선생님에게 쓸데없는 빨간 줄을 띄우지 않는다.
    """
    a, b = _parts(latest), _parts(current)
    if not a or not b:
        return False
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


async def check(current: str, timeout: float = 4.0) -> Optional[dict]:
    """더 새 버전이 있으면 {'latest','url'}, 아니면 None. 예외를 내지 않는다."""
    if disabled():
        return None
    try:
        import aiohttp
        headers = {"Accept": "application/vnd.github+json",
                   "User-Agent": f"pibo-connect/{current}"}
        async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=timeout)) as s:
            async with s.get(LATEST_API, headers=headers) as r:
                if r.status != 200:
                    return None
                data = await r.json(content_type=None)
    except Exception:
        return None                      # 오프라인 교실. 아무 일도 없던 것으로

    tag = str((data or {}).get("tag_name") or "").strip()
    if not newer(tag, current):
        return None
    return {"latest": tag.lstrip("vV"), "url": RELEASES_URL}
