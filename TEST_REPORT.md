# CodePop 中文语义检索功能测试报告

## 1. 测试概览

| 项目 | 内容 |
|------|------|
| 测试分支 | `feature/chinese-llm-retrieval` |
| 测试时间 | 2026-07-30 |
| 测试范围 | 中文同义词检索、索引取消、时区显示、删除仓库、强制重新索引、状态恢复 |
| 测试方式 | Python 单元 / 集成测试（mock + 本地文件） |
| 测试环境 | Linux 远程沙箱（无 Docker / PostgreSQL） |

## 2. 执行结果

### 2.1 后端全量测试

```bash
cd backend
python -m pytest tests/ -v --tb=short
```

**结果：98 passed, 0 failed, 23 warnings**

### 2.2 本次新增 / 重点覆盖的测试

| 测试文件 | 测试类 | 覆盖功能 |
|----------|--------|----------|
| `tests/test_chinese_retrieval_integration.py` | `TestTimezoneAwareResponse` | UTC 时间序列化带 `+00:00`，前端可自动转本地时区 |
| `tests/test_chinese_retrieval_integration.py` | `TestLLMRouterUsageLogSessionIsolation` | LLM 使用日志写入独立 Session，不破坏索引事务 |
| `tests/test_chinese_retrieval_integration.py` | `TestCancelIndexing` | 取消索引事件设置与 `_check_cancelled` 抛出异常 |
| `tests/test_chinese_retrieval_integration.py` | `TestChineseSynonymExpansion` | 中文同义词扩展生成查询变体 |
| `tests/test_chinese_retrieval_integration.py` | `TestSearcherUsesExpandedTerms` | Searcher 接收到扩展词，BM25 使用参数化查询 |
| `tests/test_chinese_retrieval_integration.py` | `TestDeleteRepo` | 删除仓库时取消索引并清理关联表 |
| `tests/test_chinese_retrieval_integration.py` | `TestForceReindexWhenEnrichmentMissing` | hash 命中但缺少中文增强数据时强制重新索引 |
| `tests/test_chinese_retrieval_integration.py` | `TestIndexingStateRecovery` | 服务重启后将 indexing 状态仓库重置为 pending |
| `tests/test_chinese_enricher.py` | 多个 | 中文摘要、关键词、同义词、Flow Label 解析与存储 |
| `tests/test_llm_router.py` | 多个 | 多 Provider 路由、降级、回退 |
| `tests/test_searcher.py` | 多个 | BM25 查询包含中文增强字段、同义词扩展、调用链标签 |

## 3. 已修复问题确认

| 问题 | 修复位置 | 验证方式 |
|------|----------|----------|
| 时区显示错误 | `backend/main.py` `_TimezoneAwareJSONResponse` | `TestTimezoneAwareResponse` |
| `aggregate_domain_synonyms` 内部自行 commit | `backend/services/chinese_enricher.py` 移除 `db.commit()` | 代码审查 + 调用链检查 |
| 取消索引按钮无效 | `backend/services/indexer.py` `_indexing_cancel_events` + `_check_cancelled` | `TestCancelIndexing` |
| 删除仓库无响应 | `backend/api/repos.py` `delete_repo` | `TestDeleteRepo` |
| 强制重新索引不强制 | `backend/services/indexer.py` `_index_file` | `TestForceReindexWhenEnrichmentMissing` |
| 重启后索引状态不恢复 | `backend/main.py` `_recover_indexing_repos` | `TestIndexingStateRecovery` |
| LLM 日志破坏索引事务 | `backend/services/llm_router.py` `_write_usage_log` 独立 Session | `TestLLMRouterUsageLogSessionIsolation` |

## 4. 环境限制说明

当前远程沙箱环境无法启动完整服务，原因如下：

- 无 `docker` / `docker-compose` / `podman` 命令
- 无 PostgreSQL 二进制文件（`pg_ctl` / `initdb` / `postgres` / `psql` 均不存在）
- `apt-get install postgresql` 因网络超时失败
- pip 可安装 Python 包，但无法安装 PostgreSQL 服务端二进制

因此以下步骤**未能在本环境实际执行**：

1. `docker compose up` 启动 backend / web / postgres
2. 在 UI 配置 DeepSeek key（`sk-fa8584ed4b8d46f8838f9929370e207c`）
3. 添加并索引 `https://github.com/ilyuve/code-pop`
4. 端到端验证中文同义词搜索

## 5. 在本地/服务器环境跑通主流程的步骤

在有 Docker 的环境（如 macOS、Linux 桌面、云服务器）执行：

```bash
# 1. 切到分支
git checkout feature/chinese-llm-retrieval
git pull origin feature/chinese-llm-retrieval

# 2. 启动服务（本地构建）
docker compose -f docker-compose.yml -f docker-compose.override.yml up -d --build

# 3. 初始化数据库表（首次启动）
docker compose exec backend python scripts/ensure_database.py

# 4. 打开前端 http://localhost:3000
#    进入 Settings -> LLM Providers，添加 DeepSeek：
#    - Base URL: https://api.deepseek.com/v1
#    - API Key: sk-fa8584ed4b8d46f8838f9929370e207c
#    - Model: deepseek-chat
#    - Capability: chat
#    - 填写输入/输出成本后保存并测试连接

# 5. 添加仓库
#    Repos -> Add Repository
#    - Name: code-pop
#    - Git URL: https://github.com/ilyuve/code-pop
#    保存后自动触发索引

# 6. 验证搜索
#    在搜索框输入：骑士配送流程
#    应返回包含“骑手配送流程”相关代码的结果
```

## 6. 仍需关注的风险

1. **同义词扩展只做单 term 替换**：当前 `expand_query_with_synonyms` 一次只替换一个中文术语，不会生成“骑手送货流程”这类组合变体。若业务需要组合扩展，需改为笛卡尔积生成。
2. **中文增强依赖 LLM Provider 配置**：未配置 DeepSeek 时，索引会跳过 enrichment，导致同义词表为空、BM25 只能命中原始词。
3. **`_enrich_repository` 后无显式 commit**：`aggregate_domain_synonyms` 和 Flow Label 的写入随后续 `_rebuild_call_graph` 的 `db.commit()` 一起落盘。若调用图阶段失败，domain_synonyms 数据会回滚丢失。
4. **Docker 镜像拉取/构建**：`ghcr.io/ilyuve/codepop-postgres:pg16` 和 `ghcr.io/ilyuve/codepop-backend:latest` 需要能访问 GitHub Container Registry。

## 7. 结论

- 本次提交的分支代码已通过全部 98 个自动化测试。
- 时区、调用方统一提交、取消索引等三项修复已落地并验证。
- 由于当前沙箱环境缺少 Docker 与 PostgreSQL，端到端主流程未能实际运行，需在具备容器环境后继续验证。
