# Code:Pop — 让代码,真正活着。

> **🤖 AI INFRASTRUCTURE** · **代码专用检索基础设施**  
> **LOCAL AI CODE MEMORY** · tree-sitter + BAAI/bge-small + PostgreSQL/pgvector  
> SEMANTIC RECALL · INCREMENTAL INDEX · PRIVACY-FIRST

---

<div align="center">

![Code:Pop Banner](https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt=A%20modern%20pop-art%20style%20banner%20for%20CodePop%20AI%20code%20search%20tool%2C%20featuring%20bright%20pink%20cyan%20yellow%20colors%2C%20geometric%20shapes%2C%20code%20symbols%20floating%2C%20clean%20minimalist%20design%20with%20gradient%20background%2C%20tech%20startup%20aesthetic&image_size=landscape_16_9)

</div>

---

## 🎯 AI 代码检索基础设施 (AI Infrastructure)

**Code:Pop** 是面向 **AI Agent** 的代码专用检索 **AI Infra** 项目。通过混合索引、智能检索与上下文压缩，为 Claude Code、Codex、Cursor 等编码 Agent 提供精准的代码上下文，降低幻觉率，提升代码理解深度。

### ✨ 核心优势

| 特性 | 说明 |
|------|------|
| 🚀 **开箱即用** | Docker 一键部署，5 分钟完成配置 |
| 🎯 **精准检索** | 向量 + 符号 + 图检索的混合索引 |
| 📊 **上下文压缩** | 智能 Token 控制，降低 API 成本 |
| 🔌 **多 Agent 支持** | 原生支持 Claude Code、Cursor、VS Code 等 |
| 🐘 **PostgreSQL + pgvector** | 成熟稳定，运维友好 |
| 🔒 **隐私优先** | 数据留在本机，不上传云端 |

---

## 🚀 快速开始

### 1. 一键启动

```bash
# 克隆仓库
git clone https://github.com/luyemoon/code-pop.git
cd code-pop

# 启动服务
docker compose up -d

# 打开管理界面
open http://localhost:8080
```

### 2. 配置仓库

通过 Web 界面配置：
1. 打开 http://localhost:8080
2. 选择 **快速配置向导**
3. 添加 GitHub/Gitee 仓库或本地代码路径
4. 配置向量嵌入服务（OpenAI / 本地模型）

### 3. 接入 Agent

**Claude Code**：
```bash
claude config add mcp-server codepop npx @codepop/mcp-server
```

**Cursor**（settings.json）：
```json
{
  "mcpServers": {
    "codepop": {
      "url": "http://localhost:8081/mcp"
    }
  }
}
```

---

## 🏗️ 技术架构

```
┌─────────────────────────────────────────────────────────────┐
│                        Agent CLI 层                         │
│  Claude Code │ Cursor │ VS Code │ 自研 Agent                  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      接入层 (MCP / REST)                    │
│  • MCP Server（原生支持 Claude Code）                        │
│  • REST API（兼容 OpenAI 格式）                             │
│  • WebSocket（实时同步）                                    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      检索服务层                             │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐          │
│  │ 意图理解    │ │ 混合检索    │ │ 上下文补全  │          │
│  │ (规则引擎)  │ │ (向量+符号) │ │ (图遍历)   │          │
│  └─────────────┘ └─────────────┘ └─────────────┘          │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                 PostgreSQL + pgvector                       │
│  • 向量索引 (embedding)                                    │
│  • 符号索引 (symbols)                                       │
│  • 调用图关系 (call_graph)                                 │
│  • Git 历史 (git_commits)                                  │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔍 核心功能

### 01. 实时索引 (REAL-TIME INDEXING)

基于 **tree-sitter AST** 解析，函数级切片精准提取代码语义单元，**毫秒级写入 PostgreSQL/pgvector 本地向量库**。Ctrl+S 即同步，工作流零打扰。

```bash
$ codepop watch ~/projects/api-gateway
✓ initial scan: 1,247 files / 41,892 chunks
✓ embedding model: BAAI/bge-small-zh
✓ vector store: ~/.codepop/chroma.db

# 监听文件变更
[12:04:31] SAVE  src/auth/jwt.go
       └ parse_ast() → 3 chunks
       └ embed() → 512-dim
       └ ✓ store() in 23ms
```

### 02. 语义检索 (SEMANTIC SEARCH)

**BAAI/bge-small 嵌入模型**编码代码与查询为同空间向量，理解**代码语义**而非关键词匹配。忘了函数名也能找回来。

```bash
codepop> ask "用户登录的 JWT 验证"

# vectorize query → cosine search
→ found 3 matches in 87ms:

  ★ 0.94  src/auth/jwt_verify.go:42
        // validate token signature ...
  ★ 0.91  api/middleware/auth.go:18
        // extract Bearer token ...
  ★ 0.87  legacy/login/handler.py:7
        // decode_jwt(token) ...
```

### 03. 增量更新 (INCREMENTAL UPDATE)

**git diff + watchdog 文件监听**双引擎，只重新索引**变更的代码块**，不全量扫描。每一次 commit 都让记忆悄悄长大。

```bash
$ git commit -m "refactor auth flow"
# post-commit hook → codepop sync

▸ diff vs HEAD~1:
   +  src/auth/oauth2.go     [+12 chunks]
   ~  src/auth/jwt.go        [~3 chunks]
   -  legacy/auth_old.py     [-1 chunk]

✓ delta indexed in 142ms
✓ total alive: 41,903 chunks
```

---

## 📊 8 项能力矩阵

| 能力 | 说明 |
|------|------|
| **PARSE** 代码解析 | 自动拆解代码结构，精准识别函数、类、方法边界 |
| **VECTOR** 向量化 | 把代码逻辑转化为机器能理解的向量，保留语义而非字面 |
| **SEARCH** 语义检索 | 说人话提问，代码自己跳出来 |
| **RECALL** 关联召回 | 从 controller 一路追到 dao |
| **DIFF** 增量检测 | 代码保存即更新，只处理变化的部分，记忆持续生长 |
| **REUSE** 知识复用 | 越问越懂你，记住你常找的代码 |
| **ALIVE** 实时索引 | Ctrl+S保存即索引，代码库时刻与你同步 |
| **LOCAL** 本地运行 | 数据留在本机，不上传云端 |

---

## 🎭 解决的痛点

### 场景 01: TOKEN 黑洞
> "AI 硬读代码库，Token 烧了 ¥5万，还没找到关键关联。"

- 30 万行 monorepo · 全量塞 context
- 5 轮迭代后 **仍漏掉跨服务调用**

### 场景 02: GREP 失忆
> "grep 搜不到语义，只记得功能，不记得函数名。"

- 想找"超时重试" · 但写的是 **backoffWrapper**
- 翻 12 个 commit 也想不起来

### 场景 03: 调用链断裂
> "改了上游字段，下游三个服务崩了，没人记得调用链。"

- user.id → int 改 string
- **3 个微服务连锁报错** · 凌晨 3 点回滚

---

## 📦 部署方式

### 本地开发

```bash
docker compose up -d
```

### 生产环境

```bash
# 配置环境变量
cp .env.example .env
vim .env

# 启动
docker compose -f docker-compose.prod.yml up -d
```

---

## ⚙️ 配置说明

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DATABASE_URL` | PostgreSQL 连接字符串 | `postgresql://postgres@localhost:5432/codepop` |
| `OPENAI_API_KEY` | OpenAI API Key | 空 |
| `CODEPOP_PORT` | 服务端口 | `8080` |
| `CODEPOP_MCP_PORT` | MCP 端口 | `8081` |

### 向量嵌入配置

支持多种嵌入服务：
- OpenAI（推荐）
- Azure OpenAI
- 本地模型（Ollama）
- Cohere

---

## 📈 性能指标

| 指标 | 目标值 |
|------|--------|
| 查询延迟 P95 | < 500ms |
| Top-5 命中率 | > 85% |
| Token 压缩率 | 60-80% |
| 增量同步延迟 | < 3s |

---

## 🗂️ 项目结构

```
codepop/
├── arch/                    # 技术文档
│   └── postgresql-pgvector-design.md
├── docker/                  # Docker 配置
│   ├── docker-compose.yml
│   └── Dockerfile
├── docs/                    # 用户文档
├── benchmarks/              # 评测数据集
├── src/                     # 源代码
│   ├── data/                # 数据库适配层
│   │   ├── adapter.ts       # 统一接口定义
│   │   ├── adapter-factory.ts # 工厂模式
│   │   ├── postgresql-adapter.ts # PostgreSQL 实现
│   │   ├── sqlite-adapter.ts # SQLite 实现
│   │   └── mock-adapter.ts  # Mock 实现
│   ├── service/             # 业务服务
│   │   └── code-search-service.ts
│   └── index.ts             # 导出入口
├── .github/                 # GitHub 配置
│   ├── ISSUE_TEMPLATE/      # Issue 模板
│   ├── workflows/           # CI/CD
│   └── PULL_REQUEST_TEMPLATE.md
├── README.md
├── LICENSE
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
├── SECURITY.md
└── docker-compose.yml
```

---

## 🤝 贡献指南

欢迎提交 PR 和 Issue！

### 开发环境

```bash
# 安装依赖
npm install

# 编译项目
npm run build

# 运行测试
npm test

# 启动开发服务器
npm run dev
```

---

## 📄 许可证

MIT License

---

## 📞 联系方式

- 官方文档：https://docs.codepop.dev
- GitHub：https://github.com/luyemoon/code-pop
- 问题反馈：https://github.com/luyemoon/code-pop/issues

---

<div align="center">

**POP. ART. CODE. ALIVE.**

</div>