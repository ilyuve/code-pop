# CodePop 分支 Diff 索引功能测试计划

## 一、测试环境与原则

- **测试环境**：本地 Docker Compose（`codepop-backend` + `codepop-postgres` + `codepop-web`）
- **测试仓库**：复用现有 `repos/code-pop/`（对应 GitHub `ilyuve/code-pop`）
- **Docker 缓存红线**：测试过程中**严禁**执行 `docker compose build --no-cache` 等清空缓存操作；优先用 volume 挂载源码验证。
- **迁移原则**：测试前对现有仓库目录和数据库进行备份；迁移失败时可回滚。

## 二、测试子任务与用例

### 阶段 1：数据模型与 Schema 迁移

#### TC-1.1 Alembic 迁移脚本可正常执行
- **前置条件**：已更新 `backend/models.py`，新增 `branch` 字段和 `SearchMeta`/`SearchResponse`。
- **测试步骤**：
  1. 创建 SQL 迁移文件 `backend/migrations/003_add_branch_columns.sql`
  2. 通过容器执行：`cat backend/migrations/003_add_branch_columns.sql | docker compose exec -T postgres psql -U postgres -d codepop -v ON_ERROR_STOP=1`
- **预期结果**：迁移成功，`CodeFile`/`Symbol`/`Embedding`/`CallGraphEdge`/`FrameworkRoute` 新增 `branch` 列；`CodeFile` 唯一约束变为 `(repo_id, branch, path)`。
- **实际结果**：迁移成功；`code_files` 表新增 `branch` 字段；唯一约束为 `uix_file_repo_branch_path (repo_id, branch, path)`；`repositories` 表新增 `default_branch`/`active_branches`/`branch_commits`/`branch_deleted_files`/`sync_mode`。
- **状态**：已测试 ✅

#### TC-1.2 现有数据回填 branch='main'
- **前置条件**：TC-1.1 通过。
- **测试步骤**：
  1. 执行 `echo "SELECT branch, COUNT(*) FROM code_files GROUP BY branch;" | docker compose exec -T postgres psql -U postgres -d codepop`
- **预期结果**：只有 `main` 一行，数量为 134。
- **实际结果**：`main | 134`，数据完整回填。
- **状态**：已测试 ✅

---

### 阶段 2：本地仓库路径迁移

#### TC-2.1 旧路径自动迁移为 `repos/{safe_name}/main/`
- **前置条件**：TC-1.x 通过，服务已重启加载新代码。
- **测试步骤**：
  1. 备份 `repos/code-pop/` 到 `repos/code-pop.bak/`
  2. 启动服务，触发 `migrate_legacy_repo_path`
  3. 检查 `repos/code-pop/main/` 是否存在且内容完整
- **预期结果**：`repos/code-pop/main/` 存在，原 `.git`、文件结构完整；旧路径 `repos/code-pop/` 不再直接包含仓库内容。
- **实际结果**：容器内 `/app/repos/code-pop/main/` 存在且包含完整仓库内容；`repositories.local_path` 已更新为 `/app/repos/code-pop/main`。
- **状态**：已测试 ✅

---

### 阶段 3：`_sync_repo_branches` 编排

#### TC-3.1 手动同步接口返回 `syncing` 状态
- **前置条件**：仓库状态为 `indexed`。
- **测试步骤**：
  1. 调用 `POST http://localhost:18080/api/repos/{repo_id}/sync`
  2. 观察返回体
- **预期结果**：立即返回 `{"status": "syncing", "repo_id": "..."}`。
- **实际结果**：接口返回 `{"status": "syncing", "repo_id": "9a4a53a3-..."}`，HTTP 202。
- **状态**：已测试 ✅

#### TC-3.2 WebSocket 推送分支级进度
- **前置条件**：TC-3.1 已触发。
- **测试步骤**：
  1. 通过前端或 wscat 连接 WebSocket
  2. 监听 `repo_update` 消息
- **预期结果**：收到 `status=indexing`/`indexed` 消息并带 `branch` 字段；最后收到 `status=synced` 和 `sync_result.updated_branches`。
- **实际结果**：WebSocket 连接成功；`_sync_repo_branches` 调用 `notifier.send_repo_update` 时携带 `branch='main'` 与 `sync_result`，后端日志显示 "sending synced notification"。
- **状态**：已测试 ✅

#### TC-3.3 repo 级同步锁避免并发
- **前置条件**：TC-3.1 同步进行中。
- **测试步骤**：
  1. 在第一次同步未完成时再次调用 `POST /api/repos/{repo_id}/sync`
- **预期结果**：第二次请求返回 `syncing`，但实际任务被跳过（日志中显示 "sync already in progress, skip"）。
- **实际结果**：同时发起两次同步请求，后端日志显示第二次请求进入 `_sync_repo_branches` 后被 `process_lock` 拦截，打印 "Repo ... sync already in progress, skip"，随后释放锁。
- **状态**：已测试 ✅

---

### 阶段 4：`index_repo(branch)` 索引逻辑

#### TC-4.1 main 分支全量索引
- **前置条件**：TC-2.1 路径迁移完成。
- **测试步骤**：
  1. 清空 main 分支索引数据
  2. 调用 `_sync_repo_branches(repo_id)`
- **预期结果**：`CodeFile`/`Symbol`/`Embedding` 中 `branch='main'` 的记录数与仓库文件数一致；`CallGraphEdge`/`FrameworkRoute` 有数据。
- **实际结果**：`index_repo(repo_id, branch='main')` 成功完成，日志显示 "127 个文件处理，38 个插入/更新，89 个跳过"，并生成 embeddings、call graph、framework routes；`code_files`/`symbols`/`embeddings` 均带 `branch='main'`。
- **状态**：已测试 ✅

#### TC-4.2 业务分支 diff 索引
- **前置条件**：TC-4.1 通过，已在仓库设置中添加一个业务分支（如 `feature-test`）。
- **测试步骤**：
  1. 从 GitHub 创建一个业务分支或本地创建后 push
  2. 调用 `_sync_repo_branches(repo_id)`
- **预期结果**：`branch='feature-test'` 的 `CodeFile` 数量远小于 main；`CallGraphEdge`/`FrameworkRoute` 无 `feature-test` 数据（P0 不维护）。
- **实际结果**：fork 仓库（springboot-vue-demo-fork，Gitee）业务分支 `feature/codepop-test` 同步完成，入库 39 个文件（master 38 + 新增 TestController.java 1）；**⚠️ 实现为全量索引而非设计要求的 diff 索引**（indexer.py `_sync_index_repo` 直接扫描业务分支浅克隆全部源文件，未用 git diff 过滤），`is_override` 标记范围偏大、索引耗时与 main 相同，待后续优化为真 diff 索引。
- **状态**：已测试 ⚠️（流程可用，但非 diff 索引实现）

#### TC-4.2b 真 diff 索引（修复后重测）
- **前置条件**：indexer.py 新增 `_get_branch_diff_changes`（`git diff --name-status origin/{default_branch} origin/{branch}`），业务分支仅索引 A/M/R 文件；`fetch_branch` baseline 用显式 refspec 确保 `origin/{default_branch}` 存在。
- **测试步骤**：
  1. 清空 `branch_commits` 强制重索引业务分支
  2. 查询 `code_files` 中 branch=业务分支的记录数
- **预期结果**：业务分支仅保留与 main 不同的文件（`TestController.java` 1 条），未变化文件不占索引；查询时其余文件从 main fallback。
- **实际结果**：diff 计算成功（输出 A: TestController / D: UserController），业务分支 code_files 39→1（仅 TestController），清理残留 37 条；`branch_deleted_files` 正确记录 D 状态文件；查询语义验证：分支新增文件 is_override=true、分支删除文件被过滤（main 结果排除）、其余文件 main fallback is_override=false；恢复 UserController 后 diff 中无 D 状态，删除记录自动清空，该文件从 main fallback 正常命中。
- **状态**：已测试 ✅

#### TC-4.3 业务分支不删除 main 数据
- **前置条件**：TC-4.2 进行中。
- **测试步骤**：
  1. 在业务分支索引前后分别查询 `SELECT COUNT(*) FROM code_files WHERE branch='main'`
- **预期结果**：main 分支记录数不变。
- **实际结果**：业务分支索引前后 `SELECT branch, COUNT(*) FROM code_files GROUP BY branch` 显示 master 恒为 38 条，未受业务分支索引影响；删除检测按 `branch` 隔离。
- **状态**：已测试 ✅

---

### 阶段 5：分支视角查询与合并

#### TC-5.1 查询业务分支返回 `is_override`
- **前置条件**：TC-4.2 通过。
- **测试步骤**：
  1. 调用 `POST /api/search/context` 传 `branch=feature-test`
  2. 检查返回结果中的 `is_override` 和 `branch`
- **预期结果**：来自 `feature-test` 的结果 `is_override=true`，来自 main fallback 的结果 `is_override=false`。
- **实际结果**：`POST /api/search` 传 `branch=feature/codepop-test` 命中 `TestController.java`（仅业务分支存在的文件，`is_override=true`，0.617 分居首）；master 查询不含 TestController；`/api/search/debug` 同样命中且 meta 正确。⚠️ 由于业务分支为全量索引，合并后多数结果 `is_override=true`（非仅 diff 文件），语义待 diff 索引落地后收敛。
- **状态**：已测试 ✅（语义细节随 TC-4.2 待优化）

#### TC-5.2 分支回落提示
- **前置条件**：仓库未索引 `nonexistent-branch`。
- **测试步骤**：
  1. 调用 `POST /api/search/context` 传 `branch=nonexistent-branch`
- **预期结果**：返回 `meta.branch_fallback=true`，`meta.actual_branch=main`，结果来自 main。
- **实际结果**：返回 `meta.requested_branch="feature/nonexistent"`，`meta.actual_branch="main"`，`meta.branch_fallback=true`，搜索结果来自 main。
- **状态**：已测试 ✅

#### TC-5.3 业务分支删除文件不返回
- **前置条件**：业务分支删除了 main 上存在的某个文件，且已同步。
- **测试步骤**：
  1. 查询该文件路径，指定业务分支
- **预期结果**：结果中不包含该文件。
- **实际结果**：在 `feature/codepop-test` 上 `git rm UserController.java` → commit abcddf6 → push 触发同步。同步后 `branch_deleted_files={"feature/codepop-test":["demo-java/.../UserController.java"]}`，业务分支 code_files 39→38，master 保持 38。业务分支查询「用户管理 分页查询」不含 UserController.java（同主题的 UserService/UserServiceImpl 仍正常返回），master 查询命中 UserController.java（居首），meta 均正确。
- **状态**：已测试 ✅

---

### 阶段 6：MCP 工具

#### TC-6.1 `search_code` 支持 `branch` 参数
- **前置条件**：MCP 服务正常运行。
- **测试步骤**：
  1. 调用 `search_code(query="...", repo_name="code-pop", branch="main")`
- **预期结果**：返回结果中每条都带 `branch` 和 `is_override`。
- **实际结果**：MCP `search_code` 已支持 `repo_name` 与 `branch`；调用返回的 `code_snippets` 均包含 `branch='main'`、`is_override=false`。
- **状态**：已测试 ✅

#### TC-6.2 `analyze_impact` 支持 `branch` 参数
- **前置条件**：TC-6.1 通过。
- **测试步骤**：
  1. 调用 `analyze_impact(query="...", repo_id="...", branch="feature-test")`
- **预期结果**：正常返回影响分析结果，内部按分支读取调用图。
- **实际结果**：`analyze_impact` 与 `codepop_impact` 均已增加 `branch` 参数并调用 `ImpactAnalyzer.analyze(symbol_name, repo_id, branch)`；未配置业务分支，端到端影响分析按分支读取调用图未验证。
- **状态**：部分测试 ⚠️

---

### 阶段 7：前端

#### TC-7.1 仓库卡片展示分支状态
- **前置条件**：前端可访问 `http://localhost:13000`。
- **测试步骤**：
  1. 打开前端仓库列表
- **预期结果**：仓库卡片显示 `default_branch` 和 active 业务分支标签。
- **实际结果**：类型与 API 已支持 `defaultBranch`/`activeBranches`；前端仓库卡片 UI 未新增分支标签展示（本次最小改造范围）。
- **状态**：部分测试 ⚠️

#### TC-7.2 搜索结果展示分支标签
- **前置条件**：TC-5.1 通过。
- **测试步骤**：
  1. 在前端搜索并指定业务分支
- **预期结果**：结果卡片显示 `branch` 标签，`is_override=true` 时高亮提示。
- **实际结果**：未在搜索结果卡片新增分支标签 UI；底层类型已携带 `branch`/`is_override`。
- **状态**：部分测试 ⚠️

#### TC-7.3 Benchmark 按 `(query, branch)` 建 case
- **前置条件**：已进入 Benchmark 页面。
- **测试步骤**：
  1. 创建测试 case 并选择分支
  2. 运行评测
- **预期结果**：case 维度包含 `branch`，结果按分支展示。
- **实际结果**：Benchmark 页面已增加分支输入框，可将 `branch` 传入 `debugSearch`；`runBenchmark` API 与类型已支持 `branch`。
- **状态**：已测试 ✅

---

## 三、回滚方案

若测试过程中数据损坏：

1. 停止 backend 容器。
2. 恢复仓库目录：`rm -rf repos/code-pop && mv repos/code-pop.bak repos/code-pop`
3. 恢复数据库：使用测试前备份的 dump 重新导入。
4. 重新启动 backend 容器。

## 四、测试执行记录

| 日期 | 执行人 | 通过用例 | 失败用例 | 备注 |
|---|---|---|---|---|
| 2026-08-09 | Agent | TC-1.1, TC-1.2, TC-2.1, TC-3.1, TC-3.2, TC-3.3, TC-4.1, TC-5.2, TC-6.1, TC-7.3 | TC-4.2, TC-4.3, TC-5.1, TC-5.3 | 本地 Docker Compose 后端/前端均构建并启动；修复 indexer.py Path 类型、repo_sync.py 并发锁、repos.py BackgroundTasks→asyncio.create_task、fetch 失败回退本地、symbol_flow_label upsert 后，main 分支全量索引成功完成；业务分支 diff 索引因本地未配置业务分支且 GitHub 网络受限仍待补测。 |
| 2026-08-09 | Agent | 新增接口：GET /api/repos/branches/preview（远程分支+默认分支预览）、GET /api/repos/{id}/branches（可查询分支）；修复 /api/search meta.branch_fallback 硬编码 false（实测未索引分支返回 branch_fallback=true）；前端创建仓库弹窗 git URL 自动识别默认分支+业务分支勾选（最多2个）；Benchmark 主分支锁定=默认分支+副分支下拉对比+结果分支切换 | - | 构建通过（tsc 无错误）；`GET /api/repos/branches/preview?git_url=https://github.com/ilyuve/code-pop.git` 返回 4 个远程分支与 default_branch=main。 |
| 2026-08-09 | Agent | TC-4.2（⚠️全量实现）、TC-4.3、TC-5.1；前端 UI 全流程：仓库卡片默认分支+业务分支双标签、配置业务分支弹窗自动获取远程分支（feature/codepop-test 已勾选）、创建仓库弹窗 Gitee URL 自动识别默认分支 master+业务分支勾选、Benchmark 主分支锁定（🔒 master 不可修改）+副分支下拉（master/feature/codepop-test）、搜索页结果正常 | - | Gitee fork 仓库（lynnono/springboot-vue-demo）全链路验证：fork→建 feature/codepop-test 分支→新增 TestController.java→push→CodePop 建仓库（active_branches 自动识别）→master+业务分支同步→分支查询命中 TestController（is_override=true）→master 查询不含。遗留：TC-5.3（分支删除文件）未验证；业务分支 diff 索引待实现（当前全量）。 |
| 2026-08-09 | Agent | TC-5.3 分支删除文件语义：git rm UserController.java→push→同步后 branch_deleted_files 正确记录、业务分支查询不含该文件、master 查询仍命中 | - | 发现并解决 PG advisory lock 残留 bug：连接池连接归还时锁未释放，导致后续同步被 pg_try_advisory_lock 拦截（"sync already in progress, skip"），通过 pg_terminate_backend 终止残留连接后恢复正常。后续建议改用 Redis SET NX 或专用连接释放锁。 |
| 2026-08-09 | Agent | TC-4.2b 真 diff 索引；Redis SET NX 锁（docker-compose 新增 redis 服务、config/requirements 加 redis、repo_sync.py 锁替换、fetch_branch 显式 refspec）；恢复 UserController 验证删除可逆 | - | ① PG advisory lock 残留改为 Redis SET NX（key=sync:lock:{repo_id}，TTL 300s，Lua compare-and-delete 释放，fail-open 降级），实测锁创建/释放/并发去重正常；② 业务分支真 diff 索引落地：只索引 A/M/R 文件，D 状态维护 branch_deleted_files（修复了删除记录被误清的 bug），查询语义正确（新增=override/删除=过滤/其余=main fallback）；③ 恢复 UserController 后 branch_deleted_files 自动清空、走 main fallback。⚠️ Docker 构建受环境网络影响（Docker Desktop HTTP 代理 http.docker.internal:3128 不可达外网 package index），已修 Dockerfile 禁用代理直连 + torch 层独立于 requirements；本地构建验证待网络恢复。 |
