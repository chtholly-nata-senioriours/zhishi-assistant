"""发版核查 ②：发布包密钥泄漏复检。

用途
    确认用户的真实密钥**没有**进到发布目录 / 发布 zip 里。
    密钥只应存在于 `~/.pet_demo/user_config.json`（在项目目录之外）。

用法
    python dev_bootstrap.py spikes/leak_check.py

做法
    - 递归取 `~/.pet_demo/user_config.json` 里所有长度 >= 16 的字符串
      （**只做存在性搜索，绝不打印值**）
    - 与 `config.default.json` 同路径默认值比对：
        用户值 == 默认值 -> benign（出现在包内属正常，不计失败）
        用户值 != 默认值 -> sensitive（用户自定义，命中即 FAIL）
    - 扫描发布目录（逐文件）与发布 zip（**逐条目解压后**扫描）

⚠ 为什么 zip 必须逐条目解压
    压缩后的字节流里搜原始明文不可靠（DEFLATE 后明文已不存在）。
    必须 `z.read(name)` 解压出真实内容再搜。

退出码：0 = 无泄漏，1 = 发现泄漏。
"""

from __future__ import annotations

import json
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")

with open(os.path.join(ROOT, "config.default.json"), encoding="utf-8") as f:
    DEFAULT_CFG = json.load(f)
VERSION = DEFAULT_CFG["version"]
# v1.7.0 起产品改名「知时助手」，发布目录随之改名（见 spikes/_refresh_release.py）
REL_NAME = f"知时助手-v{VERSION}-win64"
REL_DIR = os.path.join(DIST, REL_NAME)
ZIP_PATH = os.path.join(DIST, REL_NAME + ".zip")

MIN_LEN = 16  # 太短的值（如版本号）会造成误报
SK_RE = re.compile(rb"sk-[A-Za-z0-9_\-]{20,}")


def get_path(d, path):
    cur = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def walk(d, path=""):
    if isinstance(d, dict):
        for k, v in d.items():
            yield from walk(v, f"{path}.{k}" if path else k)
    elif isinstance(d, str):
        yield path, d


def load_secrets():
    user_cfg_path = os.path.expanduser("~/.pet_demo/user_config.json")
    with open(user_cfg_path, encoding="utf-8") as f:
        user_cfg = json.load(f)
    sensitive, benign = [], []
    for path, val in walk(user_cfg):
        if len(val) < MIN_LEN:
            continue
        b = val.encode("utf-8")
        (benign if get_path(DEFAULT_CFG, path) == val else sensitive).append((path, b))
    return sensitive, benign


def scan_bytes(data: bytes, sensitive):
    hits = [p for p, s in sensitive if s and s in data]
    return hits, len(SK_RE.findall(data))


def scan_dir(path, sensitive):
    n_files = n_hit = n_sk = 0
    for root, _dirs, files in os.walk(path):
        for fn in files:
            full = os.path.join(root, fn)
            try:
                with open(full, "rb") as fh:
                    data = fh.read()
            except OSError:
                continue
            n_files += 1
            hits, sk = scan_bytes(data, sensitive)
            if hits:
                print(f"      [HIT] {os.path.relpath(full, path)} <- {hits}")
            if sk:
                print(f"      [SK ] {os.path.relpath(full, path)} (x{sk})")
            n_hit += len(hits)
            n_sk += sk
    return n_files, n_hit, n_sk


def scan_zip(path, sensitive):
    n_files = n_hit = n_sk = 0
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            data = z.read(info.filename)  # 逐条目解压
            n_files += 1
            hits, sk = scan_bytes(data, sensitive)
            if hits:
                print(f"      [HIT] {info.filename} <- {hits}")
            if sk:
                print(f"      [SK ] {info.filename} (x{sk})")
            n_hit += len(hits)
            n_sk += sk
    return n_files, n_hit, n_sk


def main() -> int:
    sensitive, benign = load_secrets()
    print(f"[i] 待搜值: sensitive={len(sensitive)} "
          f"({', '.join(p for p, _ in sensitive)}) / benign={len(benign)} "
          f"({', '.join(p for p, _ in benign)})")

    ok = True
    if os.path.isdir(REL_DIR):
        nf, nh, ns = scan_dir(REL_DIR, sensitive)
        print(f"[目录] {REL_NAME}: {nf} 文件 / 敏感命中 {nh} / sk- {ns}")
        ok = ok and nh == 0 and ns == 0
    else:
        print(f"[!] 发布目录不存在: {REL_DIR}")
        ok = False

    if os.path.isfile(ZIP_PATH):
        nf, nh, ns = scan_zip(ZIP_PATH, sensitive)
        print(f"[zip ] {REL_NAME}.zip: {nf} 条目 / 敏感命中 {nh} / sk- {ns}")
        ok = ok and nh == 0 and ns == 0
    else:
        print(f"[!] 发布 zip 不存在: {ZIP_PATH}")
        ok = False

    inner = os.path.join(REL_DIR, "知时助手", "_internal", "config.default.json")
    if os.path.isfile(inner):
        with open(inner, encoding="utf-8") as f:
            ak = json.load(f).get("ai", {}).get("api_key", "")
        print(f"[i] 包内 config.default.json ai.api_key = {ak!r}")
        ok = ok and ak == ""
    else:
        print(f"[!] 包内 config.default.json 未找到: {inner}")
        ok = False

    print()
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
