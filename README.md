# CodePop

面向 AI Agent 的代码语义检索基础设施。基于 FastAPI + pgvector + tree-sitter + sentence-transformers，为 Claude Code、Cursor、Windsurf 等编码助手提供精准的代码上下文。

## 核心特性

- **混合检索**：向量相似度 + 符号匹配 + BM25 全文 + 调用图，四路召回加权融合
- **本地 Embedding**：默认使用 `sentence-transformers/all-MiniLM-L6-v2`，无需 OpenAI
- **增量索引**：git webhook 触发增量更新，文件 hash 去重，调用图增量重建
- **MCP Server**：通过 SSE 协议接入任意支持 MCP 的客户端
- **Benchmark 工具**：量化检索质量与 token 节省效果

## 快速启动

```bash
# 1. 克隆仓库
git clone https://github.com/ilyuve/code-pop.git
cd code-pop

# 2. 启动服务
docker compose up -d

# 3. 等待 backend 初始化完成
docker logs -f codepop-backend

# 4. 访问
#   前端: http://localhost:3000
#   API:  http://localhost:8080/api/health
```

环境变量可在项目根目录创建 `.env` 覆盖：

```env
POSTGRES_PASSWORD=codepop123
GITHUB_WEBHOOK_SECRET=your_secret
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
```

## API 概览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| POST | `/api/repos` | 创建仓库 |
| POST | `/api/repos/:id/index` | 触发索引 |
| POST | `/api/search` | 混合搜索 |
| POST | `/api/search/symbol` | 符号搜索 |
| GET | `/api/search/history` | 搜索历史 |
| GET | `/api/search/history/stats` | 今日统计 |
| POST | `/api/search/benchmark` | 运行评测 |
| GET | `/api/search/benchmark/summary` | 评测汇总 |
| GET | `/mcp/sse` | MCP SSE 端点 |

## MCP 接入

CodePop 内置 MCP Server，暴露以下工具：

- `codepop_search`：语义搜索代码
- `codepop_repos`：列出已索引仓库
- `codepop_symbols`：查看文件符号列表

### Claude Code / Claude Desktop

将 `claude_desktop_config.json` 中的内容合并到 Claude 配置：

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "codepop": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-sse@latest", "http://localhost:8080/mcp/sse"]
    }
  }
}
```

> 若 Claude 原生不支持 SSE MCP，可使用 [mcp-proxy](https://github.com/sparfenov/mcp-proxy) 将 SSE 转为 stdio。

### Cursor

在 Cursor Settings → MCP → Add new MCP server 中：

- **Name**: `codepop`
- **Type**: `sse`
- **URL**: `http://localhost:8080/mcp/sse`

或编辑 `~/.cursor/mcp.json`：

```json
{
  "mcpServers": {
    "codepop": {
      "url": "http://localhost:8080/mcp/sse"
    }
  }
}
```

### Windsurf

在 Windsurf Settings → Cascade → MCP 中添加 SSE server，URL 填 `http://localhost:8080/mcp/sse`。

## 评测与 Benchmark

### 前端评测页面

访问 `http://localhost:3000/benchmark`：

1. 输入一组测试查询（每行一个）
2. 选择仓库和对比模式（使用 CodePop / Baseline）
3. 点击"开始评测"
4. 查看平均耗时、token 消耗、准确率及延迟趋势

### 命令行评测脚本

```bash
cd backend
python -m scripts.benchmark ../benchmark_queries.json --repo-id <uuid> --k 10 --output report.json
```

**Baseline 说明**：`without_codepop` 模式采用朴素关键词匹配（扫描文件内容中的关键词）作为代理基准，用于对比检索效率。它不代表真实 LLM 直接读取整个代码库的 token 消耗，但能有效反映 CodePop 对检索质量和速度的提升。

`benchmark_queries.json` 示例：

```json
[
  {
    "query": "how is authentication handled?",
    "expected_files": ["src/auth.py"],
    "expected_lines": [42]
  }
]
```

## 技术栈

- Python 3.11 / FastAPI / SQLAlchemy 2.0
- PostgreSQL 16 + pgvector
- sentence-transformers（本地 embedding）
- tree-sitter（多语言代码解析）
- React + Vite + Tailwind CSS（前端）

## 许可证

MIT
