#!/usr/bin/env python3
"""端到端验证：分支切换与索引状态更新稳定性。

覆盖场景（对应近期修复的问题）：
  1. 索引状态更新稳定性：轮询 /api/repos/{id}/progress 期间，断言
     - 阶段 current_stage 始终属于合法阶段集合；
     - 索引中（status=indexing）overall_progress 不会出现旧 bug 的
       「flow_labels 阶段误判为 call_graph 且 overall=100%」；
     - 多分支串行索引时，主分支完成后业务分支从 0 重新开始（进度不再残留）；
     - 索引完成后 status=indexed、overall=100。
  2. 分支切换：通过 PATCH active_branches 增删业务分支，断言
     - 添加分支 → 分支 diff 索引建立（files?branch=xxx 非空）；
     - 移除分支 → 分支索引清理（files 为空、active_branches 清空）；
     - 相同分支配置重复保存 → 不触发重新同步（last_indexed_at 不变）。
  3. WebSocket 实时推送：监听 repo_update 消息，断言最终收到
     status=indexed/progress=100，且推送的 progress 与 /progress 接口同源。

用法（需后端已在运行）：
    docker compose exec backend python scripts/verify/verify_branch_sync.py
    # 或宿主机（需 requests 替代 urllib 的 fallback 已内置）：
    python backend/scripts/verify/verify_branch_sync.py --base-url http://localhost:18080 \
        --ws-url ws://localhost:13000/ws --repos-dir ./repos

退出码：0 = 全部 PASS；1 = 存在 FAIL。
"""

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

STAGES = ["git_sync", "scan", "chinese_enrichment", "symbols", "embeddings", "flow_labels", "call_graph"]
TEST_BRANCH = "feature/automated-test"
TEST_FILE = "demo.py"

_failures: list = []


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    suffix = f" ({detail})" if detail else ""
    print(f"[{status}] {name}{suffix}")
    if not cond:
        _failures.append(name)


def http_json(method: str, url: str, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode()
            return resp.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return e.code, json.loads(body) if body else None
        except Exception:
            return e.code, {"detail": body}


def run_git(args, cwd=None) -> None:
    subprocess.run(["git"] + args, cwd=cwd, check=True, capture_output=True, text=True)


def wait_until_indexed(base: str, repo_id: str, timeout: float = 300) -> list:
    """轮询 /progress 直至 indexed/error，返回所有监控点（含 status/overall/stage/stage_progress）。"""
    points = []
    start = time.time()
    while time.time() - start < timeout:
        _, d = http_json("GET", f"{base}/api/repos/{repo_id}/progress")
        if not d:
            time.sleep(2)
            continue
        points.append(d)
        if d.get("status") in ("indexed", "error"):
            break
        time.sleep(2)
    return points


def run_ws_listener(ws_url: str, repo_id: str, collected: list) -> None:
    """后台线程：监听 repo_update 消息写入 collected。"""

    async def listen():
        import websockets
        async with websockets.connect(ws_url) as ws:
            while True:
                raw = await ws.recv()
                msg = json.loads(raw)
                if msg.get("type") == "repo_update" and msg.get("repoId") == repo_id:
                    collected.append(msg)

    try:
        asyncio.run(listen())
    except Exception as exc:  # 连接失败/关闭均记录，由主流程判断
        collected.append({"ws_error": str(exc)})


def create_test_git_repo(repos_dir: Path, name: str):
    """在 repos_dir 下创建临时源码仓库 + 裸仓库（master + 业务分支）。返回裸仓库路径。"""
    auto_dir = repos_dir / "_automated_test"
    auto_dir.mkdir(parents=True, exist_ok=True)
    src = auto_dir / f"{name}-src"
    src.mkdir(parents=True)
    run_git(["init"], src)
    run_git(["config", "user.email", "t@codepop.test"], src)
    run_git(["config", "user.name", "codepop-test"], src)

    (src / TEST_FILE).write_text("def hello():\n    return 'master'\n", encoding="utf-8")
    run_git(["add", "."], src)
    run_git(["commit", "-m", "init master"], src)

    run_git(["checkout", "-b", TEST_BRANCH], src)
    (src / TEST_FILE).write_text(
        "def hello():\n    return 'feature'\n\ndef extra():\n    pass\n",
        encoding="utf-8",
    )
    run_git(["add", "."], src)
    run_git(["commit", "-m", "feature change"], src)

    bare = auto_dir / f"{name}.git"
    run_git(["clone", "--bare", str(src), str(bare)])
    # 裸仓库 HEAD 会继承 src 当前检出的分支（feature），必须指回 master，
    # 否则 preview_remote_branches 会把业务分支误判为默认分支。
    run_git(["-C", str(bare), "symbolic-ref", "HEAD", "refs/heads/master"])
    return str(bare)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080",
                        help="后端地址（容器内默认 8080，宿主机可用 18080）")
    parser.add_argument("--ws-url", default=None,
                        help="WebSocket 地址，默认取 base-url 推导 ws://<host>/ws")
    parser.add_argument("--repos-dir", default="/app/repos",
                        help="后端仓库根目录（容器内 /app/repos；宿主机可用 ./repos，但 git clone 需容器可达）")
    parser.add_argument("--timeout", type=float, default=300, help="单次索引等待上限（秒）")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    ws_url = args.ws_url or base.replace("http", "ws", 1) + "/ws"
    repos_dir = Path(args.repos_dir).resolve()

    print(f"== CodePop 分支切换与索引状态稳定性验证 ==")
    print(f"base-url: {base}\nws-url:   {ws_url}\nrepos-dir: {repos_dir}\n")

    # 0. 健康检查
    code, health = http_json("GET", f"{base}/health")
    check("后端健康检查", code == 200 and health.get("status") == "ok", f"code={code}")

    name = f"branch-sync-test-{uuid.uuid4().hex[:8]}"
    repo_id = None
    try:
        # 1. 创建临时 git 仓库并添加 CodePop 仓库（初始即带业务分支）
        git_url = create_test_git_repo(repos_dir, name)
        print(f"\n[setup] 临时裸仓库: {git_url}")

        code, created = http_json("POST", f"{base}/api/repos", {
            "name": name,
            "git_url": git_url,
            "active_branches": [TEST_BRANCH],
        })
        check("创建仓库成功", code == 201, f"code={code}")
        repo_id = created["id"]
        check("初始 active_branches 正确", created.get("active_branches") == [TEST_BRANCH],
              str(created.get("active_branches")))

        # 2. WS 监听启动
        ws_messages: list = []
        ws_thread = threading.Thread(
            target=run_ws_listener, args=(ws_url, repo_id, ws_messages), daemon=True
        )
        ws_thread.start()

        # 3. 首轮索引监控（master + 业务分支串行）
        print("\n[索引] 等待首次同步完成（master + feature 分支）...")
        points = wait_until_indexed(base, repo_id, args.timeout)
        final = points[-1]
        check("首次同步最终 status=indexed", final.get("status") == "indexed",
              f"status={final.get('status')}, overall={final.get('overall_progress')}")

        # 3.1 索引中状态更新稳定性断言（问题 2 回归）
        stage_valid = all(
            p.get("current_stage") in STAGES for p in points
            if p.get("status") == "indexing" and p.get("current_stage")
        )
        check("索引中 current_stage 均在合法阶段集合", stage_valid)

        # 旧 bug 回归：不允许「indexing 中 overall=100 且 flow_labels 仍在推进、却把 current_stage 判成 call_graph」
        bug_like = 0
        for p in points:
            if p.get("status") != "indexing":
                continue
            sp = p.get("stage_progress") or {}
            overall = p.get("overall_progress")
            cur = p.get("current_stage")
            if cur == "call_graph" and overall == 100 and sp.get("flow_labels", {}).get("progress", 100) < 100:
                bug_like += 1
        check("无「flow_labels 未完成却被判 call_graph/100%」残留（问题2回归）", bug_like == 0,
              f"命中 {bug_like} 次")

        # 多分支串行：master 完成后业务分支应从低进度重新开始（进度不残留）
        resets = 0
        prev_status = None
        for p in points:
            if prev_status == "indexed" and p.get("status") == "indexing" and p.get("overall_progress", 0) < 10:
                resets += 1
            prev_status = p.get("status")
        # WS 消息更密集：任一 indexed 之后再次出现 <=10% 的索引中进度，即新分支从 0 开始
        seen_indexed = False
        ws_reset = False
        for m in ws_messages:
            if m.get("status") == "indexed":
                seen_indexed = True
            elif (
                seen_indexed
                and m.get("status") == "indexing"
                and m.get("progress") is not None
                and m.get("progress") <= 10
            ):
                ws_reset = True
                break
        check("业务分支索引从 0 重新开始（进度不残留）", resets >= 1 or ws_reset,
              f"轮询重置 {resets} 次 / WS 重置 {'是' if ws_reset else '否'}")

        # 3.2 WebSocket 推送断言
        time.sleep(1)
        ws_indexed = [m for m in ws_messages if m.get("status") == "indexed" and m.get("progress") == 100]
        ws_indexing_low = [m for m in ws_messages if m.get("status") == "indexing" and m.get("progress") is not None and m.get("progress") < 100]
        check("WS 收到最终 indexed/100 推送", len(ws_indexed) >= 1, f"{len(ws_indexed)} 条")
        check("WS 推送存在 <100% 的索引中进度", len(ws_indexing_low) >= 1, f"{len(ws_indexing_low)} 条")

        # 4. 分支切换验证
        print("\n[分支切换] ...")

        def branch_files(branch: str):
            code, data = http_json("GET", f"{base}/api/repos/{repo_id}/files?branch={urllib.parse.quote(branch)}")
            return code, (data if isinstance(data, list) else [])

        # 4.1 初始：业务分支已有 diff 索引
        _, files_f = branch_files(TEST_BRANCH)
        check("添加分支后 diff 索引建立（files 非空）", len(files_f) >= 1, f"{len(files_f)} 个文件")

        # 4.2 移除业务分支 → 索引清理
        code, updated = http_json("PATCH", f"{base}/api/repos/{repo_id}", {"active_branches": []})
        check("PATCH 移除分支成功", code == 200, f"code={code}")
        time.sleep(5)  # 等后台同步（仅 master，无变化）结束，避免 last_indexed_at 竞态
        _, repo_now = http_json("GET", f"{base}/api/repos/{repo_id}")
        check("移除后 active_branches 为空", not (repo_now.get("active_branches") or []),
              str(repo_now.get("active_branches")))
        _, files_f = branch_files(TEST_BRANCH)
        check("移除后业务分支索引已清理（files 为空）", len(files_f) == 0, f"{len(files_f)} 个文件")

        # 4.3 相同配置重复保存 → 跳过同步（last_indexed_at 不变）
        _, before = http_json("GET", f"{base}/api/repos/{repo_id}")
        time.sleep(2)
        code, _ = http_json("PATCH", f"{base}/api/repos/{repo_id}", {"active_branches": []})
        time.sleep(2)
        _, after = http_json("GET", f"{base}/api/repos/{repo_id}")
        check("相同分支配置重复保存不触发重新同步", before.get("last_indexed_at") == after.get("last_indexed_at"),
              f"{before.get('last_indexed_at')} vs {after.get('last_indexed_at')}")

        # 4.4 重新添加业务分支 → 重建 diff 索引（轮询 files 出现，避免 sync 未开始的竞态）
        code, _ = http_json("PATCH", f"{base}/api/repos/{repo_id}", {"active_branches": [TEST_BRANCH]})
        check("PATCH 重新添加分支成功", code == 200, f"code={code}")
        wait_until_indexed(base, repo_id, args.timeout)
        deadline = time.time() + 120
        fcnt = 0
        while time.time() < deadline:
            _, files_f = branch_files(TEST_BRANCH)
            fcnt = len(files_f)
            if fcnt >= 1:
                break
            time.sleep(2)
        check("重新添加分支后 diff 索引重建（files 非空）", fcnt >= 1, f"{fcnt} 个文件")

    finally:
        # 5. 清理：删除仓库记录与临时 git 仓库/克隆目录
        if repo_id:
            http_json("DELETE", f"{base}/api/repos/{repo_id}")
        for d in (repos_dir / name, repos_dir / "_automated_test"):
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)

    print(f"\n== 结果：{len(_failures)} 项失败 ==")
    for f in _failures:
        print(f"  - {f}")
    sys.exit(1 if _failures else 0)


if __name__ == "__main__":
    main()
