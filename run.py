#!/usr/bin/env python3
"""소스 실행용 진입점.

    pip install -r requirements.txt
    python run.py

exe 로 쓰려면 릴리스의 pibo-connect.exe 를 받으면 된다 — 같은 코드다.
"""

import sys

from pibo_connector.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
