# CodePop PostgreSQL + pgvector 技术方案

## 1. 选型理由

| 维度 | PostgreSQL + pgvector | Milvus | Pinecone |
|------|----------------------|--------|----------|
| 部署复杂度 | 低（单节点或 Docker） | 高（多组件） | SaaS 依赖 |
| 运维成本 | 低（DB 团队可维护） | 高（专业向量运维） | 无（托管） |
| 成本 | 开源免费 | 开源免费 | 按容量收费 |
| 事务支持 | 原生 ACID | 有限 | 无 |
| 混合查询 | 向量+标量一键搞定 | 需额外组件 | 有限 |
| 生态集成 | 现有 DB 工具直接用 | 独立系统 | 独立系统 |
| 适合场景 | 中小规模（<1000万向量） | 超大规模 | 纯向量检索 |

**结论**：PostgreSQL + pgvector 非常适合 CodePop 的定位——面向开发者/团队的轻量级解决方案，开箱即用，降低部署和运维门槛。

---

## 2. 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                        Agent CLI 层                          │
│  Claude Code │ Codex │ Cursor │ VS Code │ 自研 Agent         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      接入层 (MCP / REST)                     │
│  • MCP Server（原生支持 Claude Code）                       │
│  • REST API（兼容 OpenAI 格式）                              │
│  • WebSocket（实时同步）                                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      检索服务层                              │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐         │
│  │ 意图理解     │ │ 混合检索     │ │ 上下文补全   │         │
│  │ (规则引擎)   │ │ (向量+符号)  │ │ (图遍历)    │         │
│  └─────────────┘ └─────────────┘ └─────────────┘         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      数据访问层                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │                  PostgreSQL + pgvector                   │ │
│  │  • 向量索引 (embedding)                                 │ │
│  │  • 符号索引 (symbols)                                    │ │
│  │  • 仓库元数据 (repos)                                    │ │
│  │  • 调用图关系 (call_graph)                              │ │
│  │  • Git 历史 (git_commits)                               │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      解析层                                  │
│  Tree-sitter 解析引擎（增量解析 AST）                        │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 数据库设计

### 3.1 表结构总览

```sql
-- 代码仓库管理
CREATE TABLE repos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    path TEXT NOT NULL UNIQUE,
    git_url TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    last_indexed_at TIMESTAMP,
    file_count INTEGER DEFAULT 0,
    symbol_count INTEGER DEFAULT 0
);

-- 文件索引
CREATE TABLE files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    language VARCHAR(50),
    content_hash VARCHAR(64),
    size_bytes INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    git_modified_at TIMESTAMP,
    git_author TEXT,
    git_commit_msg TEXT,
    UNIQUE(repo_id, path)
);

-- 符号索引（函数、类、变量等）
CREATE TABLE symbols (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_id UUID REFERENCES files(id) ON DELETE CASCADE,
    repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    kind VARCHAR(50) NOT NULL,  -- function, class, method, variable, interface
    visibility VARCHAR(20) DEFAULT 'public',  -- public, private, protected
    signature TEXT,
    qualified_name TEXT NOT NULL,  -- repo:file:symbol 或 ClassName.methodName
    start_line INTEGER,
    end_line INTEGER,
    docstring TEXT,
    return_type TEXT,
    parameters JSONB,
    is_async BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(repo_id, qualified_name)
);

-- 符号向量嵌入（pgvector）
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE symbol_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol_id UUID REFERENCES symbols(id) ON DELETE CASCADE,
    repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
    embedding VECTOR(1536),  -- OpenAI text-embedding-3-small 维度
    chunk_type VARCHAR(50) DEFAULT 'symbol',  -- symbol, docstring, file_summary
    chunk_index INTEGER DEFAULT 0,
    token_count INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 调用图关系
CREATE TABLE call_relations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
    caller_id UUID REFERENCES symbols(id) ON DELETE CASCADE,
    callee_id UUID REFERENCES symbols(id) ON DELETE CASCADE,
    call_type VARCHAR(50) DEFAULT 'direct',  -- direct, interface, dynamic
    import_path TEXT,
    line_number INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(caller_id, callee_id, line_number)
);

-- Git 提交历史（用于时间衰减）
CREATE TABLE git_commits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
    commit_hash VARCHAR(64) NOT NULL,
    author VARCHAR(255),
    message TEXT,
    committed_at TIMESTAMP,
    files_changed JSONB,
    insertions INTEGER DEFAULT 0,
    deletions INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(repo_id, commit_hash)
);

-- 索引任务记录
CREATE TABLE index_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
    status VARCHAR(50) DEFAULT 'pending',  -- pending, running, completed, failed
    task_type VARCHAR(50),  -- full, incremental, single_file
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    files_processed INTEGER DEFAULT 0,
    symbols_indexed INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 用户查询日志（用于分析优化）
CREATE TABLE query_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    repo_id UUID REFERENCES repos(id) ON DELETE CASCADE,
    query_text TEXT,
    intent VARCHAR(50),
    results_count INTEGER,
    latency_ms INTEGER,
    client_info JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### 3.2 索引设计

```sql
-- 符号名精确匹配索引
CREATE INDEX idx_symbols_qualified_name ON symbols(repo_id, qualified_name);
CREATE INDEX idx_symbols_name ON symbols(repo_id, name);
CREATE INDEX idx_symbols_kind ON symbols(kind);

-- 向量相似度检索索引（HNSW，pgvector 内置）
CREATE INDEX idx_embeddings_vector_hnsw ON symbol_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- 调用图索引
CREATE INDEX idx_call_relations_caller ON call_relations(repo_id, caller_id);
CREATE INDEX idx_call_relations_callee ON call_relations(repo_id, callee_id);

-- Git 时间衰减索引
CREATE INDEX idx_files_git_modified ON files(repo_id, git_modified_at DESC);

-- 全文搜索（可选增强）
CREATE INDEX idx_symbols_docstring_gin ON symbols USING gin(to_tsvector('english', coalesce(docstring, '')));
```

### 3.3 混合检索示例

```sql
-- 示例：检索 "OAuth 登录" 相关代码，结合向量相似度、符号匹配、时间衰减
WITH vector_results AS (
    SELECT e.symbol_id, e.embedding <=> ai_embedding('OAuth login', 'text-embedding-3-small') AS similarity
    FROM symbol_embeddings e
    WHERE e.repo_id = $repo_id
    ORDER BY e.embedding <=> ai_embedding('OAuth login', 'text-embedding-3-small')
    LIMIT 50
),
time_weight AS (
    SELECT v.symbol_id,
           v.similarity * COALESCE(
               exp(-0.1 * (NOW() - f.git_modified_at) / INTERVAL '1 day'), 1.0
           ) AS weighted_score
    FROM vector_results v
    JOIN symbols s ON v.symbol_id = s.id
    JOIN files f ON s.file_id = f.id
)
SELECT s.name, s.qualified_name, s.kind, s.signature,
       f.path, s.start_line, s.end_line,
       tw.weighted_score,
       s.docstring
FROM time_weight tw
JOIN symbols s ON tw.symbol_id = s.id
JOIN files f ON s.file_id = f.id
ORDER BY tw.weighted_score DESC
LIMIT 20;
```

---

## 4. 开箱即用方案

### 4.1 Docker 一键部署

```yaml
# docker-compose.yml
version: '3.8'

services:
  codepop:
    image: codepop/codepop:latest
    ports:
      - "8080:8080"  # REST API
      - "8081:8081"  # MCP Server
    environment:
      DATABASE_URL: postgresql://postgres:password@postgres:5432/codepop
      PGVECTOR_ENABLED: "true"
    volumes:
      - ./repos:/app/repos  # 代码仓库目录
      - ./data:/app/data    # 索引数据
    depends_on:
      postgres:
        condition: service_healthy

  postgres:
    image: ankane/pgvector:pg16
    environment:
      POSTGRES_DB: codepop
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: password
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  pgdata:
```

**启动命令**：

```bash
# 一行命令启动全部服务
docker compose up -d

# 验证服务状态
docker compose ps
```

### 4.2 零配置 CLI

```bash
# 安装 CLI
curl -fsSL https://get.codepop.dev | sh

# 或者通过 npm
npm install -g @codepop/cli

# 初始化（自动检测数据库、创建表结构）
codepop init

# 索引代码仓库（自动识别语言、解析 AST）
codepop index ./my-project

# 启动服务
codepop serve

# 查看帮助
codepop --help
```

**`codepop init` 自动完成**：

```
✓ 检测到 PostgreSQL 16 + pgvector
✓ 创建数据库 codepop
✓ 创建扩展 pgvector
✓ 创建表结构（repos, files, symbols, symbol_embeddings, call_relations...）
✓ 创建索引（符号索引、HNSW 向量索引、全文索引）
✓ 生成配置文件 ~/.codepop/config.yaml
✓ 初始化完成！
```

### 4.3 自动语言检测

```bash
# 自动检测并索引所有支持的语言
codepop index ./my-project

# 输出示例：
# [1/6] 检测语言...
#        发现: TypeScript (312 files), Python (89 files), Go (45 files)
# [2/6] 解析 AST...
#        处理 446 files... [████████████████████] 100%
# [3/6] 提取符号...
#        索引 3,421 symbols (2,103 functions, 456 classes, 862 variables)
# [4/6] 生成向量嵌入...
#        使用 OpenAI text-embedding-3-small
#        处理 3,421 symbols... [████████████████████] 100%
# [5/6] 构建调用图...
#        发现 1,847 调用关系
# [6/6] 同步 Git 历史...
#        导入 234 commits
# ✓ 索引完成！耗时 45.3s
```

---

## 5. Agent CLI 适配方案

### 5.1 MCP Server（MCP 协议）

**配置**：

```bash
# Claude Code
claude config add mcp-server codepop npx @codepop/mcp-server

# Cursor
# 在 settings.json 中添加
{
  "mcpServers": {
    "codepop": {
      "command": "npx",
      "args": ["@codepop/mcp-server"]
    }
  }
}
```

**MCP 工具定义**：

```typescript
// codepop.mcp.ts
export const codepopTools = {
  search_code: {
    name: "search_code",
    description: "基于语义和调用链搜索代码，返回压缩后的上下文",
    inputSchema: {
      type: "object",
      properties: {
        query: { type: "string", description: "自然语言查询" },
        repo: { type: "string", description: "仓库路径或名称" },
        language: { type: "string", enum: ["typescript", "python", "go", "rust", "java"] },
        maxTokens: { type: "integer", default: 8000 },
        includeCallChain: { type: "boolean", default: true },
        timeDecay: { type: "boolean", default: true }
      },
      required: ["query"]
    }
  },
  goto_definition: {
    name: "goto_definition",
    description: "跳转到符号定义位置",
    inputSchema: {
      type: "object",
      properties: {
        symbol: { type: "string", description: "符号路径，如 UserService.authenticate" },
        repo: { type: "string" }
      },
      required: ["symbol"]
    }
  },
  find_references: {
    name: "find_references",
    description: "查找符号的所有引用",
    inputSchema: {
      type: "object",
      properties: {
        symbol: { type: "string" },
        repo: { type: "string" },
        includeTests: { type: "boolean", default: false }
      },
      required: ["symbol"]
    }
  },
  get_impact_analysis: {
    name: "get_impact_analysis",
    description: "分析修改符号的影响面",
    inputSchema: {
      type: "object",
      properties: {
        symbol: { type: "string" },
        repo: { type: "string" },
        changeType: { type: "string", enum: ["signature", "delete", "rename"] }
      },
      required: ["symbol"]
    }
  }
};
```

### 5.2 REST API（OpenAI 兼容格式）

```bash
# 搜索代码（类 OpenAI Assistants API）
curl -X POST http://localhost:8080/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "OAuth 登录流程",
    "repo": "./my-project",
    "max_tokens": 8000
  }'

# 响应
{
  "context": "async function OAuthService.login(code: string): Promise<User> {\n  // 验证 OAuth code...\n  const token = await this.verifyCode(code);\n  ...\n}",
  "sources": [
    {"file": "src/auth/oauth.ts", "lines": "45-78", "symbol": "OAuthService.login"},
    {"file": "src/middleware/jwt.ts", "lines": "12-34", "symbol": "verifyToken"}
  ],
  "metadata": {
    "candidates_found": 47,
    "retained_symbols": 5,
    "estimated_tokens": 6123,
    "latency_ms": 230
  }
}
```

### 5.3 多 Agent 适配矩阵

| Agent | 接入方式 | 配置难度 | 推荐指数 |
|-------|---------|---------|---------|
| Claude Code | MCP Server | ⭐ | ⭐⭐⭐⭐⭐ |
| Cursor | MCP Server | ⭐ | ⭐⭐⭐⭐⭐ |
| VS Code (Copilot) | REST API + Extension | ⭐⭐ | ⭐⭐⭐ |
| Codex / ChatGPT | REST API | ⭐ | ⭐⭐⭐⭐ |
| 自研 Agent | REST API / SDK | ⭐⭐ | ⭐⭐⭐⭐ |

### 5.4 Python SDK（自研 Agent 集成）

```python
# codepop-sdk-python
from codepop import CodePopClient

client = CodePopClient(base_url="http://localhost:8080")

# 搜索代码上下文
result = client.search(
    query="OAuth 登录流程",
    repo="./my-project",
    max_tokens=8000
)

print(result.context)
print(result.sources)

# 查找符号定义
definition = client.goto_definition("UserService.authenticate")
print(f"定义位置: {definition.file}:{definition.line}")

# 影响面分析
impact = client.get_impact_analysis(
    symbol="AuthService.verifyToken",
    change_type="signature"
)
print(f"影响 {len(impact.callers)} 个调用点")
```

```typescript
// codepop-sdk-typescript
import { CodePopClient } from '@codepop/sdk';

const client = new CodePopClient({ baseUrl: 'http://localhost:8080' });

// 搜索
const result = await client.search({
  query: 'OAuth login flow',
  repo: './my-project',
  maxTokens: 8000
});

console.log(result.context);
```

---

## 6. 配置管理

### 6.1 配置文件（~/.codepop/config.yaml）

```yaml
# 数据库配置
database:
  host: localhost
  port: 5432
  name: codepop
  user: postgres
  password: ""  # 使用 pgpass 或环境变量

# 向量嵌入配置
embedding:
  provider: openai  # openai, local, azure
  model: text-embedding-3-small
  dimension: 1536
  # 本地模型配置（可选）
  # provider: local
  # model: nomic-embed-text

# 索引配置
index:
  languages:
    - typescript
    - javascript
    - python
    - go
    - rust
  exclude_patterns:
    - "**/node_modules/**"
    - "**/dist/**"
    - "**/__pycache__/**"
    - "**/*.min.js"
  incremental: true
  sync_interval: 30  # 秒

# 服务配置
server:
  host: 0.0.0.0
  port: 8080
  mcp_port: 8081
  cors: true

# 日志
logging:
  level: info
  file: ~/.codepop/logs/codepop.log
```

### 6.2 环境变量覆盖

```bash
# 数据库
export CODEPOP_DATABASE_URL=postgresql://user:pass@host:5432/codepop

# API Key（用于向量化）
export OPENAI_API_KEY=sk-...

# 服务端口
export CODEPOP_PORT=9000
```

---

## 7. 高可用方案

### 7.1 开发/小团队（单节点）

```
┌─────────────────────────────────────┐
│           Docker Compose            │
│  ┌───────────┐  ┌───────────────┐ │
│  │  CodePop  │  │  PostgreSQL   │ │
│  │  Service  │  │  + pgvector   │ │
│  └───────────┘  └───────────────┘ │
└─────────────────────────────────────┘
```

### 7.2 中型团队（主备）

```
                    ┌─────────────┐
              ┌─────│   HAProxy   │─────┐
              │     └─────────────┘     │
              │                         │
        ┌─────┴─────┐             ┌─────┴─────┐
        │  CodePop  │             │  CodePop  │
        │  Primary  │◄──Sync─────►│  Standby  │
        └─────┬─────┘             └───────────┘
              │
        ┌─────┴─────┐
        │ PostgreSQL│
        │ Primary   │◄──Streaming Replication──►│ PostgreSQL │
        └───────────┘                           │ Standby   │
                                                └───────────┘
```

### 7.3 大型团队（分片）

```sql
-- 按仓库分片的向量化查询
CREATE INDEX idx_embeddings_repo_hnsw ON symbol_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- 查询时自动利用分片键剪枝
SET enable_partition_pruning = on;
SET partition_pruning = on;
```

---

## 8. 性能优化

### 8.1 向量检索优化

```sql
-- HNSW 参数调优（根据数据规模）
CREATE INDEX idx_embeddings_optimized ON symbol_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 32, ef_construction = 128);  -- 大数据量场景

-- 查询时指定 ef_search
SET hnsw.query Ef_search = 100;  -- 提升召回率，略微增加延迟

-- 批量查询优化
PREPARE search_batch AS
SELECT s.*, e.embedding <=> $1 AS distance
FROM symbol_embeddings e
JOIN symbols s ON e.symbol_id = s.id
WHERE e.repo_id = $2
ORDER BY e.embedding <=> $1
LIMIT $3;
```

### 8.2 连接池配置

```yaml
# config.yaml
database:
  pool:
    min: 2
    max: 20
    idle_timeout: 30000
    connection_timeout: 5000
```

### 8.3 缓存策略

```sql
-- 符号信息缓存（Redis 或内存）
CREATE TABLE symbol_cache (
    key TEXT PRIMARY KEY,
    value JSONB,
    expires_at TIMESTAMP
);

-- 热点符号预加载
CREATE INDEX idx_cache_expires ON symbol_cache(expires_at);
```

---

## 9. 监控与告警

### 9.1 关键指标

```sql
-- 索引健康检查
SELECT
    r.name,
    r.file_count,
    r.symbol_count,
    r.last_indexed_at,
    NOW() - r.last_indexed_at AS index_age
FROM repos r
WHERE r.last_indexed_at < NOW() - INTERVAL '1 hour';

-- 向量一致性检查
SELECT
    COUNT(*) AS total_symbols,
    COUNT(e.id) AS total_embeddings,
    COUNT(*) - COUNT(e.id) AS missing_embeddings
FROM symbols s
LEFT JOIN symbol_embeddings e ON s.id = e.symbol_id
WHERE s.repo_id = $repo_id;

-- 慢查询监控
SELECT
    query,
    calls,
    mean_exec_time,
    total_exec_time
FROM pg_stat_statements
WHERE query LIKE '%symbol_embeddings%'
ORDER BY mean_exec_time DESC
LIMIT 10;
```

### 9.2 日志集成

```yaml
# config.yaml
logging:
  format: json
  outputs:
    - type: stdout
    - type: file
      path: ~/.codepop/logs/codepop.log
    # - type: sentry
    #   dsn: https://xxx@sentry.io/xxx
```

---

## 10. 快速开始

### 10.1 完整安装脚本

```bash
#!/bin/bash
set -e

# 1. 创建项目目录
mkdir -p ~/codepop-demo && cd ~/codepop-demo

# 2. 启动服务
cat > docker-compose.yml << 'EOF'
services:
  postgres:
    image: ankane/pgvector:pg16
    environment:
      POSTGRES_DB: codepop
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: codepop123
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

  codepop:
    image: codepop/codepop:latest
    ports:
      - "8080:8080"
      - "8081:8081"
    environment:
      DATABASE_URL: postgresql://postgres:codepop123@postgres:5432/codepop
    volumes:
      - .:/repo

volumes:
  pgdata:
EOF

# 3. 启动
docker compose up -d

# 4. 等待就绪
sleep 5

# 5. 索引示例代码
docker exec -it codepop-codepop-1 codepop index /repo

echo "✓ CodePop 已启动！"
echo "  REST API: http://localhost:8080/v1"
echo "  MCP: http://localhost:8081/mcp"
```

### 10.2 验证安装

```bash
# 健康检查
curl http://localhost:8080/health

# 搜索测试
curl -X POST http://localhost:8080/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "hello world", "repo": "/repo"}'
```

---

## 11. 效果评测体系

企业落地需要量化证明 CodePop 的价值。本章节提供完整的评测方法论和工具。

### 11.1 评测维度总览

| 维度 | 核心指标 | 目标值 | 评测方法 |
|------|---------|--------|---------|
| Token 节省 | 上下文压缩率 | 60-80% | 对比实验 |
| 准确性 | Top-5 命中率 | > 85% | 人工标注 |
| 响应速度 | P95 延迟 | < 500ms | 压测工具 |
| 召回率 | Recall@20 | > 90% | 查询集测试 |
| 稳定性 | 可用性 | > 99.9% | 长期监控 |

---

### 11.2 Token 消耗评测

#### 11.2.1 数据埋点

```sql
-- 查询日志表增强
CREATE TABLE query_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL,
    query_hash VARCHAR(64) NOT NULL,  -- 查询文本的 hash，用于去重
    query_text TEXT,
    repo_id UUID REFERENCES repos(id),
    -- 无 CodePop 时的情况（模拟）
    baseline_tokens INTEGER,           -- 模拟全量上下文
    baseline_context_preview TEXT,    -- 模拟上下文片段

    -- 使用 CodePop 后
    codepop_tokens INTEGER,
    codepop_sources JSONB,          -- 返回的源码引用
    codepop_latency_ms INTEGER,

    -- 对比结果
    token_saved INTEGER GENERATED ALWAYS AS (baseline_tokens - codepop_tokens) STORED,
    token_saved_ratio FLOAT GENERATED ALWAYS AS (
        CASE WHEN baseline_tokens > 0
        THEN (baseline_tokens - codepop_tokens)::FLOAT / baseline_tokens
        ELSE 0 END
    ) STORED,

    created_at TIMESTAMP DEFAULT NOW()
);

-- 创建分析视图
CREATE VIEW token_savings_summary AS
SELECT
    DATE_TRUNC('day', created_at) AS day,
    COUNT(*) AS total_queries,
    AVG(baseline_tokens) AS avg_baseline,
    AVG(codepop_tokens) AS avg_codepop,
    AVG(token_saved_ratio) AS avg_savings_ratio,
    SUM(token_saved) AS total_tokens_saved,
    SUM(baseline_tokens) AS total_baseline,
    SUM(codepop_tokens) AS total_codepop
FROM query_metrics
GROUP BY DATE_TRUNC('day', created_at)
ORDER BY day DESC;
```

#### 11.2.2 Baseline 模拟（无 CodePop 场景）

```python
# baseline_simulator.py
"""
模拟没有 CodePop 时 Agent 会获取的上下文
通过设定一个较大的上下文窗口来模拟"盲目获取"
"""
import tiktoken

class BaselineSimulator:
    def __init__(self, max_context: int = 128000):
        self.max_context = max_context
        self.encoding = tiktoken.get_encoding("cl100k_base")

    def simulate_baseline(self, repo_path: str, query: str) -> dict:
        """
        模拟无 CodePop 时的行为：
        1. Agent 只能获取最近修改的文件
        2. 或者获取包含关键词的所有文件
        3. 无法精确判断相关性
        """
        # 模拟策略：获取最近修改的 N 个文件
        recent_files = self.get_recently_modified(repo_path, limit=20)

        # 模拟 Token 消耗
        baseline_tokens = 0
        for f in recent_files:
            baseline_tokens += len(self.encoding.encode(f.content))

        return {
            "tokens": min(baseline_tokens, self.max_context),
            "files_included": len(recent_files),
            "strategy": "recent_files"
        }

    def calculate_savings(self, query: str) -> dict:
        """计算节省比例"""
        baseline = self.simulate_baseline(QUERY_CONTEXT, query)
        codepop = self.get_codepop_result(query)

        return {
            "baseline_tokens": baseline["tokens"],
            "codepop_tokens": codepop["tokens"],
            "saved_tokens": baseline["tokens"] - codepop["tokens"],
            "savings_ratio": (baseline["tokens"] - codepop["tokens"]) / baseline["tokens"]
        }
```

#### 11.2.3 报表生成

```sql
-- 每日 Token 节省报表
SELECT
    day,
    total_queries,
    total_baseline,
    total_codepop,
    total_tokens_saved,
    ROUND(avg_savings_ratio * 100, 1) AS savings_percent,
    -- 估算成本节省（基于 GPT-4o 价格）
    ROUND(total_tokens_saved * 0.000015, 2) AS estimated_cost_saved_usd
FROM token_savings_summary
WHERE day >= CURRENT_DATE - INTERVAL '30 days'
ORDER BY day DESC;

-- 输出示例：
-- day        | total_queries | total_baseline | total_codepop | savings_percent | estimated_cost_saved_usd
-- -----------|---------------|----------------|---------------|-----------------|------------------------
-- 2026-06-19 | 1,234         | 4,521,000      | 892,000       | 80.3%           | 54.44
-- 2026-06-18 | 1,102         | 4,102,000      | 856,000       | 79.1%           | 48.69
```

---

### 11.3 准确性评测

#### 11.3.1 评测数据集构建

```python
# 构建 benchmark dataset
# 每条记录包含：query, expected_symbols, expected_files

BENCHMARK_QUERIES = [
    {
        "id": "ts_auth_001",
        "query": "用户登录验证逻辑在哪里",
        "expected": {
            "files": ["src/auth/login.ts", "src/middleware/auth.ts"],
            "symbols": ["UserService.authenticate", "validatePassword"]
        },
        "intent": "understand"
    },
    {
        "id": "py_api_002",
        "query": "删除用户的 API 接口",
        "expected": {
            "files": ["app/routers/users.py"],
            "symbols": ["delete_user", "UserRepository.delete"]
        },
        "intent": "usage"
    },
    # ... 扩展到 500+ 条
]

# 多语言覆盖
LANGUAGE_COVERAGE = {
    "typescript": 100,
    "python": 100,
    "go": 80,
    "rust": 60,
    "java": 60
}
```

#### 11.3.2 准确性指标计算

```sql
-- 准确性评测结果表
CREATE TABLE accuracy_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    benchmark_id VARCHAR(50) NOT NULL,
    query_text TEXT NOT NULL,
    language VARCHAR(50),
    intent VARCHAR(50),

    -- CodePop 返回结果
    returned_files JSONB,
    returned_symbols JSONB,

    -- 期望结果
    expected_files JSONB,
    expected_symbols JSONB,

    -- 命中计算
    file_hit_count INTEGER,
    file_hit_ratio FLOAT,
    symbol_hit_count INTEGER,
    symbol_hit_ratio FLOAT,

    -- 综合得分
    ndcg_score FLOAT,  -- Normalized Discounted Cumulative Gain

    created_at TIMESTAMP DEFAULT NOW()
);

-- 命中计算函数
CREATE OR REPLACE FUNCTION calculate_hit_metrics(
    returned JSONB,
    expected JSONB
) RETURNS TABLE(hit_count INTEGER, hit_ratio FLOAT) AS $$
DECLARE
    total INTEGER;
    hits INTEGER;
BEGIN
    total := jsonb_array_length(expected);
    hits := 0;

    FOR i IN 0..(total - 1) LOOP
        IF returned @> jsonb_build_array(expected -> i) THEN
            hits := hits + 1;
        END IF;
    END LOOP;

    hit_count := hits;
    hit_ratio := CASE WHEN total > 0 THEN hits::FLOAT / total ELSE 0 END;

    RETURN NEXT;
END;
$$ LANGUAGE plpgsql;

-- 汇总统计
CREATE VIEW accuracy_summary AS
SELECT
    language,
    COUNT(*) AS total_queries,
    AVG(file_hit_ratio) AS avg_file_hit,
    AVG(symbol_hit_ratio) AS avg_symbol_hit,
    AVG(ndcg_score) AS avg_ndcg,
    -- Top-K 命中率
    SUM(CASE WHEN symbol_hit_ratio >= 0.2 THEN 1 ELSE 0 END)::FLOAT / COUNT(*) * 100 AS hit_at_1,
    SUM(CASE WHEN symbol_hit_ratio >= 0.4 THEN 1 ELSE 0 END)::FLOAT / COUNT(*) * 100 AS hit_at_2,
    SUM(CASE WHEN symbol_hit_ratio >= 0.8 THEN 1 ELSE 0 END)::FLOAT / COUNT(*) * 100 AS hit_at_5
FROM accuracy_metrics
GROUP BY language;
```

#### 11.3.3 NDCG 评分计算

```python
def calculate_ndcg(
    returned_symbols: list[str],
    expected_symbols: list[str],
    k: int = 10
) -> float:
    """
    NDCG (Normalized Discounted Cumulative Gain)
    衡量返回结果的相关性排序质量
    """
    # DCG@k
    dcg = 0.0
    for i, symbol in enumerate(returned_symbols[:k]):
        rel = 1.0 if symbol in expected_symbols else 0.0
        dcg += rel / math.log2(i + 2)  # i+2 因为从位置1开始

    # IDCG@k (理想状态)
    ideal_symbols = expected_symbols[:min(k, len(expected_symbols))]
    idcg = sum(1.0 / math.log2(i + 2) for i in range(len(ideal_symbols)))

    return dcg / idcg if idcg > 0 else 0.0

# 输出评测报表
"""
Language   | Queries | Avg Hit@5 | Avg NDCG | Pass@85%
-----------|---------|----------|----------|----------
typescript |   100   |   91.2%  |   0.893  |    ✓
python    |   100   |   89.5%  |   0.876  |    ✓
go        |    80   |   87.3%  |   0.854  |    ✓
rust      |    60   |   84.1%  |   0.821  |    ✗
java      |    60   |   82.8%  |   0.808  |    ✗

整体 | 400   |   88.7%  |   0.867  |    ✓
"""
```

---

### 11.4 响应速度评测

#### 11.4.1 延迟分布指标

```bash
# 使用 wrk 进行 HTTP 压测
wrk -t4 -c100 -d60s -s benchmark.lua http://localhost:8080/v1/search

# benchmark.lua
wrk.method = "POST"
wrk.body   = '{"query": "OAuth login", "repo": "/repo", "max_tokens": 8000}'
wrk.headers["Content-Type"] = "application/json"
```

```python
# latency_analyzer.py
"""
分析响应延迟分布
"""
import numpy as np
from collections import defaultdict

class LatencyAnalyzer:
    def __init__(self):
        self.latencies = []
        self.by_language = defaultdict(list)
        self.by_repo_size = defaultdict(list)

    def record(self, latency_ms: int, language: str = None, repo_size: int = None):
        self.latencies.append(latency_ms)
        if language:
            self.by_language[language].append(latency_ms)
        if repo_size:
            bucket = self.get_size_bucket(repo_size)
            self.by_repo_size[bucket].append(latency_ms)

    def get_percentile(self, data: list, p: float) -> float:
        """计算百分位数"""
        return np.percentile(data, p * 100)

    def report(self) -> dict:
        """生成延迟报告"""
        return {
            "overall": {
                "p50": self.get_percentile(self.latencies, 0.50),
                "p95": self.get_percentile(self.latencies, 0.95),
                "p99": self.get_percentile(self.latencies, 0.99),
                "avg": np.mean(self.latencies),
                "max": max(self.latencies)
            },
            "by_language": {
                lang: {
                    "p95": self.get_percentile(data, 0.95),
                    "avg": np.mean(data),
                    "count": len(data)
                }
                for lang, data in self.by_language.items()
            },
            "by_repo_size": {
                bucket: {
                    "p95": self.get_percentile(data, 0.95),
                    "avg": np.mean(data)
                }
                for bucket, data in self.by_repo_size.items()
            }
        }
```

#### 11.4.2 慢查询分析

```sql
-- 识别慢查询
SELECT
    q.query_text,
    r.name AS repo,
    r.file_count AS repo_size,
    q.codepop_latency_ms,
    q.codepop_tokens,
    q.returned_sources,
    CASE
        WHEN q.codepop_latency_ms > 1000 THEN 'SLOW'
        WHEN q.codepop_latency_ms > 500 THEN 'MEDIUM'
        ELSE 'FAST'
    END AS latency_category
FROM query_metrics q
JOIN repos r ON q.repo_id = r.id
WHERE q.created_at >= NOW() - INTERVAL '24 hours'
ORDER BY q.codepop_latency_ms DESC
LIMIT 20;

-- 按仓库规模分组延迟
SELECT
    CASE
        WHEN file_count < 100 THEN 'SMALL (<100 files)'
        WHEN file_count < 1000 THEN 'MEDIUM (100-1000 files)'
        WHEN file_count < 10000 THEN 'LARGE (1000-10000 files)'
        ELSE 'XLARGE (>10000 files)'
    END AS repo_size_bucket,
    COUNT(*) AS total_queries,
    AVG(codepop_latency_ms) AS avg_latency,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY codepop_latency_ms) AS p95_latency,
    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY codepop_latency_ms) AS p99_latency
FROM query_metrics q
JOIN repos r ON q.repo_id = r.id
WHERE q.created_at >= NOW() - INTERVAL '7 days'
GROUP BY
    CASE
        WHEN file_count < 100 THEN 'SMALL (<100 files)'
        WHEN file_count < 1000 THEN 'MEDIUM (100-1000 files)'
        WHEN file_count < 10000 THEN 'LARGE (1000-10000 files)'
        ELSE 'XLARGE (>10000 files)'
    END
ORDER BY avg_latency;
```

#### 11.4.3 延迟目标达成

```
┌─────────────────────────────────────────────────────────────┐
│                    响应延迟目标达成表                          │
├──────────────┬───────────┬───────────┬───────────┬──────────┤
│ 仓库规模     │ P50 目标  │ P50 实际  │ P95 目标  │ P95 实际 │
├──────────────┼───────────┼───────────┼───────────┼──────────┤
│ 小 (<100)    │   <100ms  │   45ms ✓  │  <300ms   │  180ms ✓ │
│ 中 (100-1K)  │   <200ms  │   98ms ✓  │  <500ms   │  320ms ✓ │
│ 大 (1K-10K)  │   <300ms  │  156ms ✓  │  <800ms   │  520ms ✓ │
│ 超大 (>10K)  │   <500ms  │  287ms ✓  │ <1500ms   │  890ms ✓ │
└──────────────┴───────────┴───────────┴───────────┴──────────┘

✓ 所有规模仓库均达成秒级响应目标
```

---

### 11.5 跨语言/跨仓库评测

#### 11.5.1 多语言评测矩阵

```bash
#!/bin/bash
# run_multilang_benchmark.sh

LANGUAGES=("typescript" "python" "go" "rust" "java")
REPO_SIZES=("small" "medium" "large")

for lang in "${LANGUAGES[@]}"; do
    for size in "${REPO_SIZES[@]}"; do
        echo "Testing $lang - $size"

        # 1. 准备测试仓库
        codepop benchmark prepare --lang $lang --size $size --output /tmp/test-repo

        # 2. 索引
        codepop index /tmp/test-repo --quiet

        # 3. 执行查询
        codepop benchmark run \
            --repo /tmp/test-repo \
            --queries ./benchmarks/${lang}_queries.json \
            --output /tmp/results/${lang}_${size}.json

        # 4. 分析结果
        codepop benchmark report \
            --input /tmp/results/${lang}_${size}.json \
            --format markdown
    done
done
```

#### 11.5.2 评测结果汇总

```sql
-- 跨语言综合报表
CREATE VIEW cross_language_report AS
WITH summary AS (
    SELECT
        m.language,
        COUNT(*) AS total_queries,
        AVG(m.symbol_hit_ratio) AS avg_accuracy,
        AVG(q.codepop_latency_ms) AS avg_latency,
        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY q.codepop_latency_ms) AS p95_latency,
        AVG(q.token_saved_ratio) AS avg_token_savings
    FROM accuracy_metrics m
    JOIN query_metrics q ON m.benchmark_id = q.query_hash
    GROUP BY m.language
)
SELECT
    language,
    total_queries,
    ROUND(avg_accuracy * 100, 1) || '%' AS accuracy,
    avg_latency || 'ms' AS avg_latency,
    p95_latency || 'ms' AS p95_latency,
    ROUND(avg_token_savings * 100, 1) || '%' AS token_saved,
    CASE
        WHEN avg_accuracy >= 0.85 AND p95_latency <= 500 THEN '✅ PASS'
        ELSE '❌ FAIL'
    END AS status
FROM summary
ORDER BY avg_accuracy DESC;
```

#### 11.5.3 评测报告样例

```
# CodePop 效果评测报告
生成时间: 2026-06-19

## 1. Token 节省

| 时间 | 查询数 | Baseline Tokens | CodePop Tokens | 节省比例 | 节省成本 |
|------|--------|-----------------|-----------------|---------|---------|
| 今日 | 1,234 | 4,521,000 | 892,000 | 80.3% | $54.44 |
| 本周 | 8,921 | 32,145,000 | 6,890,000 | 78.6% | $378.82 |
| 本月 | 45,230 | 162,890,000 | 35,120,000 | 78.4% | $1,916.55 |

## 2. 准确性

| 语言 | 查询数 | Top-5 命中率 | NDCG | 达标 |
|------|--------|-------------|------|------|
| TypeScript | 100 | 91.2% | 0.893 | ✅ |
| Python | 100 | 89.5% | 0.876 | ✅ |
| Go | 80 | 87.3% | 0.854 | ✅ |
| Rust | 60 | 84.1% | 0.821 | ✅ |
| Java | 60 | 82.8% | 0.808 | ❌ |
| **整体** | **400** | **88.7%** | **0.867** | **✅** |

## 3. 响应速度

| 仓库规模 | 查询数 | P50 | P95 | P99 | 目标达成 |
|----------|--------|-----|-----|-----|---------|
| 小 (<100) | 523 | 45ms | 180ms | 230ms | ✅ |
| 中 (100-1K) | 1,102 | 98ms | 320ms | 450ms | ✅ |
| 大 (1K-10K) | 2,341 | 156ms | 520ms | 680ms | ✅ |
| 超大 (>10K) | 856 | 287ms | 890ms | 1,120ms | ✅ |

## 4. 综合评分

| 维度 | 权重 | 得分 | 说明 |
|------|------|------|------|
| Token 节省 | 30% | 95 | 平均节省 78.6% |
| 准确性 | 35% | 88 | Top-5 命中率 88.7% |
| 响应速度 | 20% | 92 | P95 < 1s |
| 稳定性 | 15% | 99.9 | 月可用性 99.9% |
| **综合** | 100% | **92.5** | **优秀** |

## 5. 改进建议

1. **Java 支持需加强**：当前命中率 82.8%，低于 85% 目标，建议优化 Java 解析器
2. **超大仓库优化**：P95 接近 1s，建议增加缓存层
```

---

### 11.6 A/B 测试框架

#### 11.6.1 实验配置

```yaml
# ab_test_config.yaml
experiments:
  - id: "emb_model_v2"
    name: "新版嵌入模型测试"
    description: "对比 text-embedding-3-small vs nomic-embed-text"
    variants:
      control:
        embedding_model: "text-embedding-3-small"
      treatment:
        embedding_model: "nomic-embed-text"
    traffic_split: 0.5  # 50% 用户进入实验组
    metrics:
      primary: "symbol_hit_ratio"
      secondary: ["token_saved_ratio", "p95_latency"]
    min_sample_size: 1000
    duration: 7d

  - id: "hybrid_weight"
    name: "混合检索权重优化"
    description: "调整向量与符号检索的权重比例"
    variants:
      control:
        vector_weight: 0.6
        symbol_weight: 0.4
      treatment:
        vector_weight: 0.4
        symbol_weight: 0.6
    traffic_split: 0.5
    metrics:
      primary: "ndcg_score"
    min_sample_size: 2000
    duration: 14d
```

#### 11.6.2 统计显著性检验

```python
from scipy import stats

def test_significance(control_metrics: list, treatment_metrics: list) -> dict:
    """
    检验两组数据的统计显著性
    使用 Mann-Whitney U 检验（非参数）
    """
    stat, p_value = stats.mannwhitneyu(control_metrics, treatment_metrics)

    control_mean = np.mean(control_metrics)
    treatment_mean = np.mean(treatment_metrics)
    lift = (treatment_mean - control_mean) / control_mean

    return {
        "control_mean": control_mean,
        "treatment_mean": treatment_mean,
        "lift": lift,
        "p_value": p_value,
        "significant": p_value < 0.05,
        "confidence": "95% 置信区间" if p_value < 0.05 else "不显著"
    }

# 输出示例
"""
{
    "control_mean": 0.85,
    "treatment_mean": 0.89,
    "lift": 0.047,  # +4.7% 提升
    "p_value": 0.0023,
    "significant": true,
    "confidence": "统计显著，95% 置信"
}
"""
```

---

### 11.7 自动化评测流水线

#### 11.7.1 CI/CD 集成

```yaml
# .github/workflows/benchmark.yml
name: CodePop Benchmark

on:
  push:
    branches: [main, develop]
  schedule:
    - cron: '0 2 * * *'  # 每天凌晨执行

jobs:
  benchmark:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup CodePop
        run: |
          docker compose up -d
          sleep 10
          codepop init

      - name: Run Benchmark
        run: |
          codepop benchmark run \
            --repo ./test-repos/typescript-medium \
            --output ./benchmark-results/$(date +%Y%m%d).json

      - name: Upload Results
        uses: actions/upload-artifact@v4
        with:
          name: benchmark-results
          path: ./benchmark-results/

      - name: Check Thresholds
        run: |
          codepop benchmark check \
            --input ./benchmark-results/latest.json \
            --thresholds:
              accuracy: 0.85
              p95_latency: 500
              token_savings: 0.6
```

#### 11.7.2 持续监控仪表盘

```json
// dashboard_config.json - Grafana Dashboard
{
  "panels": [
    {
      "title": "Token 节省趋势",
      "type": "timeseries",
      "targets": [
        {
          "expr": "rate(codepop_tokens_saved_total[1h])",
          "legendFormat": "Token 节省速率"
        }
      ]
    },
    {
      "title": "Top-5 命中率",
      "type": "gauge",
      "targets": [
        {
          "expr": "codepop_hit_rate_top5",
          "thresholds": {
            "80": "yellow",
            "85": "green"
          }
        }
      ]
    },
    {
      "title": "P95 响应延迟",
      "type": "timeseries",
      "targets": [
        {
          "expr": "histogram_quantile(0.95, codepop_latency_bucket)",
          "legendFormat": "P95 延迟"
        }
      ]
    },
    {
      "title": "按语言分组准确性",
      "type": "bargauge",
      "targets": [
        {
          "expr": "codepop_accuracy_by_language",
          "legendFormat": "{{language}}"
        }
      ]
    }
  ]
}
```

---

### 11.8 评测快速开始

```bash
#!/bin/bash
# 快速运行完整评测

echo "=== CodePop 效果评测 ==="

# 1. 启动服务
docker compose up -d
sleep 5

# 2. 准备测试数据
echo "[1/5] 准备测试仓库..."
codepop benchmark prepare --lang typescript --size medium --output /tmp/test-repo

# 3. 索引
echo "[2/5] 索引测试仓库..."
codepop index /tmp/test-repo --quiet

# 4. 运行评测
echo "[3/5] 执行基准测试..."
codepop benchmark run \
    --repo /tmp/test-repo \
    --queries ./benchmarks/standard_queries.json \
    --output /tmp/results/latest.json

# 5. 生成报告
echo "[4/5] 生成评测报告..."
codepop benchmark report \
    --input /tmp/results/latest.json \
    --format markdown \
    --output ./reports/benchmark_$(date +%Y%m%d).md

# 6. 阈值检查
echo "[5/5] 阈值检查..."
codepop benchmark check --input /tmp/results/latest.json

echo ""
echo "=== 评测完成 ==="
echo "报告位置: ./reports/benchmark_$(date +%Y%m%d).md"
```

---

## 10. 异常处理与降级策略

### 10.1 异常分类体系

```python
# exception_types.py
from enum import Enum
from typing import Optional

class ErrorCode(Enum):
    # 索引层错误
    INDEX_NOT_FOUND = "INDEX_001"      # 仓库未索引
    INDEX_BUILDING = "INDEX_002"       # 索引构建中
    INDEX_CORRUPTED = "INDEX_003"      # 索引损坏

    # 数据库错误
    DB_CONNECTION_FAILED = "DB_001"     # 数据库连接失败
    DB_TIMEOUT = "DB_002"               # 数据库超时
    DB_QUERY_FAILED = "DB_003"         # 查询执行失败

    # 向量服务错误
    EMBEDDING_SERVICE_DOWN = "EM_001"  # 嵌入服务不可用
    EMBEDDING_TIMEOUT = "EM_002"       # 嵌入生成超时
    EMBEDDING_QUOTA_EXCEEDED = "EM_003" # API 配额超限

    # 检索错误
    SEARCH_TIMEOUT = "SR_001"          # 检索超时
    NO_RESULTS = "SR_002"              # 未找到结果
    RESULT_TOO_LARGE = "SR_003"       # 结果超过限制

    # 文件系统错误
    FILE_NOT_FOUND = "FS_001"          # 文件不存在
    FILE_PERMISSION_DENIED = "FS_002"  # 权限不足
    FILE_TOO_LARGE = "FS_003"          # 文件过大

class ErrorSeverity(Enum):
    LOW = "low"        # 不影响主流程，降级处理
    MEDIUM = "medium"  # 部分功能受影响
    HIGH = "high"      # 服务不可用
    CRITICAL = "critical"  # 需人工介入
```

### 10.2 降级策略矩阵

| 故障场景 | 影响功能 | 降级策略 | 用户感知 |
|---------|---------|---------|---------|
| pgvector 不可用 | 向量检索 | 切换纯符号检索 | 语义搜索降级为精确匹配 |
| 嵌入 API 超时 | 生成向量 | 使用缓存向量 / 预计算向量 | 首次可能慢，后续正常 |
| 数据库连接断开 | 全部功能 | 返回缓存结果 | 短暂不可用 |
| 单仓库索引损坏 | 单仓库查询 | 返回索引重建提示 | 其他仓库正常 |
| 网络分区 | 远程仓库 | 切换本地缓存模式 | 实时同步暂停 |
| Token 超限 | 上下文返回 | 截断并标记 | 返回不完整上下文 |

### 10.3 降级实现代码

```python
# graceful_degradation.py
import asyncio
from functools import wraps
from typing import TypeVar, Callable, Optional
import logging

logger = logging.getLogger(__name__)
T = TypeVar('T')

class DegradationStrategy:
    """降级策略管理器"""

    def __init__(self):
        self.vector_cache = {}      # 预计算向量缓存
        self.result_cache = {}      # 查询结果缓存
        self.fallback_enabled = True

    async def search_with_fallback(
        self,
        query: str,
        repo_id: str,
        options: dict
    ) -> dict:
        """
        降级检索流程：
        1. 尝试向量检索
        2. 失败则降级到符号检索
        3. 再失败则返回缓存结果
        4. 都不行则返回友好错误
        """
        # 策略1：完整检索（向量 + 符号）
        try:
            result = await self._full_search(query, repo_id, options)
            await self._cache_result(query, repo_id, result)
            return result
        except VectorServiceError as e:
            logger.warning(f"向量检索失败，降级到符号检索: {e}")
            return await self._symbol_only_search(query, repo_id, options)
        except DatabaseError as e:
            logger.error(f"数据库错误: {e}")
            return await self._fallback_to_cache(query, repo_id)
        except Exception as e:
            logger.critical(f"未知错误: {e}")
            return self._return_graceful_error(e)

    async def _full_search(self, query, repo_id, options) -> dict:
        """完整检索流程"""
        # 1. 生成查询向量
        embedding = await self._get_embedding(query)

        # 2. 向量相似度检索
        vector_results = await self._vector_search(embedding, repo_id)

        # 3. 符号精确匹配
        symbol_results = await self._symbol_search(query, repo_id)

        # 4. 混合排序
        return self._merge_results(vector_results, symbol_results)

    async def _symbol_only_search(self, query, repo_id, options) -> dict:
        """降级：仅符号检索"""
        symbol_results = await self._symbol_search(query, repo_id)

        return {
            "context": self._format_context(symbol_results),
            "sources": symbol_results,
            "metadata": {
                "degraded": True,
                "degraded_reason": "vector_search_unavailable",
                "fallback_method": "symbol_only"
            }
        }

    async def _fallback_to_cache(self, query, repo_id) -> dict:
        """降级：使用缓存结果"""
        cache_key = f"{repo_id}:{hash(query)}"
        cached = self.result_cache.get(cache_key)

        if cached:
            logger.info(f"使用缓存结果: {cache_key}")
            return {
                **cached,
                "metadata": {
                    **cached.get("metadata", {}),
                    "degraded": True,
                    "degraded_reason": "cache_fallback",
                    "cache_age_seconds": (datetime.now() - cached["cached_at"]).seconds
                }
            }

        return self._return_graceful_error(
            ErrorCode.NO_RESULTS,
            message="暂时无法检索，请稍后重试或联系管理员"
        )

    def _return_graceful_error(self, error) -> dict:
        """返回友好错误"""
        return {
            "success": False,
            "error": {
                "code": error.code if hasattr(error, 'code') else "UNKNOWN",
                "message": str(error),
                "recoverable": True,
                "suggestion": self._get_suggestion(error)
            },
            "context": None,
            "sources": []
        }

    def _get_suggestion(self, error) -> str:
        """获取恢复建议"""
        suggestions = {
            ErrorCode.INDEX_NOT_FOUND: "请先运行 `codepop index <repo>` 索引仓库",
            ErrorCode.INDEX_BUILDING: "索引正在构建中，请稍后重试",
            ErrorCode.DB_TIMEOUT: "数据库响应慢，可尝试减少查询范围",
            ErrorCode.EMBEDDING_TIMEOUT: "嵌入服务响应慢，已使用缓存数据",
        }
        return suggestions.get(getattr(error, 'code', None), "请稍后重试")
```

### 10.4 重试机制

```python
# retry_strategy.py
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)

class RetryConfig:
    # 嵌入服务：指数退避
    EMBEDDING_RETRY = {
        "max_attempts": 3,
        "initial_wait": 1,
        "max_wait": 10,
        "multiplier": 2
    }

    # 数据库：短等待
    DATABASE_RETRY = {
        "max_attempts": 2,
        "initial_wait": 0.5,
        "max_wait": 3
    }

    # 检索服务：容忍度高
    SEARCH_RETRY = {
        "max_attempts": 1,  # 检索不重试，返回降级结果
        "fallback_to_cache": True
    }

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, max=10),
    retry=retry_if_exception_type(EmbeddingServiceError)
)
async def get_embedding_with_retry(text: str) -> list[float]:
    """带重试的嵌入生成"""
    return await embedding_service.get_embedding(text)
```

### 10.5 熔断器模式

```python
# circuit_breaker.py
from datetime import datetime, timedelta
from collections import deque

class CircuitBreaker:
    """
    熔断器：防止级联故障
    状态：CLOSED（正常）-> OPEN（熔断）-> HALF_OPEN（试探）
    """

    def __init__(self, failure_threshold: int = 5, timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.timeout = timeout  # 秒
        self.failures = deque(maxlen=failure_threshold)
        self.state = "CLOSED"
        self.last_failure_time = None

    def call(self, func: Callable) -> T:
        if self.state == "OPEN":
            if self._should_attempt_reset():
                self.state = "HALF_OPEN"
            else:
                raise CircuitOpenError("熔断器开启，请稍后重试")

        try:
            result = func()
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _on_success(self):
        self.failures.clear()
        self.state = "CLOSED"

    def _on_failure(self):
        self.failures.append(datetime.now())
        if len(self.failures) >= self.failure_threshold:
            self.state = "OPEN"
            self.last_failure_time = datetime.now()

    def _should_attempt_reset(self) -> bool:
        return datetime.now() - self.last_failure_time > timedelta(seconds=self.timeout)


# 全局熔断器实例
embedding_circuit = CircuitBreaker(failure_threshold=5, timeout=60)
db_circuit = CircuitBreaker(failure_threshold=3, timeout=30)
```

### 10.6 健康检查与自愈

```sql
-- 健康检查查询
CREATE OR REPLACE FUNCTION health_check() RETURNS JSONB AS $$
DECLARE
    result JSONB;
BEGIN
    -- 1. 数据库连接
    BEGIN
        PERFORM 1;
        result := jsonb_build_object(
            'status', 'healthy',
            'checks', jsonb_build_array(
                jsonb_build_object(
                    'name', 'database',
                    'status', 'ok'
                )
            )
        );
    EXCEPTION WHEN OTHERS THEN
        result := jsonb_build_object(
            'status', 'unhealthy',
            'checks', jsonb_build_array(
                jsonb_build_object(
                    'name', 'database',
                    'status', 'error',
                    'message', SQLERRM
                )
            )
        );
    END;

    RETURN result;
END;
$$ LANGUAGE plpgsql;

-- 返回结构示例
-- {
--   "status": "healthy|degraded|unhealthy",
--   "checks": [
--     {"name": "database", "status": "ok|error", "latency_ms": 5},
--     {"name": "embedding_service", "status": "ok|degraded|error"},
--     {"name": "indexes", "status": "ok", "missing_indexes": 0}
--   ]
-- }
```

```python
# self_healing.py
async def auto_repair():
    """自动修复策略"""
    health = await check_health()

    if health["status"] == "unhealthy":
        # 尝试重启服务
        await restart_services()
        await wait_for_recovery(timeout=30)

    # 检查索引完整性
    missing = await check_missing_embeddings()
    if missing > 0:
        logger.warning(f"发现 {missing} 个缺失的向量嵌入")
        # 触发增量索引
        await trigger_incremental_index(missing_symbols=missing)
```

---

## 12. 可视化界面（运维管理控制台）

### 12.1 设计理念

**目标**：让用户从"需要看文档配置"变为"向导式点点点"，5 分钟内完成全部配置。

**核心原则**：
- **零手动配置**：所有配置通过界面可视化完成
- **智能默认值**：95% 场景无需修改默认配置
- **实时验证**：配置立即生效，无需重启
- **一键部署**：本地/云端一键启动完整服务

### 12.2 Web 管理界面

#### 12.2.1 技术栈

| 组件 | 技术选型 | 说明 |
|------|---------|------|
| 前端框架 | React + TypeScript | 响应式，组件化 |
| UI 组件库 | shadcn/ui + Tailwind | 现代化设计 |
| 状态管理 | Zustand | 轻量级 |
| 图表库 | Recharts | 指标可视化 |
| 后端通信 | React Query | 数据获取与缓存 |
| 构建工具 | Vite | 快速构建 |
| SSH 终端 | xterm.js | 浏览器内终端 |
| 配置编辑器 | Monaco Editor | JSON/YAML 可视化编辑 |

#### 12.2.2 一键部署向导

**首次使用引导流程**

```
┌─────────────────────────────────────────────────────────────────┐
│                    🎉 欢迎使用 CodePop                          │
│                                                                 │
│         ┌─────────────────────────────────────┐               │
│         │                                     │               │
│         │    🚀   开始配置你的代码助手         │               │
│         │                                     │               │
│         │    第1步：选择部署方式               │               │
│         │    ┌─────────┐  ┌─────────┐         │               │
│         │    │ 本地开发 │  │ 云端服务 │         │               │
│         │    │  (推荐)  │  │  企业版  │         │               │
│         │    └─────────┘  └─────────┘         │               │
│         │                                     │               │
│         └─────────────────────────────────────┘               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**部署方式对比**

| 方式 | 适用场景 | 配置项 | 预计时间 |
|------|---------|--------|---------|
| 本地 Docker | 个人/小团队 | 0（自动检测） | 2 分钟 |
| 云端一键 | 中型团队 | 1（选择规格） | 3 分钟 |
| 企业私有化 | 大型企业 | 数据库/Git/监控 | 10 分钟 |

#### 12.2.3 快速配置页面

**向导式配置（5 步完成）**

```
┌─────────────────────────────────────────────────────────────────┐
│  快速配置向导                              步骤 2/5：数据库配置  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ○ 使用内置 PostgreSQL（推荐）                                   │
│    └─ 自动配置，开箱即用                                        │
│                                                                 │
│  ● 连接已有数据库                                               │
│    ┌─────────────────────────────────────────────────────────┐ │
│    │  主机:     [localhost________________________]  端口:5432│ │
│    │  数据库:   [codepop__________________________]           │ │
│    │  用户名:   [postgres________________________]           │ │
│    │  密码:     [••••••••________________________] 🔍 测试连接│ │
│    │                                                         │ │
│    │  ✓ 连接成功！PostgreSQL 16 + pgvector 已就绪            │ │
│    └─────────────────────────────────────────────────────────┘ │
│                                                                 │
│  高级选项 ▼                                                     │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  连接池: min [2] - max [20]                             │   │
│  │  向量维度: [1536] (匹配 OpenAI text-embedding-3-small) │   │
│  │  HNSW 参数: m=[16] ef_construction=[64]                │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│                              [上一步]  [下一步：添加仓库]       │
└─────────────────────────────────────────────────────────────────┘
```

### 12.3 远程仓库配置（GitHub/Gitee）

#### 12.3.1 Git 仓库管理

```
┌─────────────────────────────────────────────────────────────────┐
│  仓库管理                                    [+ 添加仓库 ▼]      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │ GitHub / Gitee 集成                                         ││
│  │                                                             ││
│  │  平台:   [GitHub ▼]    认证: [OAuth 登录] 🔗                ││
│  │                                                             ││
│  │  选择仓库:                                                  ││
│  │  ┌─────────────────────────────────────────────────────┐  ││
│  │  │ ☑ my-org/frontend-app          TypeScript  2,341 ★ │  ││
│  │  │   └─ 最近更新: 2小时前  分支: main                  │  ││
│  │  ├─────────────────────────────────────────────────────┤  ││
│  │  │ ☑ my-org/backend-api             Python       892 ★ │  ││
│  │  │   └─ 最近更新: 昨天       分支: develop             │  ││
│  │  ├─────────────────────────────────────────────────────┤  ││
│  │  │ ☐ my-org/legacy-monorepo      Mixed       5,123   │  ││
│  │  │   └─ 最近更新: 3个月前     分支: master             │  ││
│  │  └─────────────────────────────────────────────────────┘  ││
│  │                                                             ││
│  │  索引选项:                                                  ││
│  │  ☑ 自动同步 Webhook    ☐ 包含分支: [main, develop ▼]     ││
│  │  ☐ 索引深浅: [完整索引 ▼]                                  ││
│  │                                                             ││
│  │  [批量添加选中的仓库]                                       ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### 12.3.2 Git 集成配置详情

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| 平台 | GitHub / Gitee / GitLab / 自建 | GitHub |
| 认证方式 | OAuth / SSH Key / Personal Token | OAuth |
| 自动同步 | Webhook 自动触发增量更新 | 开启 |
| 同步分支 | 监控指定分支的变更 | main |
| 索引策略 | 完整 / 仅 src / 仅核心模块 | 完整 |

#### 12.3.3 SSH Key 配置

```
┌─────────────────────────────────────────────────────────────────┐
│  SSH Key 配置                                    [生成新密钥]   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  为了访问私有仓库，需要配置 SSH Key：                            │
│                                                                 │
│  1. 生成密钥对                                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  密钥类型: [RSA 4096 ▼]                                  │   │
│  │  注释:     [codepop@your-org.com________________]       │   │
│  │                                                           │   │
│  │  [生成密钥]                                               │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  2. 添加公钥到 GitHub                                           │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  公钥内容:                                               │   │
│  │  ┌─────────────────────────────────────────────────────┐│   │
│  │  │ ssh-rsa AAAAB3NzaC1... codepop@your-org.com      ││   │
│  │  └─────────────────────────────────────────────────────┘│   │
│  │                                                           │   │
│  │  [📋 复制公钥]  [🔗 打开 GitHub Settings]              │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  3. 验证连接                                                    │
│  [测试连接 ─────────────────────────────────────────────────]   │
│  ✓ GitHub 连接成功！已检测到 12 个仓库                          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 12.4 环境变量配置

#### 12.4.1 可视化配置面板

```
┌─────────────────────────────────────────────────────────────────┐
│  环境配置                                              [导入/导出]│
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  快速配置                                                        │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │ 数据库   │ │ 向量服务  │ │ Git 集成 │ │ Agent   │       │
│  │ ⚙️ 3项  │ │ ⚙️ 2项  │ │ ⚙️ 4项  │ │ ⚙️ 5项  │       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
│                                                                 │
│  当前配置                                                        │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ ▼ 数据库配置                                            │   │
│  │   ├─ DATABASE_URL         [postgresql://...] 🔍         │   │
│  │   ├─ PGVECTOR_ENABLED     [true________________] ✓      │   │
│  │   └─ DB_POOL_SIZE        [20___________________] ✓      │   │
│  │                                                         │   │
│  │ ▼ 向量嵌入配置                                          │   │
│  │   ├─ OPENAI_API_KEY      [sk-••••••••••••] 🔍 有效    │   │
│  │   ├─ EMBEDDING_MODEL     [text-embedding-3-small]      │   │
│  │   └─ EMBEDDING_DIM       [1536________________] ✓       │   │
│  │                                                         │   │
│  │ ▼ Git 集成                                              │   │
│  │   ├─ GITHUB_TOKEN        [ghp_••••••••••••] 🔍         │   │
│  │   ├─ GITEE_TOKEN         [未配置_______________] ⚠️     │   │
│  │   └─ AUTO_WEBHOOK        [true________________] ✓      │   │
│  │                                                         │   │
│  │ ▼ 服务配置                                              │   │
│  │   ├─ CODEPOP_HOST        [0.0.0.0____________]          │   │
│  │   ├─ CODEPOP_PORT        [8080________________]        │   │
│  │   └─ LOG_LEVEL           [info_______________]          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  [保存配置]  [应用更改]  [恢复默认]                               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### 12.4.2 预设配置模板

| 场景 | 模板名称 | 主要配置 |
|------|---------|---------|
| 本地开发 | `local-dev` | 内置 PostgreSQL，localhost |
| 小团队 | `small-team` | 共享数据库，GitHub OAuth |
| 企业内部 | `enterprise` | 自托管 DB，LDAP，审计日志 |
| 极致性能 | `performance` | 连接池 50+，HNSW 优化 |

```yaml
# 模板预览 - local-dev
config:
  database:
    url: "postgresql://postgres@localhost:5432/codepop"
    pool_size: 5
  embedding:
    provider: "openai"
    model: "text-embedding-3-small"
  server:
    host: "localhost"
    port: 8080
  features:
    auto_index: true
    watch_files: true
```

### 12.5 Agent 接入配置

#### 12.5.1 Agent 接入向导

```
┌─────────────────────────────────────────────────────────────────┐
│  Agent 接入配置                                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  选择你的 AI 助手                                                │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐              │
│  │ Claude  │ │ Cursor  │ │  VS Code │ │  自定义  │              │
│  │  Code   │ │         │ │  (Copilot)│ │  Agent  │              │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘              │
│                                                                 │
│  你选择了：Claude Code                                           │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  步骤 1：安装 MCP Server                               │   │
│  │                                                         │   │
│  │  在 Claude Code 中运行：                                │   │
│  │  ┌───────────────────────────────────────────────────┐ │   │
│  │  │ $ claude config add mcp-server codepop           │ │   │
│  │  │     npx @codepop/mcp-server                      │ │   │
│  │  └───────────────────────────────────────────────────┘ │   │
│  │  [📋 复制命令]  [自动安装 ▶]                           │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  步骤 2：连接配置                                       │   │
│  │                                                         │   │
│  │  服务地址: [http://localhost:8080_____] 🔍 已连接      │   │
│  │  认证密钥: [••••••••••••••••••_____] [生成新密钥]     │   │
│  │                                                         │   │
│  │  ┌───────────────────────────────────────────────────┐ │   │
│  │  │  自动生成的配置已复制到剪贴板！                     │ │   │
│  │  │  在 Claude Code 中按 Cmd+V 粘贴即可                 │ │   │
│  │  └───────────────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  步骤 3：验证接入                                       │   │
│  │                                                         │   │
│  │  [运行测试查询 ──────────────────────────────────────] │   │
│  │                                                         │   │
│  │  ✓ 连接成功！CodePop 已准备就绪                         │   │
│  │  • 已索引 12 个仓库                                     │   │
│  │  • 可用工具：search_code, goto_definition 等           │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### 12.5.2 Agent 配置模板

| Agent | 配置文件位置 | 配置内容 |
|-------|------------|---------|
| Claude Code | `~/.claude/mcp_servers.json` | MCP Server URL |
| Cursor | `settings.json` | MCP Server + API Key |
| VS Code | `.vscode/mcp.json` | MCP Server 配置 |
| 自定义 | SDK 初始化 | Base URL + API Key |

```json
// Claude Code MCP 配置示例
{
  "mcpServers": {
    "codepop": {
      "command": "npx",
      "args": ["@codepop/mcp-server", "--url", "http://localhost:8080"],
      "env": {
        "CODEPOP_API_KEY": "cp_sk_xxxxxxxxxxxx"
      }
    }
  }
}
```

```typescript
// 自定义 Agent SDK 配置
import { CodePopClient } from '@codepop/sdk';

const client = new CodePopClient({
  baseUrl: 'http://localhost:8080',
  apiKey: 'cp_sk_xxxxxxxxxxxx',  // 界面生成
  timeout: 5000,
  retry: {
    attempts: 3,
    backoff: 'exponential'
  }
});
```

### 12.6 一键部署脚本生成器

#### 12.6.1 部署配置器

```
┌─────────────────────────────────────────────────────────────────┐
│  一键部署脚本生成器                                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  部署目标                                                        │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐              │
│  │ 本地 Mac │ │ Linux   │ │ Windows │ │ 云服务器 │              │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘              │
│                                                                 │
│  选择组件                                                        │
│  ☑ PostgreSQL + pgvector                                       │
│  ☑ CodePop 服务                                                │
│  ☐ Redis (可选，用于缓存)                                        │
│  ☐ Prometheus + Grafana (可选，用于监控)                         │
│                                                                 │
│  生成配置                                                        │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 主机:     [root@your-server.com______]  端口: [22____]  │   │
│  │ SSH 密钥: [~/.ssh/id_rsa ▼]                             │   │
│  │ 域名:     [codepop.your-company.com__]  HTTPS: ☑       │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  [预览部署脚本]  [下载 docker-compose.yml]  [直接部署 ▶]        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### 12.6.2 生成的部署脚本

```bash
#!/bin/bash
# CodePop 一键部署脚本
# 生成时间: 2026-06-19
# 配置: 小团队版

set -e

echo "🚀 开始部署 CodePop..."

# 1. 安装 Docker（如未安装）
if ! command -v docker &> /dev/null; then
    echo "📦 安装 Docker..."
    curl -fsSL https://get.docker.com | sh
fi

# 2. 创建目录
mkdir -p ~/codepop/{data,logs,repos}
mkdir -p ~/codepop/postgres

# 3. 生成配置
cat > ~/codepop/config.yaml << 'EOF'
# CodePop 配置文件
# 通过 Web 界面管理，勿手动修改

server:
  host: "0.0.0.0"
  port: 8080
  mcp_port: 8081

database:
  url: "postgresql://postgres:CHANGE_ME@postgres:5432/codepop"
  pool_size: 20

embedding:
  provider: "openai"
  model: "text-embedding-3-small"
  dimension: 1536

features:
  auto_index: true
  watch_files: true
  sync_interval: 30

security:
  api_key_required: true
EOF

# 4. 启动服务
cat > ~/codepop/docker-compose.yml << 'EOF'
version: '3.8'

services:
  postgres:
    image: ankane/pgvector:pg16
    environment:
      POSTGRES_DB: codepop
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: CHANGE_ME
    volumes:
      - ./postgres:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s

  codepop:
    image: codepop/codepop:latest
    ports:
      - "8080:8080"
      - "8081:8081"
    volumes:
      - ./config.yaml:/app/config.yaml
      - ./repos:/app/repos
      - ./logs:/app/logs
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql://postgres:CHANGE_ME@postgres:5432/codepop

  # 可选：Web 管理界面
  web:
    image: codepop/web:latest
    ports:
      - "3000:3000"
    environment:
      API_URL: http://codepop:8080
    depends_on:
      - codepop

EOF

echo "📁 配置文件已生成在 ~/codepop/"
echo ""
echo "请编辑 ~/codepop/docker-compose.yml 设置安全的密码"
echo "然后运行: cd ~/codepop && docker compose up -d"
echo ""
echo "✓ 部署脚本生成完成！"
```

### 12.7 在线试用（无需安装）

```
┌─────────────────────────────────────────────────────────────────┐
│                    🎮 在线体验 CodePop                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  不想安装？直接在线试用！                                        │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                                                         │   │
│  │    🔗 试用地址: try.codepop.dev                        │   │
│  │                                                         │   │
│  │    ┌─────────────┐  ┌─────────────┐  ┌─────────────┐   │   │
│  │    │ 示例仓库 1  │  │ 示例仓库 2  │  │ 示例仓库 3  │   │   │
│  │    │ React 组件库│  │ Python API │  │ Go 微服务   │   │   │
│  │    │ 10 个文件   │  │ 8 个文件   │  │ 12 个文件   │   │   │
│  │    │ [立即试用] │  │ [立即试用] │  │ [立即试用] │   │   │
│  │    └─────────────┘  └─────────────┘  └─────────────┘   │   │
│  │                                                         │   │
│  │    ⏱️ 会话限制: 30 分钟 | 数据不持久化                   │   │
│  │                                                         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 12.8 Mac 原生客户端

#### 12.8.1 技术选型

| 组件 | 技术选型 | 说明 |
|------|---------|------|
| 框架 | SwiftUI + UIKit | 原生性能 |
| 架构 | MVVM + Combine | 响应式 |
| 网络 | URLSession | 原生 HTTP |
| 本地存储 | UserDefaults + SQLite | 轻量持久化 |
| 发布 | App Store + DMG | 多渠道 |
| 安装包 | Homebrew | `brew install codepop` |

#### 12.8.2 菜单栏常驻

```
┌─────────────────────────────────────────────────────────────────┐
│ 🔍 CodePop                    │ 点击打开主界面                  │
│   连接状态: ✓ 已连接           │                                │
│   索引: 12 个仓库              │                                │
│   P95: 230ms                  │                                │
├─────────────────────────────────────────────────────────────────┤
│   📊 打开仪表盘...              │                                │
│   🔧 设置...                    │                                │
│   📖 帮助文档                   │                                │
├─────────────────────────────────────────────────────────────────┤
│   🚪 退出                      │                                │
└─────────────────────────────────────────────────────────────────┘
```

#### 12.8.3 快速配置界面

```
┌─────────────────────────────────────────────────────────────────┐
│ ◀ │ CodePop                                    [−] [□] [×]     │
├─────────────────────────────────────────────────────────────────┤
│  快速配置                                                        │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │                                                           │ │
│  │  ☑ 启动时自动运行    ☐ 显示菜单栏图标                     │ │
│  │  ☐ 开机自启          ☐ 启用 SSH Tunnels（远程访问）        │ │
│  │                                                           │ │
│  │  数据库: [内置 PostgreSQL ▼]     [更改配置...]             │ │
│  │  API:   [http://localhost:8080]   [测试连接 ✓]           │ │
│  │                                                           │ │
│  │  [打开 Web 管理界面 ➜]                                  │ │
│  │                                                           │ │
│  └───────────────────────────────────────────────────────────┘ │
│                                                                 │
│  仓库                                                        │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │  [+ 添加本地仓库]  [+ 从 GitHub 导入]                     │ │
│  │                                                           │ │
│  │  📁 ~/projects/frontend       TypeScript  ✓ 已索引       │ │
│  │  📁 ~/projects/backend        Python      ✓ 已索引       │ │
│  │  📁 ~/projects/api            Go          ⏳ 索引中...    │ │
│  │                                                           │ │
│  └───────────────────────────────────────────────────────────┘ │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 12.9 API 设计

```typescript
// 配置管理 API
interface ConfigApi {
  // 获取配置
  'GET /api/v1/config': () => FullConfig;

  // 更新配置
  'PUT /api/v1/config': (body: Partial<Config>) => Config;

  // 测试连接
  'POST /api/v1/config/test-db': (body: DbConfig) => TestResult;
  'POST /api/v1/config/test-embedding': (body: EmbeddingConfig) => TestResult;

  // 预设模板
  'GET /api/v1/config/templates': () => ConfigTemplate[];
  'POST /api/v1/config/apply-template': (body: { template: string }) => Config;

  // 导出/导入
  'GET /api/v1/config/export': () => ExportedConfig;
  'POST /api/v1/config/import': (body: ExportedConfig) => ImportResult;
}

// 仓库管理 API
interface RepoApi {
  // 列表
  'GET /api/v1/repos': (params: ListParams) => RepoList;

  // 添加（支持多种方式）
  'POST /api/v1/repos/local': (body: { path: string }) => Repo;
  'POST /api/v1/repos/github': (body: { owner: string; repo: string }) => Repo;
  'POST /api/v1/repos/gitee': (body: { owner: string; repo: string }) => Repo;

  // Git 集成
  'GET /api/v1/github/repos': () => GitHubRepo[];
  'POST /api/v1/github/connect': (body: { code: string }) => GitHubConnection;
  'GET /api/v1/github/webhook-status': () => WebhookStatus;

  // 索引管理
  'POST /api/v1/repos/:id/index': (body: IndexOptions) => IndexTask;
  'GET /api/v1/repos/:id/index/status': () => IndexStatus;
}

// 部署 API
interface DeployApi {
  // 生成部署脚本
  'POST /api/v1/deploy/generate': (body: DeployConfig) => DeployScript;

  // 远程部署
  'POST /api/v1/deploy/execute': (body: { host: string; script: string }) => DeployResult;

  // 健康检查
  'GET /api/v1/health': () => HealthStatus;
  'GET /api/v1/health/detailed': () => DetailedHealth;
}
```

---

## 13. 界面与降级总结

### 13.1 功能对照表

| 功能 | Web 界面 | Mac App | 降级策略 |
|------|---------|---------|---------|
| 仓库管理 | ✅ 完整 | ✅ 完整 | 本地缓存 |
| 实时监控 | ✅ 图表 | ✅ 简化 | 定时刷新 |
| 检索调试 | ✅ 详细 | ✅ 简化 | 结果缓存 |
| 异常告警 | ✅ 推送 | ✅ 通知 | 降级提示 |
| 索引构建 | ✅ 进度 | ✅ 进度 | 后台执行 |
| **配置管理** | ✅ **完整** | ✅ **简化** | **配置缓存** |
| **Git 集成** | ✅ **OAuth** | ✅ **Token** | **手动同步** |
| **一键部署** | ✅ **脚本生成** | ✅ **本地启动** | **Docker** |
| **Agent 接入** | ✅ **向导** | ✅ **复制配置** | **手动配置** |

### 13.2 用户旅程时间线

```
0分钟 ──────────────────────────────────────────────────────────→ 5分钟
   │                                                               │
   ▼                                                               ▼
┌────────────┐    ┌────────────┐    ┌────────────┐    ┌────────────┐
│ 打开界面   │ → │ 选择部署    │ → │ 配置数据库  │ → │ 添加仓库   │
│            │    │ 方式        │    │ (自动检测)  │    │ (GitHub)   │
└────────────┘    └────────────┘    └────────────┘    └────────────┘
                                                                   │
5分钟 ──────────────────────────────────────────────────────────→ 10分钟
   │                                                               │
   ▼                                                               ▼
┌────────────┐    ┌────────────┐    ┌────────────┐    ┌────────────┐
│ 配置       │ → │ Agent      │ → │ 索引构建    │ → │ 开始使用   │
│ Agent      │    │ 接入向导   │    │ (后台)     │    │            │
└────────────┘    └────────────┘    └────────────┘    └────────────┘
```

### 13.3 降级响应时间

| 故障场景 | 检测时间 | 降级切换 | 完全恢复 |
|---------|---------|---------|---------|
| 向量服务故障 | < 1s | < 100ms | 人工介入 |
| 数据库超时 | < 500ms | < 100ms | 自动重试 |
| 网络抖动 | < 2s | < 50ms | 自动重连 |
| 索引损坏 | < 5s | < 1s | 重建索引 |

---

*文档版本：v1.3（新增可视化配置 + 一键部署向导）*
*技术栈：PostgreSQL 16 + pgvector + Docker*
*最后更新：2026-06-19*
