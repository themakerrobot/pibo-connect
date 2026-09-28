#!/usr/bin/env python3
"""릴리스 페이지 본문을 만든다. CHANGELOG.md 의 해당 절 + 받기·실행 안내.

    python build/release_notes.py --tag v0.3.2 --sha abc123 --out notes.md

릴리스 페이지는 선생님이 링크를 받아 여는 곳이다. 그래서 본문은
'무엇이 바뀌었나(CHANGELOG)' → '어떻게 받나' → '어떻게 켜나' → '잘 안 될 때'
순서다. 개발자용 정보는 맨 아래 접어 둔다.
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"

HOWTO = """### 받기

아래 **Assets** 에서 하나만 받으면 돼요.

| 노트북 | 받을 파일 | |
|---|---|---|
| **Windows** | **`pibo-connect-windows-portable.zip`** | **이걸 받으세요.** 압축을 풀고 `pibo-connect.exe` 를 두 번 눌러요 |
| Windows | `pibo-connect-windows.exe` | 파일 하나로 쓰고 싶을 때. PC 에 따라 "차단되었습니다" 가 뜰 수 있어요 |
| macOS | `pibo-connect-macos` | 터미널에서 `chmod +x` 한 뒤, 첫 실행은 우클릭 → 열기 |
| Linux | `pibo-connect-linux` | `chmod +x` 한 뒤 실행 |

### 실행하기 (Windows, zip)

1. 받은 zip 파일을 **오른쪽 클릭 → [압축 풀기]** 를 누르세요.
   (zip 안에서 바로 두 번 누르면 안 켜져요. 꼭 풀어서 쓰세요.)
2. 풀린 폴더에서 **`pibo-connect.exe`** 를 두 번 누르세요.
3. 검은 창이 하나 뜨고, 잠시 뒤 브라우저가 열려요.
   **검은 창은 닫지 마세요** — 닫으면 꺼져요.
4. 로봇과 노트북이 **같은 와이파이**에 있는지 확인하고 [로봇 찾기] 를 누르세요.

이 묶음은 "이 앱이 차단되었습니다" 창이 뜨지 않도록 만든 거예요. 누르는 파일이
python.org 가 서명해서 배포하는 공식 파이썬이고, 이름만 알아보기 쉽게 바꾼 거예요.
(서명은 파일 이름이 아니라 내용에 붙어 있어서 그대로 살아 있어요.)

### 실행하기 (Windows, exe)

1. 받은 파일을 더블클릭해요.
2. **"Windows의 PC 보호"** 창이 뜨면 → **추가 정보** → **실행**. 그 PC 에서는 한 번이면 돼요.
3. **"이 앱이 차단되었습니다"** 가 뜨면 → 위의 zip 을 받으세요. 그건 안 막혀요.
4. 나머지는 위와 같아요.

### 잘 안 될 때

- **로봇이 안 찾아져요** → 로봇이 켜져 있고 노트북과 같은 와이파이인지 봐요.
  5초쯤 기다렸다 한 번 더 눌러요. 그래도 없으면 묶음 폴더에서 주소창에 `cmd` 를 치고
  `pibo-connect.exe -m pibo_connector --check 192.168.0.51` 처럼 써요 (로봇 주소로 바꿔서).
  어디서 막혔는지 한 줄씩 알려줘요.
- **그래도 "차단되었습니다" 가 떠요** → 압축을 풀기 **전에** zip 파일을 오른쪽 클릭 →
  [속성] → 맨 아래 **[차단 해제]** 를 체크하고 확인을 누른 다음 압축을 푸세요.
- **브라우저가 안 열려요** → 검은 창에 적힌 주소(보통 `http://127.0.0.1:8900/`)를
  브라우저에 직접 넣어요.
- **로봇이 대답을 안 해요** → [다시 확인] 을 누르고, 그래도 없으면 [로봇 찾기] 를 다시 눌러요.
"""


def section_for(tag: str, text: str = None) -> str:
    """CHANGELOG.md 에서 그 버전 절만 떼어낸다. 없으면 빈 문자열."""
    text = CHANGELOG.read_text(encoding="utf-8") if text is None else text
    want = tag if tag.startswith("v") else "v" + tag
    # '## v0.3.2' 또는 '## v0.3.2 — 날짜' 부터 다음 '## v' 직전까지
    pat = re.compile(
        r"^##\s+" + re.escape(want) + r"\b.*?$(.*?)(?=^##\s+v|\Z)",
        re.M | re.S)
    m = pat.search(text)
    return m.group(1).strip() if m else ""


def title_for(tag: str) -> str:
    """릴리스 제목칸에 들어갈 한 줄."""
    return "파이보 커넥터 (시험용 nightly)" if tag == "nightly" else f"파이보 커넥터 {tag}"


def build(tag: str, sha: str) -> str:
    """본문. 제목은 title_for() 가 맡으므로 여기서 되풀이하지 않는다."""
    if tag == "nightly":
        head = ("코드가 바뀔 때마다 자동으로 다시 만들어지는 **시험용**이에요.\n"
                "수업에는 [정식 버전]"
                "(https://github.com/themakerrobot/pibo-connect/releases/latest) 을 쓰세요.\n")
        body = ""
    else:
        notes = section_for(tag)
        if not notes:
            raise SystemExit(
                f"!! CHANGELOG.md 에 '## {tag}' 절이 없다.\n"
                f"   맨 위에 절을 더하고 다시 태그할 것 (형식: '## {tag} — 2026-09-22')")
        head = ""
        body = notes + "\n"

    intro = ("\n교실의 파이보·파이브레인을 브라우저 한 장으로 찾고, 같은 코드를 한 번에 실행해요.\n"
             "노트북에 아무것도 설치하지 않아요. 아래 파일 하나만 받으면 돼요.\n\n")
    dev = ("\n<details><summary>개발자용</summary>\n\n"
           "소스로 돌리려면 `pip install -r requirements.txt && python run.py`.\n"
           "올라온 파일은 모두 CI 에서 실제로 띄워 화면·글꼴·이미지까지 나오는 것을 확인한 빌드예요.\n"
           "윈도우 zip 묶음은 안에 든 python.exe 의 Authenticode 서명(Python Software\n"
           "Foundation)까지 확인하고 올립니다 — `build/make_portable.py`.\n\n"
           f"커밋 `{sha}`\n</details>\n")
    return head + body + intro + HOWTO + dev


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--sha", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--title", action="store_true", help="본문 대신 제목 한 줄만")
    args = ap.parse_args()
    if args.title:
        print(title_for(args.tag))
        return 0
    text = build(args.tag, args.sha)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"{args.out} 에 썼다 ({len(text)}자)")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
