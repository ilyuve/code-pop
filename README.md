<!--
CodePop 代码波普 - SEO Keywords
代码检索, AI代码检索, 向量数据库, pgvector, 语义搜索, Claude Code, Cursor AI, AI Agent, 代码索引, 代码搜索, 代码理解, RAG, 代码RAG, 代码向量化, Code Search, Semantic Code Search, Vector Database, AI Infrastructure
-->

# Code:Pop — 让代码，真正活着。

> **中文名：代码波普** · **代码，真正活着**  
> **🤖 AI INFRASTRUCTURE** · **代码专用检索基础设施**

---

<div align="center">

![Code:Pop 代码波普 Banner](https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt=A%20modern%20pop-art%20style%20banner%20for%20CodePop%20AI%20code%20search%20tool%2C%20featuring%20bright%20pink%20cyan%20yellow%20colors%2C%20geometric%20shapes%2C%20code%20symbols%20floating%2C%20clean%20minimalist%20design%20with%20gradient%20background%2C%20tech%20startup%20aesthetic&image_size=landscape_16_9)

</div>

---

## 🎯 代码波普 (Code:Pop) — AI 代码检索基础设施

**代码波普（Code:Pop）** 是面向 **AI Agent** 的代码专用检索 **AI Infra** 项目。通过混合索引、智能检索与上下文压缩，为 Claude Code、Codex、Cursor 等编码 Agent 提供精准的代码上下文，降低幻觉率，提升代码理解深度。

> 💡 **代码波普**：让你的代码库像人一样"记住"每一个函数、每一次变更。AI 提问，代码自己"跳"出来。

### ✨ 核心优势

| 特性 | 说明 |
|------|------|
| 🚀 **开箱即用** | Docker Compose 一键部署，5 分钟完成配置 |
| 🎯 **精准检索** | 向量 + 符号 + BM25 + 调用图 四路召回混合排序 |
| 📊 **上下文压缩** | 函数级分块，超长函数按 200 行切分 |
| 🔌 **多 Agent 支持** | REST API + WebSocket + MCP Server |
| 🐘 **PostgreSQL + pgvector** | 768 维向量，IVFFlat 索引 |
| 🔒 **隐私优先** | 本地 sentence-transformers 模型，不依赖 OpenAI |

---

## 🚀 快速开始

### 环境要求

- Docker + Docker Compose
- Git

### 一键部署

```bash
git clone https://github.com/luyemoon/code-pop.git
cd code-pop
cp .env.example .env
# 按需编辑 .env，然后启动
docker compose up --build -d
```

服务启动后：

- Web UI: http://localhost:3000
- REST API: http://localhost:8080
- API 文档: http://localhost:8080/docs
- WebSocket: ws://localhost:8080/ws
- MCP SSE: http://localhost:8080/mcp/sse

### 本地开发（Python 后端）

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 启动 PostgreSQL（可用 docker compose up -d postgres）
python scripts/init_db.py
uvicorn main:app --reload --host 0.0.0.0 --port 8080
```

### 本地开发（React 前端）

```bash
cd packages/web
npm install
npm run dev
```

---

## 📡 API 端点

### 仓库管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/repos` | 创建仓库 `{name, git_url}` |
| GET | `/api/repos` | 仓库列表 |
| GET | `/api/repos/{id}` | 仓库详情 |
| DELETE | `/api/repos/{id}` | 删除仓库（级联删除文件/符号/向量） |
| POST | `/api/repos/{id}/index` | 手动触发索引 |
| GET | `/api/repos/{id}/files` | 仓库文件列表 |
| GET | `/api/repos/{id}/symbols` | 仓库符号列表 |

### 检索

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/search` | 混合检索 `{query, repo_id?, limit?}` |
| POST | `/api/search/symbol` | 符号搜索 `{query, repo_id?, limit?}` |
| GET | `/api/search/history` | 搜索历史 |

### Webhook & WebSocket

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/webhook/github` | 接收 GitHub push 事件 |
| WS | `/ws` | 索引进度实时推送 |

### MCP

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/mcp/sse` | MCP Server SSE 事件流 |

MCP 暴露工具：

- `codepop_search(query, repo_id?, limit?)`
- `codepop_repos()`
- `codepop_symbols(repo_id, file_path)`

---

## ⚙️ 配置说明

复制 `.env.example` 为 `.env` 并按需修改：

```bash
# 数据库
DATABASE_URL=postgresql://postgres:codepop123@localhost:5432/codepop
POSTGRES_PASSWORD=codepop123

# GitHub Webhook 签名密钥（可选）
GITHUB_WEBHOOK_SECRET=your-webhook-secret

# 本地嵌入模型
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2

# 代码存储目录
REPOS_DIR=./repos

# API 端口
API_HOST=0.0.0.0
API_PORT=8080
```

---

## 🧠 架构概览

```
用户提交 GitHub 仓库地址
        ↓
POST /api/repos 创建仓库记录
        ↓
后台启动索引任务（WebSocket 推送进度）
        ↓
git clone / git pull 代码到本地目录
        ↓
tree-sitter 遍历文件 → 提取符号（函数/类/接口）
        ↓
按符号切分 chunk（函数级优先，超长按 200 行切分）
        ↓
sentence-transformers 生成 768 维 embedding
        ↓
写入 PostgreSQL + pgvector
        ↓
用户通过 MCP 或 REST 查询
        ↓
四路召回（向量 + 符号 + BM25 + 调用图）混合排序
        ↓
返回带代码片段和行号的检索结果
```

---

## 🤝 接入 AI Agent

### Cursor / Windsurf MCP 配置

在 MCP 配置中添加：

```json
{
  "mcpServers": {
    "codepop": {
      "url": "http://localhost:8080/mcp/sse"
    }
  }
}
```

### GitHub Webhook 配置

在仓库 Settings → Webhooks 中添加：

- Payload URL: `http://your-server/webhook/github`
- Content type: `application/json`
- Secret: 与 `.env` 中 `GITHUB_WEBHOOK_SECRET` 一致
- 选择 `Just the push event`

---

## 📄 License

MIT License © CodePop Team
