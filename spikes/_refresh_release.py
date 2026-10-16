"""刷新发布目录与 zip（P2.2）

把 dist/知时助手/ 同步到 dist/知时助手-v<版本>-win64/ 并重打 zip。

（v1.7.0 起发布目录随产品改名，原名 `little-table-pet-`。）
zip 内排除 __pycache__ 与 .pyc（旧 zip 曾混入 21 个缓存文件）。

版本号**从 `config.default.json` 读**，不再手改 —— 发版只需改配置里的 version。

用法：python dev_bootstrap.py spikes/_refresh_release.py
"""

import json
import os
import shutil
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
SRC = os.path.join(DIST, "知时助手")

with open(os.path.join(ROOT, "config.default.json"), encoding="utf-8") as _f:
    VERSION = json.load(_f)["version"]

REL_NAME = f"知时助手-v{VERSION}-win64"
REL_DIR = os.path.join(DIST, REL_NAME)
ZIP_PATH = os.path.join(DIST, REL_NAME + ".zip")
TOP = "知时助手"

# --- 安全护栏：只允许操作 dist/ 下、名字以 知时助手- 开头的目录 ---
assert os.path.basename(os.path.dirname(REL_DIR)) == "dist", REL_DIR
assert os.path.basename(REL_DIR).startswith("知时助手-"), REL_DIR
assert os.path.isdir(SRC), f"源目录不存在: {SRC}"

# 1) 重建发布目录
if os.path.isdir(REL_DIR):
    shutil.rmtree(REL_DIR)
    print(f"[清理] 已删除旧目录 {REL_DIR}")
shutil.copytree(SRC, os.path.join(REL_DIR, TOP))
print(f"[复制] {SRC} -> {os.path.join(REL_DIR, TOP)}")

# 2) 重打 zip
if os.path.exists(ZIP_PATH):
    os.remove(ZIP_PATH)

n_files = 0
n_skipped = 0
with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for root, dirs, files in os.walk(os.path.join(REL_DIR, TOP)):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in sorted(files):
            if f.endswith(".pyc"):
                n_skipped += 1
                continue
            full = os.path.join(root, f)
            arc = os.path.relpath(full, REL_DIR).replace(os.sep, "/")
            z.write(full, arc)
            n_files += 1

size = os.path.getsize(ZIP_PATH)
print(f"[打包] {n_files} 个文件，跳过 {n_skipped} 个 .pyc，zip = {size:,} bytes ({size/1024/1024:.2f} MB)")

# 3) 校验
with zipfile.ZipFile(ZIP_PATH) as z:
    names = z.namelist()
    assert sorted({n.split("/")[0] for n in names}) == [TOP], "顶层目录不正确"
    assert f"{TOP}/{TOP}.exe" in names, "exe 不在包内"
    assert not any("__pycache__" in n or n.endswith(".pyc") for n in names), "仍有缓存残留"
    bad = z.testzip()
    assert bad is None, f"zip 损坏于 {bad}"

exe = os.path.join(REL_DIR, TOP, TOP + ".exe")
print(f"[校验] 顶层目录 OK / exe 在内 / 无缓存残留 / 完整性 OK")
print(f"[校验] 发布 exe = {exe} ({os.path.getsize(exe):,} bytes)")
print(f"[完成] {ZIP_PATH}")
