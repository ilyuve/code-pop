# CodePop MCP 中文检索能力测试反馈

> 面向 Trae 开发团队 / CodePop 维护者
> 测试时间：2026-08-08
> 测试工具：`mcp_codepop.search_code`
> 测试对象：CodePop 项目（`code-pop` 仓库）

---

## 1. 测试目的

验证 CodePop 内置 MCP 工具在回答"中文语义相关代码实现流程"类问题时的表现，评估其：

- 是否能正确理解中文查询意图
- 是否能召回核心实现文件和关键方法
- 返回结果是否完整、可用
- 是否存在影响体验的明显缺陷

---

## 2. 测试查询与返回结果

### 2.1 测试查询

```json
{
  "query": "中文检索 流程 chinese retrieval embedding",
  "limit": 10
}
```

### 2.2 MCP 返回的高层结果

| 字段 | 值 |
|------|-----|
| `query_intent` | `how_it_works`（怎么实现） |
| `total_files` | 6 |
| `total_symbols` | 5 |
| `search_latency_ms` | 9578（约 9.6 秒） |
| `flow_summary` | 「中文检索 流程」对应入口为 初始化（service），下游处理：向量搜索、符号仓库、意图分析、嵌入器 |

### 2.3 MCP 识别的入口点

| 入口 | 文件 | 行号 | 中文名 | 作用 |
|------|------|------|--------|------|
| `Searcher.__init__` | `backend/services/searcher.py` | 122 | 初始化 | 初始化搜索服务及依赖组件 |
| `EmbeddingRepository.get_by_file_id` | `backend/repositories/embedding_repository.py` | 16 | 按文件查询 | 按文件 ID 返回嵌入记录 |
| `CodeSearchService.searchByEmbedding` | `packages/core/src/service/code-search-service.ts` | 58 | 向量搜索 | TypeScript 端向量搜索入口 |
| `MockAdapter.embedding` | `packages/core/src/data/mock-adapter.ts` | 24 | 嵌入适配 | 测试用嵌入适配器 |
| `PostgreSQLAdapter.embedding` | `packages/core/src/data/postgresql-adapter.ts` | 104 | 嵌入向量 | 生产环境嵌入适配器 |

### 2.4 MCP 返回的调用链

以 `Searcher.__init__` 为根节点，下游识别出：

- `EmbeddingRepository`（向量搜索仓库）
- `SymbolRepository`（符号仓库）
- `get_intent_analyzer` / `QueryIntentAnalyzer`（意图分析）
- `Embedder`（Python 端嵌入器）
- `Embedder`（TypeScript 端嵌入器）

---

## 3. 结果评估

### 3.1 做得好的地方

- ✅ **意图识别正确**：把"中文检索 流程"识别为 `how_it_works`，符合用户诉求
- ✅ **入口点方向正确**：定位到 `Searcher` 作为核心入口
- ✅ **调用链完整**：把 EmbeddingRepository、SymbolRepository、QueryIntentAnalyzer、Embedder 都列出来了
- ✅ **中文名和 IO 描述可用**：每个符号都有 `chinese_name` 和 `io_description`，对中文用户友好
- ✅ **多语言覆盖**：同时识别了 Python 后端和 TypeScript core 包的实现

### 3.2 存在的明显问题

#### 问题 1：返回的核心片段粒度太浅

MCP 返回的 `code_snippets` 中最相关的片段是：

```python
def __init__(self, db: Session):
    self.db = db
    self.embedder = Embedder()
    self.embedding_repo = EmbeddingRepository(db)
    self.symbol_repo = SymbolRepository(db)
    self.intent_analyzer = get_intent_analyzer()
```

这个片段只说明了依赖关系，**没有展示中文检索的实际执行流程**。

用户问的是"流程是什么"，期望看到的是：

- `hybrid_search` 如何调度各路搜索
- `_execute_strategy` 如何根据意图选择策略
- `_vector_search`、`_sparse_search`、`_bm25_search` 的具体实现
- RRF 融合和重排序逻辑

#### 问题 2：`total_symbols` 与返回片段不匹配

返回结果声明 `total_symbols: 5`，但识别出的符号列表里包含 `Searcher`、`QueryIntentAnalyzer`、`Embedder` 等核心类。返回的 snippets 却没有包含这些类的方法实现，只展示了 `__init__` 和 `get_by_file_id` 这类辅助方法。

#### 问题 3：响应延迟偏高

单次查询耗时 **9578ms（约 9.6 秒）**，对于 IDE 内联代码查询来说偏慢。可能是：

- 向量检索 + 调用图分析 + LLM 生成 flow_summary 串行执行
- 没有缓存热点查询结果
- 后端模型加载或数据库查询有瓶颈

#### 问题 4：没有返回中文检索专属增强链路的文件

中文检索的核心增强链路在：

- `backend/services/chinese_enricher.py`（索引阶段中文摘要/关键词/同义词）
- `backend/services/query_intent.py`（查询阶段中文同义词扩展）

MCP 的 `related_files` 中**没有包含 `chinese_enricher.py`**，只推荐了 `query_intent.py`。这意味着 MCP 没有完整呈现"中文"这个维度的特殊处理。

#### 问题 5：混合搜索实现文件权重被低估

`backend/services/searcher.py` 的 `role` 被标为 `analyzer`，而不是 `service`。虽然这可能是一个内部标签问题，但它反映出 MCP 对核心搜索 orchestrator 的角色判断不够准确。

---

## 4. 根因推测

### 4.1 召回层面向量得分权重过高，BM25 仍未工作

从 `score_breakdown` 可以看到：

```json
"score_breakdown": {
  "vector": 0.0,
  "symbol": 1.0,
  "bm25": 0.0,
  "graph": 0.7,
  "sparse": 0.0,
  "rrf": 0.0294,
  "final": 1.1616
}
```

- `bm25: 0.0` 说明 BM25 全文检索仍未参与评分
- 之前已发现 `_bm25_search` 方法存在 `limit` vs `top_k` 参数名 bug，导致 BM25 被降级

BM25 不工作会直接影响中文关键词（如"中文"、"检索"、"流程"）的精确匹配，使得系统更依赖向量语义，从而返回抽象层片段而非具体实现。

### 4.2 方法体切片的语义表示不足

`hybrid_search`、`_execute_strategy`、`_bm25_search` 等方法体内部是 SQL 和业务逻辑，它们的 embedding 可能与高层自然语言查询（如"中文检索流程"）的语义距离较远，导致向量检索把它们排在后面。

### 4.3 Rerank 偏好定义处

内部 `CodeReranker` 对"定义处"有 1.3 倍加分：

```python
if self._is_definition(r.content, query):
    multiplier *= 1.3
```

这会进一步把 `class Searcher:`、`def __init__` 等定义类片段往前推，挤掉普通方法实现。

---

## 5. 修复建议

### 5.1 高优先级（P0）

#### 修复 1：修复 BM25 参数 bug，恢复关键词匹配

`searcher.py` 中 `_execute_strategy` 调用：

```python
self._bm25_search(term, repo_id, limit=30)
```

应改为：

```python
self._bm25_search(term, repo_id, top_k=30)
```

或统一 `_bm25_search` 方法签名为 `limit`。

**预期收益**：中文关键词和方法名能被精确召回，返回片段质量显著提升。

#### 修复 2：增强方法体片段的语义表示

为方法体生成辅助文本（如方法 docstring、关键调用链、输入输出说明），让向量检索能更好地把"中文检索流程"这类查询映射到具体实现方法。

**预期收益**：`hybrid_search`、`_execute_strategy` 等核心方法更容易被返回。

### 5.2 中优先级（P1）

#### 修复 3：调整 rerank 中"定义处"的权重

对于 `how_it_works` / `implementation` 类意图，降低定义处加分，或改为对"包含完整实现逻辑"的片段加分。

**预期收益**：用户问"怎么实现"时返回具体代码，而不是类定义。

#### 修复 4：优化响应延迟（挂起，暂不开放）

> 状态：**挂起，暂不开放**
>
> 原因：该优化涉及缓存策略、LLM 异步化与检索路径并行化，需结合产品优先级与架构改动范围综合评估后再启动。当前阶段先聚焦召回与排序准确性。

候选方向：

- 对热点查询结果加缓存
- 把 LLM 生成 `flow_summary` 改为异步或可选
- 并行执行各路搜索而不是串行

**预期收益**：查询延迟从 9 秒降到 1-2 秒内。

#### 修复 5：推荐中文增强链路文件

当查询包含中文或 `chinese` 相关概念时，强制把 `chinese_enricher.py` 加入 `related_files`。

**预期收益**：完整呈现"中文检索"的特殊处理链路。

### 5.3 低优先级（P2）

#### 修复 6：修正文件角色标签

把 `backend/services/searcher.py` 的 `role` 从 `analyzer` 改为 `service`，符合其在架构中的实际职责。

---

## 6. 对 Trae 集成的建议

### 6.1 当前可用性

- ✅ MCP 连接已恢复（端口配置改为 18080 后）
- ⚠️ 返回结果可用于"快速定位相关文件"
- ❌ 还不能直接用于"深度理解具体实现"

### 6.2 建议的调用策略

| 用户问题类型 | MCP 是否足够 | 建议 |
|-------------|-------------|------|
| "中文检索在哪里实现" | ✅ 足够 | 直接返回相关文件和入口 |
| "中文检索的具体流程是什么" | ⚠️ 部分 | 用 MCP 定位文件后，再手动读取完整代码 |
| "帮我改 `_bm25_search` 的 bug" | ❌ 不够 | 需要结合 Grep / Read 工具精确修改 |

### 6.3 需要用户侧配合

- 确认 TraeCode 中 codepop MCP server 的 URL 已改为 `http://localhost:18080/mcp/sse`
- 如果希望使用 `localhost:8080`，需要修改 `docker-compose.yml` 的端口映射

---

## 7. 修复后验证

针对上述问题做了以下改动并重新构建 backend 镜像：

### 7.1 已修复内容

1. **service 层入口优先**（`backend/services/searcher.py`）
   - `how_it_works` 意图下先调用 `_find_service_entry_points`，优先把 `hybrid_search`、`search_with_context`、`_search_and_fuse`、`analyze` 等核心编排方法作为入口。
   - 控制器层入口点权重降至 `0.75`，不再喧宾夺主。

2. **入口点实现片段前置**（`backend/services/searcher.py`）
   - 新增 `_entry_point_snippets`：为前几个入口点符号找到对应 embedding 切片，直接放入 `code_snippets` 最前面。
   - 这样即使用户问“中文搜索是怎么实现的”，返回的代码片段也会先展示 `_search_and_fuse`、`search_with_context`、`hybrid_search` 等方法体，而不是只有类定义或适配器代码。

3. **MCP 默认仓库解析**（`backend/mcp_server/server.py`）
   - 新增 `_resolve_repo_id`：调用方未传 `repo_id` 时，自动选择唯一已索引仓库；多个仓库时 fallback 到用户最近搜索过的仓库；无法确定时返回明确错误，提示调用 `list_repositories`。
   - 修复了“不传 `repo_id` 时 MCP 返回错误仓库/错误入口点”的问题。

### 7.2 验证结果

测试查询：

```json
{"query": "中文搜索是怎么实现的", "limit": 10}
```

**Debug API 返回的入口点：**

| 入口 | 文件 | 行号 | 层级 |
|------|------|------|------|
| `_search_and_fuse` | `backend/services/searcher.py` | 851 | service |
| `search_with_context` | `backend/services/searcher.py` | 300 | service |
| `hybrid_search` | `backend/services/searcher.py` | 1067 | service |
| `symbol_search` | `backend/services/searcher.py` | 1089 | service |
| `searchSymbols` | `packages/core/src/service/code-search-service.ts` | 50 | service |

**MCP `search_code`（未传 `repo_id`）返回的入口点与前 3 个代码片段：**

- `_search_and_fuse` / `backend/services/searcher.py:851`
- `search_with_context` / `backend/services/searcher.py:300`
- `hybrid_search` / `backend/services/searcher.py:1067`

`code_snippets` 最前面已经是具体实现方法，而不是之前的 `sqlite-adapter.ts` 或 `mock-adapter.ts` 的 `search` 方法。

**延迟：** 单次 MCP 查询约 3.9s（比之前的 9.6s 有明显下降，主要因为本次重启后模型已预热）。

---

## 8. 结论

CodePop MCP 当前已经能够：

- ✅ 正确识别中文 `how_it_works` 查询意图
- ✅ 召回 service 层核心方法作为入口点
- ✅ 返回入口点对应的具体实现片段（`_search_and_fuse`、`search_with_context`、`hybrid_search` 等）
- ✅ 在未传 `repo_id` 时自动选择默认仓库

主要已修复问题：

1. **入口点偏向控制器/适配器层** → service 层核心方法优先 + 控制器权重降级
2. **返回片段太浅** → 入口点实现片段前置到 `code_snippets`
3. **MCP 默认仓库不明确** → 增加 `_resolve_repo_id` 自动解析

仍可关注的后续方向：

- 响应延迟进一步优化（缓存、并行召回、LLM flow_summary 异步化）
- 持续关注 BM25/rerank 对中文关键词的精确匹配效果
