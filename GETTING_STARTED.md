# 🚀 代码波普 (CodePop) - 快速入门指南

> 5 分钟让你的 AI 编程助手读懂你的代码库

---

## ⚡ 方式一：一键 Docker 部署（推荐）

### 1. 克隆项目
```bash
git clone https://github.com/luyemoon/code-pop.git
cd code-pop
```

### 2. 一键部署
```bash
# 方式 A: 自动部署（包含 PostgreSQL）
./scripts/deploy.sh

# 方式 B: 手动部署
cp docker/.env.example .env
# 编辑 .env 设置 OPENAI_API_KEY
docker compose -f docker/docker-compose.yml up -d
```

### 3. 访问服务
- **Web 管理界面**: http://localhost
- **API 文档**: http://localhost:3000/api-docs
- **MCP 服务**: http://localhost:3001/mcp

### 4. 接入 AI Agent

**Claude Code:**
```bash
./scripts/setup-mcp.sh
```

**Cursor (settings.json):**
```json
{
  "mcpServers": {
    "codepop": {
      "url": "http://localhost:3001"
    }
  }
}
```

---

## 💻 方式二：本地开发模式

### 1. 安装依赖
```bash
# 使用 pnpm（推荐）
corepack enable
pnpm install

# 或使用 npm
npm install
```

### 2. 启动 PostgreSQL（Docker）
```bash
./scripts/start-local.sh
```

### 3. 启动服务
```bash
# 启动所有服务（开发模式）
pnpm dev

# 或分别启动
pnpm --filter @codepop/server dev    # API Server (端口 3000)
pnpm --filter @codepop/web dev        # Web 界面 (端口 5173)
```

### 4. 打开浏览器
访问 http://localhost:5173

---

## 📱 方式三：macOS 原生应用

### 1. 下载 DMG
从 [Releases](https://github.com/luyemoon/code-pop/releases) 下载最新版本

### 2. 安装应用
```bash
# 挂载 DMG
hdiutil mount CodePop-x.x.x.dmg

# 复制到 Applications
cp -R "/Volumes/CodePop/CodePop.app" /Applications/

# 卸载 DMG
hdiutil unmount /Volumes/CodePop
```

### 3. 或构建自己
```bash
./scripts/build-macos.sh
```

---

## 🔌 方式四：仅 API 服务（无 Web 界面）

### 1. 使用 Docker（最快）
```bash
docker run -d \
  --name codepop \
  -p 3000:3000 \
  -p 3001:3001 \
  -e DATABASE_URL=postgresql://postgres:password@host:5432/codepop \
  -e OPENAI_API_KEY=sk-xxx \
  codepop/codepop:latest
```

### 2. 或使用现有 PostgreSQL
```bash
# 设置环境变量
export DATABASE_URL=postgresql://user:pass@localhost:5432/codepop
export OPENAI_API_KEY=sk-xxx

# 启动服务
pnpm --filter @codepop/server start
```

---

## 🗄️ 数据库选项

### PostgreSQL（生产推荐）
```bash
# Docker 一键启动
docker run -d \
  --name codepop-postgres \
  -e POSTGRES_DB=codepop \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=your_password \
  -p 5432:5432 \
  -v pgdata:/var/lib/postgresql/data \
  ankane/pgvector:pg16
```

### 连接现有数据库
```bash
# 在 .env 中设置
DATABASE_URL=postgresql://user:password@host:5432/database
```

---

## 🎯 快速使用

### 1. 添加代码仓库
通过 Web 界面或 API：
```bash
curl -X POST http://localhost:3000/api/repos \
  -H "Content-Type: application/json" \
  -d '{"name": "my-project", "path": "/path/to/project"}'
```

### 2. 触发索引
```bash
curl -X POST http://localhost:3000/api/repos/{id}/index
```

### 3. 搜索代码
```bash
curl -X POST http://localhost:3000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query": "用户认证逻辑"}'
```

### 4. MCP 工具调用
```bash
curl -X POST http://localhost:3001 \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "search_code",
      "arguments": {"query": "JWT authentication"}
    }
  }'
```

---

## 🔧 配置说明

### 环境变量
| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DATABASE_URL` | 数据库连接 | `postgresql://...` |
| `OPENAI_API_KEY` | OpenAI API Key | - |
| `EMBEDDING_PROVIDER` | 嵌入服务 | `openai` |
| `CODEPOP_PORT` | API 服务端口 | `3000` |
| `CODEPOP_MCP_PORT` | MCP 服务端口 | `3001` |

### 嵌入服务配置
```bash
# OpenAI（默认）
OPENAI_API_KEY=sk-xxx
EMBEDDING_PROVIDER=openai

# Ollama（本地）
OLLAMA_BASE_URL=http://localhost:11434
EMBEDDING_PROVIDER=ollama

# Cohere
COHERE_API_KEY=xxx
EMBEDDING_PROVIDER=cohere
```

---

## 🆘 常见问题

### Q: Docker 启动失败？
```bash
# 检查 Docker 是否运行
docker ps

# 查看日志
docker compose logs codepop
```

### Q: 数据库连接失败？
```bash
# 确保 PostgreSQL 启动
docker compose up postgres -d

# 检查连接
psql postgresql://postgres:codepop123@localhost:5432/codepop
```

### Q: 索引很慢？
- 首次索引需要处理所有文件，请耐心等待
- 大型仓库可以先只索引部分目录
- 检查网络连接（如果使用 OpenAI API）

### Q: Claude Code 无法连接？
```bash
# 检查 MCP 服务
curl http://localhost:3001/health

# 重新配置
./scripts/setup-mcp.sh
```

---

## 📚 更多文档

- [完整 API 文档](./docs/API.md)
- [MCP 工具列表](./docs/MCP-TOOLS.md)
- [部署文档](./docs/DEPLOYMENT.md)
- [开发指南](./docs/DEVELOPMENT.md)
- [SEO 优化](./docs/SEO-OPTIMIZATION.md)

---

## 🎉 下一步

1. 添加你的第一个代码仓库
2. 触发索引
3. 体验语义搜索
4. 接入你的 AI 编程助手

祝你使用愉快！
