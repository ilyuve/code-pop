# Codebase Intelligence Platform
## 技术架构文档 v1.0

---

## 1. 产品定位

Codebase Intelligence Platform 是面向 AI Agent 的代码专用检索基础设施。通过混合索引、智能检索与上下文压缩，为 Claude Code、Codex、Qoder 等编码 Agent 提供精准的代码上下文，降低幻觉率，提升代码理解深度。

**核心原则**：零 LLM 调用，纯工程化规则，轻量高效。

---

## 2. 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                        用户层                                │
│  Claude Code │ Codex │ Qoder │ Cursor │ VS Code │ 自研 Agent │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      接入层 (MCP / API)                      │
│  • MCP Server 协议（Claude Code 原生支持）                    │
│  • REST API / LSP 扩展                                      │
│  • Function Calling 标准接口                                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    六道工序检索引擎                           │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ │
│  │意图关联 │→│混合检索 │→│时间衰减 │→│重排序   │→│上下文补全│ │
│  │(规则)   │ │(4路召回)│ │(Git)    │ │(小模型) │ │(图遍历) │ │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘ │
│                              │                               │
│                              ▼                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ Token 控制（树剪枝 → 压缩到模型窗口）                    │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      混合索引层                              │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐           │
│  │ 向量索引     │ │ 符号索引     │ │ 图索引       │           │
│  │ (Milvus)    │ │ (内存/Redis) │ │ (内存图/Neo4j)│           │
│  └─────────────┘ └─────────────┘ └─────────────┘           │
│  ┌─────────────┐                                             │
│  │ 全文索引     │                                             │
│  │ (可选)      │                                             │
│  └─────────────┘                                             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    解析与构建层                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ Tree-sitter 解析引擎                                     │ │
│  │ • AST 提取（函数/类/变量/类型）                          │ │
│  │ • 调用链分析（import/require/call）                      │ │
│  │ • 作用域边界识别                                         │ │
│  └─────────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ Git 元数据提取                                           │ │
│  │ • 修改时间/作者/commit message                           │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                       存储层                                 │
│  代码仓库（本地/远程）│ 向量数据库 │ 图数据库 │ 缓存层         │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 核心模块详解

### 3.1 Tree-sitter 解析引擎

**职责**：将源代码文本转换为结构化数据，支撑所有上层索引。

**处理流程**：

```
源代码文件
    │
    ▼
Tree-sitter Parser（语言特定 grammar）
    │
    ▼
AST（抽象语法树）
    │
    ├──→ 符号提取器
    │       ├── 函数定义：名称、参数、返回值、位置
    │       ├── 类/接口定义：名称、继承、方法列表
    │       ├── 变量声明：名称、类型、作用域
    │       └── 类型注解：TypeScript/Python 类型信息
    │
    ├──→ 依赖分析器
    │       ├── import/require 语句解析
    │       ├── 跨文件引用映射
    │       └── 调用表达式收集（谁调用了谁）
    │
    └──→ 作用域分析器
            ├── 块级作用域边界
            ├── 变量生命周期
            └── 闭包关系
```

**支持语言**：TypeScript/JavaScript、Python、Go、Rust、Java、C/C++ 等（通过 Tree-sitter 语言绑定扩展）。

**增量更新**：监听 Git diff 或文件系统事件，仅重新解析变更文件，AST 节点增量替换。

---

### 3.2 混合索引层

#### 3.2.1 向量索引（语义检索）

| 属性 | 说明 |
|------|------|
| 存储 | Milvus / Pinecone / Weaviate |
| 向量化对象 | 函数体文本、类文档字符串、文件级摘要 |
| 嵌入模型 | 代码专用模型（如 CodeBERT、StarEncoder）或通用模型 |
| 分片策略 | 按函数/类为单位分片，非整个文件 |
| 元数据 | 文件路径、语言、符号类型、Git 时间戳 |

#### 3.2.2 符号索引（精确匹配）

| 属性 | 说明 |
|------|------|
| 存储 | 内存哈希表 + Redis 持久化 |
| 索引内容 | 符号名称 → 定义位置（文件:行号:列号） |
| 查询场景 | "跳转到 UserService.authenticate 定义" |
| 更新策略 | 增量更新，符号变更时原子替换 |

#### 3.2.3 图索引（关系检索）

| 属性 | 说明 |
|------|------|
| 存储 | 内存图结构（小型仓库）/ Neo4j（大型仓库） |
| 节点类型 | 文件、函数、类、接口、变量 |
| 边类型 | CALL（调用）、IMPORT（导入）、EXTEND（继承）、CONTAIN（包含） |
| 查询能力 | 上下游调用链、影响面分析、循环依赖检测 |

#### 3.2.4 全文索引（可选）

| 属性 | 说明 |
|------|------|
| 存储 | Elasticsearch / 轻量级分词索引 |
| 用途 | 精确字符串匹配、注释搜索、日志/错误信息检索 |
| 场景 | 用户搜索特定错误提示文本 |

---

### 3.3 六道工序检索引擎

#### 工序一：意图关联

**输入**：用户自然语言查询
**输出**：结构化检索意图

```python
# 规则匹配示例
INTENT_PATTERNS = {
    "modify": ["改成", "修改为", "重构", "迁移到"],
    "debug": ["bug", "报错", "异常", "为什么失败"],
    "understand": ["怎么实现", "原理", "流程", "架构"],
    "usage": ["怎么用", "调用", "示例", "API"]
}

# 提取实体
ENTITIES = {
    "symbol": r"[A-Z][a-zA-Z0-9_]*\.[a-zA-Z0-9_]+",  # Class.method
    "file": r"[\w/]+\.(ts|js|py|go|rs)",
    "language": ["typescript", "python", "go", "rust"]
}
```

**作用**：指导后续检索策略权重。例如 "modify" 意图下，调用链扩展深度增加，影响面分析优先。

---

#### 工序二：混合检索

**四路召回并行执行**：

```
用户查询
    │
    ├──→ 向量检索 → 语义相似 Top-20
    │       查询："OAuth 登录"
    │       召回：auth/oauth.ts, middleware/jwt.ts
    │
    ├──→ 符号检索 → 精确匹配 Top-10
    │       查询："UserService.authenticate"
    │       召回：直接定位定义位置
    │
    ├──→ 图检索 → 关系扩展 Top-15
    │       种子：已知 auth 模块
    │       召回：调用 auth 的所有路由文件
    │
    └──→ 全文检索 → 字符串匹配 Top-10（可选）
            查询："OAuth2"
            召回：注释/文档中含该关键词
```

**合并策略**：去重后取并集，默认上限 50 个候选。

---

#### 工序三：时间衰减

**公式**：

```
score_time = base_score × exp(-λ × days_since_last_commit)

λ = 0.1  # 衰减系数，可调
```

**规则**：
- 7 天内修改：权重 × 1.2
- 30 天内修改：权重 × 1.0
- 90 天内修改：权重 × 0.8
- 超过 180 天：权重 × 0.5
- 已删除文件：直接过滤

---

#### 工序四：重排序

**模型**：Cross-Encoder（轻量级，~100MB，CPU 可跑）

**输入**：用户查询 + 候选代码块
**输出**：相关性分数 0-1

**训练数据**：
- 正例：用户查询与正确代码块的配对
- 负例：随机采样不相关代码块
- 来源：历史查询日志、人工标注

**特征融合**：
```
final_score = 0.6 × cross_encoder_score
            + 0.2 × time_decay_score
            + 0.1 × symbol_exact_match
            + 0.1 × call_chain_proximity
```

**输出**：精排 Top-20 候选。

---

#### 工序五：上下文补全

**目标**：把碎片代码补成完整逻辑链。

**策略**：

| 场景 | 补全动作 |
|------|---------|
| 只命中函数签名 | 自动补全函数体实现 |
| 命中函数但未命中其调用 | 补全上下游调用点（各 1-2 层） |
| 命中接口定义 | 补全所有实现类 |
| 命中变量使用 | 补全变量定义和类型 |

**图遍历算法**：

```python
def complete_context(seed_symbols, max_depth=2, max_nodes=30):
    graph = load_call_graph()
    visited = set()
    queue = [(sym, 0) for sym in seed_symbols]
    result = []

    while queue and len(visited) < max_nodes:
        symbol, depth = queue.pop(0)
        if symbol in visited or depth > max_depth:
            continue
        visited.add(symbol)
        result.append(symbol)

        # 向上游扩展：谁调用了这个符号
        for caller in graph.callers(symbol):
            queue.append((caller, depth + 1))

        # 向下游扩展：这个符号调用了谁
        for callee in graph.callees(symbol):
            queue.append((callee, depth + 1))

    return result
```

---

#### 工序六：Token 控制

**目标**：将补全后的上下文压缩到模型窗口限制内（如 8K / 32K / 128K）。

**压缩策略**：

| 优先级 | 保留内容 | 压缩方式 |
|--------|---------|---------|
| P0 | 核心命中函数完整实现 | 完整保留 |
| P1 | 直接调用链上下游 | 保留签名 + 关键行注释 |
| P2 | 间接调用（2层以上） | 仅保留签名 + 注释说明 |
| P3 | 类型定义/接口 | 保留签名，实现折叠为 `// implementation...` |
| P4 | 测试文件/文档 | 仅保留文件名引用 |

**树剪枝算法**：

```python
def compress_context(symbols, token_limit):
    # 按优先级排序
    sorted_symbols = sort_by_priority(symbols)

    total_tokens = 0
    compressed = []

    for sym in sorted_symbols:
        tokens = estimate_tokens(sym)
        if total_tokens + tokens <= token_limit:
            compressed.append(sym.full_code)
            total_tokens += tokens
        elif total_tokens + sym.signature_tokens <= token_limit:
            compressed.append(sym.signature + " // ...")
            total_tokens += sym.signature_tokens
        else:
            break

    return compressed
```

---

## 4. 接入层设计

### 4.1 MCP Server 协议（推荐）

```json
{
  "name": "codebase-intelligence",
  "version": "1.0.0",
  "tools": [
    {
      "name": "search_code",
      "description": "基于语义和调用链搜索代码",
      "input_schema": {
        "type": "object",
        "properties": {
          "query": {"type": "string", "description": "用户查询"},
          "language": {"type": "string", "enum": ["typescript", "python", "go", "rust"]},
          "repo": {"type": "string", "description": "仓库标识"},
          "max_tokens": {"type": "integer", "default": 8000},
          "include_tests": {"type": "boolean", "default": false}
        },
        "required": ["query"]
      }
    },
    {
      "name": "get_impact_analysis",
      "description": "分析修改某符号的影响面",
      "input_schema": {
        "type": "object",
        "properties": {
          "symbol": {"type": "string", "description": "符号路径，如 src/auth.ts:UserService.authenticate"},
          "change_type": {"type": "string", "enum": ["signature_change", "delete", "rename"]}
        },
        "required": ["symbol", "change_type"]
      }
    },
    {
      "name": "get_symbol_definition",
      "description": "精确跳转到符号定义",
      "input_schema": {
        "type": "object",
        "properties": {
          "symbol_name": {"type": "string"}
        },
        "required": ["symbol_name"]
      }
    }
  ]
}
```

**Claude Code 配置**：

```bash
claude config add mcp-server codebase-intelligence npx @codebase/mcp-server
```

---

### 4.2 REST API

```
POST /api/v1/search
Content-Type: application/json

{
  "query": "OAuth 2.0 login",
  "repo": "company/backend",
  "language": "typescript",
  "max_tokens": 8000,
  "options": {
    "include_call_chain": true,
    "time_decay": true,
    "include_tests": false
  }
}
```

**响应**：

```json
{
  "context": "压缩后的代码文本...",
  "sources": [
    {"file": "src/auth/oauth.ts", "lines": "45-78", "symbol": "OAuthService.login"},
    {"file": "src/middleware/jwt.ts", "lines": "12-34", "symbol": "verifyToken"}
  ],
  "impact": {
    "callers": ["src/routes/user.ts:handleLogin", "src/routes/admin.ts:handleAdminLogin"],
    "tests": ["tests/auth.test.ts:OAuthLoginTest"]
  },
  "metadata": {
    "total_candidates": 47,
    "retained_symbols": 5,
    "estimated_tokens": 6123,
    "latency_ms": 230
  }
}
```

---

## 5. 用户操作流程

### 5.1 初始化（一次）

```bash
# 安装 CLI
npm install -g codebase-cli

# 初始化索引
codebase index ./my-project   --languages typescript,python   --vector-store milvus://localhost:19530   --graph-store neo4j://localhost:7687

# 输出：
# [1/4] Scanning 1,247 files...
# [2/4] Parsing AST with Tree-sitter...
# [3/4] Building hybrid index (vector + symbol + graph)...
# [4/4] Syncing Git metadata...
# ✓ Index complete: 3,421 symbols, 1,847 call relations, 12.4MB
```

### 5.2 启动服务

```bash
codebase serve --port 8080 --mcp --api

# 输出：
# ✓ MCP Server: mcp://localhost:8080/mcp
# ✓ REST API: http://localhost:8080/api/v1
# ✓ WebSocket: ws://localhost:8080/ws (real-time sync)
```

### 5.3 配置 Agent

**Claude Code**：
```bash
claude config add mcp-server codebase http://localhost:8080/mcp
```

**Cursor**（settings.json）：
```json
{
  "mcpServers": {
    "codebase": {
      "url": "http://localhost:8080/mcp"
    }
  }
}
```

### 5.4 日常使用

```
用户：@codebase 把这个登录接口改成支持 OAuth 2.0

Agent 内部：
  1. 解析意图 → modify + OAuth + login
  2. 调用 codebase.search_code()
  3. 六道工序执行（230ms）
  4. 返回压缩上下文（6,123 tokens）
  5. LLM 生成修改方案

用户看到：
  相关代码：
  • src/auth/oauth.ts:45-78 OAuthService.login
  • src/middleware/jwt.ts:12-34 verifyToken

  影响面：
  • src/routes/user.ts 调用此接口
  • tests/auth.test.ts 需同步修改

  [生成修改方案...]
```

---

## 6. 增量同步机制

### 6.1 触发方式

| 方式 | 适用场景 | 延迟 |
|------|---------|------|
| Git Webhook | 团队仓库，push 触发 | < 5s |
| 文件系统监听 | 本地开发，save 触发 | < 1s |
| 定时轮询 | 无 Git 场景 | 5min |
| 手动触发 | `codebase sync` 命令 | 即时 |

### 6.2 增量处理流程

```
Git diff / 文件变更事件
    │
    ▼
┌─────────────────┐
│ 变更文件筛选     │  → 过滤 .gitignore / 二进制 / 未变更
└─────────────────┘
    │
    ▼
┌─────────────────┐
│ Tree-sitter 增量解析│  → 只解析变更文件，复用未变更 AST 节点
└─────────────────┘
    │
    ▼
┌─────────────────┐
│ 索引原子更新     │  → 向量：删除旧向量 + 插入新向量
│                 │  → 符号：哈希表 CAS 替换
│                 │  → 图：事务级边增删
└─────────────────┘
    │
    ▼
┌─────────────────┐
│ 缓存失效        │  → 相关查询结果缓存标记失效
└─────────────────┘
```

---

## 7. 性能指标

| 指标 | 目标值 | 说明 |
|------|--------|------|
| 索引构建速度 | 1000 文件/分钟 | 含解析 + 向量化 + 建图 |
| 查询延迟 | P95 < 300ms | 六道工序完整执行 |
| 增量同步延迟 | < 3s | 单文件变更 |
| 内存占用 | < 2GB / 10K 文件 | 含 AST + 索引 + 图 |
| Token 压缩率 | 70-90% | 原始代码 → 压缩后上下文 |
| 检索准确率 | Top-5 命中率 > 85% | 人工评估 |

---

## 8. 部署模式

### 8.1 本地开发模式

```
开发者笔记本
├── codebase-cli（索引 + 服务）
├── Milvus Lite（本地向量库）
├── 内存图结构（无需外部依赖）
└── Claude Code（本地 MCP）
```

### 8.2 团队 SaaS 模式

```
代码仓库 ──→ Webhook ──→ codebase-cloud
                              ├── 多租户索引隔离
                              ├── 共享向量库集群
                              └── 企业级 API
```

### 8.3 企业私有化模式

```
企业内部服务器
├── codebase-enterprise
├── 自托管 Milvus / Neo4j
├── LDAP/SSO 集成
└── 审计日志与合规
```

---

## 9. 与竞品对比

| 维度 | Sourcegraph Cody | Cursor @codebase | 本产品 |
|------|-----------------|------------------|--------|
| 定位 | 代码搜索 + AI | IDE 内置功能 | AI Infra（中立） |
| 模型绑定 | 部分绑定 | 绑定 Copilot | 模型无关 |
| 索引深度 | 深（企业级） | 深（IDE 集成） | 深（可定制） |
| 私有化 | 支持（贵） | 不支持 | 支持（轻量） |
| 多语言 | 主流语言 | 主流语言 | 可扩展 |
| 上下文压缩 | 中等 | 强 | 强（六道工序） |
| 影响面分析 | 有 | 有限 | 有（图遍历） |
| 接入成本 | 高 | 低（内置） | 低（MCP/API） |

---

## 10. 演进路线

| 阶段 | 版本 | 目标 |
|------|------|------|
| MVP | v0.1 | TypeScript/Python 支持，本地 CLI，MCP 接入 |
| 扩展 | v0.5 | 5+ 语言，团队 SaaS，增量同步 |
| 企业 | v1.0 | 私有化部署，权限控制，审计日志 |
| 智能 | v2.0 | 自学习重排序（用户反馈闭环），跨仓库检索 |
| 生态 | v3.0 | 插件市场（自定义解析器、自定义规则），开源核心 |

---

## 附录：术语表

| 术语 | 说明 |
|------|------|
| AST | 抽象语法树，代码的结构化表示 |
| MCP | Model Context Protocol，Anthropic 提出的 Agent 工具标准 |
| Cross-Encoder | 双塔模型，用于精确排序查询-文档对 |
| Token | 大模型处理文本的最小单位，约 0.75 个汉字或 1 个英文单词 |
| RAG | Retrieval-Augmented Generation，检索增强生成 |
| LSP | Language Server Protocol，编辑器与语言服务通信标准 |

---

*文档版本：v1.0*
*最后更新：2026-06-19*
*作者：Codebase Intelligence Team*
