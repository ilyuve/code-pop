# CodePop 中文语义检索功能演示部署方案

## 目标

让评委在任何网络环境下，**不需要配置代理、不需要构建镜像、不需要关心 Docker Hub**，只通过两条命令就能启动完整功能。

## 核心思路

使用 **GitHub Container Registry (GHCR)** 预构建镜像，评委只拉取运行，不从源码构建。

评委执行的是：

```bash
docker compose -f docker-compose.demo.yml pull
docker compose -f docker-compose.demo.yml up -d
```

这里拉取的是已经构建好的应用镜像（存在 GHCR），不是 Docker Hub 上的基础镜像。Dockerfile 里的 `python:3.11-slim-bookworm`、`node:20-slim`、`nginx:alpine` 已经在构建时被打包进最终镜像，评委机器上不需要再拉取它们。

## 为什么不会有 Docker Hub 403 问题？

你本地构建失败是因为要直接从 Docker Hub 拉基础镜像。评委使用预构建镜像时：

| 步骤 | 来源 | 是否依赖 Docker Hub |
|------|------|---------------------|
| 拉取 `ghcr.io/ilyuve/codepop-backend:demo` | GHCR | 否 |
| 拉取 `ghcr.io/ilyuve/codepop-web:demo` | GHCR | 否 |
| 拉取 `ghcr.io/ilyuve/codepop-postgres:pg16` | GHCR | 否 |
| 容器内使用 python/node/nginx | 已打包在镜像里 | 否 |

GHCR 在国内通常可以直接访问，不需要 VPN 或镜像源。

## 自动构建：GitHub Actions

仓库已存在 `.github/workflows/docker-build.yml`，每次 push 到 `main`、`dev_625` 或 `feature/chinese-llm-retrieval` 分支时，会自动构建并推送镜像到 GHCR。

针对 `feature/chinese-llm-retrieval` 分支，workflow 会额外生成 `:demo` 标签：

```yaml
tags: |
  type=raw,value=latest,enable=${{ github.ref == 'refs/heads/main' }}
  type=raw,value=demo,enable=${{ github.ref == 'refs/heads/feature/chinese-llm-retrieval' }}
  type=ref,event=branch
  type=ref,event=tag
```

所以只要往 `feature/chinese-llm-retrieval` 分支 push 代码，GitHub Actions 就会自动构建并上传：

```text
ghcr.io/ilyuve/codepop-backend:demo
ghcr.io/ilyuve/codepop-web:demo
```

也可以手动触发：进入仓库 GitHub Actions 页面，选择 `Docker Build`，点击 `Run workflow`，选择 `feature/chinese-llm-retrieval` 分支。

## 评委部署文件

已提供 [docker-compose.demo.yml](docker-compose.demo.yml)：

```yaml
services:
  backend:
    image: ghcr.io/ilyuve/codepop-backend:demo
    # ...
  web:
    image: ghcr.io/ilyuve/codepop-web:demo
    # ...
```

评委不需要看 Dockerfile，不需要本地构建。

## 评委使用说明

### 环境要求

- Docker Engine >= 20.10
- Docker Compose >= 2.0
- 可用端口：3000、8080、5432

### 启动步骤

```bash
# 1. 克隆仓库并切换分支
git clone https://github.com/ilyuve/code-pop.git
cd code-pop
git checkout feature/chinese-llm-retrieval

# 2. 拉取并启动预构建镜像
docker compose -f docker-compose.demo.yml pull
docker compose -f docker-compose.demo.yml up -d

# 3. 等待后端就绪（约 30-60 秒，首次会下载 embedding 模型）
curl http://localhost:18080/health
```

### 访问

- Web UI: http://localhost:13000
- API 文档: http://localhost:18080/docs
- 后端健康检查: http://localhost:18080/health

### 停止

```bash
docker compose -f docker-compose.demo.yml down
```

## 管理员维护说明

### 触发镜像构建

推送代码到 `feature/chinese-llm-retrieval` 分支，GitHub Actions 会自动构建并推送 `:demo` 标签的镜像。

### 本地验证评委同款镜像

```bash
# 拉取并启动和评委完全一致的镜像
docker compose -f docker-compose.demo.yml pull
docker compose -f docker-compose.demo.yml up -d
```

### 更新镜像标签

如果需要给评委提供新的稳定版本，可以修改 workflow 中的 `demo` 标签逻辑，或者使用 Git tag（例如 `v0.3.0-demo`），然后在 `docker-compose.demo.yml` 中更新对应 tag。

## 重要提示

### LLM Provider 配置

本功能依赖 LLM 进行中文语义增强、查询扩展和 Flow Label 生成。评委启动后，需要：

1. 打开 http://localhost:13000/settings
2. 在 LLM Provider 中添加 DeepSeek / GLM / OpenAI 兼容的 provider
3. 配置 API Key、Base URL、Model
4. 打开全局开关（索引增强、查询扩展、Flow Label）

建议准备一份默认 provider 配置示例写入演示文档，例如：

```text
名称：DeepSeek
协议类型：openai_compatible
Base URL：https://api.deepseek.com
Model：deepseek-chat
API Key：sk-xxx
输入成本 / 1K tokens：0.001
输出成本 / 1K tokens：0.002
```

### 演示仓库

建议提前准备一个中小型仓库作为演示素材，避免首次索引耗时过长。评委可以在 Settings 页面添加本地路径或 Git URL。

### 网络说明

- 所有 Docker 镜像均来自 GHCR，不依赖 Docker Hub
- 首次启动时，backend 会从 HuggingFace 镜像站下载 embedding 模型（约 1-2GB）
- 如果评委机器无法访问 `https://hf-mirror.com`，需要额外配置 `HF_ENDPOINT` 环境变量
