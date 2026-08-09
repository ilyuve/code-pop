#!/usr/bin/env bash
# 安全清空 codepop PostgreSQL 数据库并重建
# 适用场景：需要从头开始索引，或 schema 变更后不愿走迁移脚本
# 注意：本脚本只清空数据库数据，不会清理 Docker 构建缓存

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
BACKUP_DIR="${PROJECT_ROOT}/backups"
DB_CONTAINER="codepop-postgres"
DB_NAME="codepop"
DB_USER="postgres"
BACKEND_SERVICE="backend"

echo "=================================================="
echo "  CodePop 数据库重置脚本"
echo "=================================================="
echo ""
echo "目标数据库: ${DB_NAME}"
echo "PostgreSQL 容器: ${DB_CONTAINER}"
echo "项目根目录: ${PROJECT_ROOT}"
echo ""

# 确认操作
read -r -p "⚠️  此操作会清空 ${DB_NAME} 数据库的所有数据，是否继续？[y/N] " confirm
if [[ "${confirm}" != "y" && "${confirm}" != "Y" ]]; then
    echo "已取消"
    exit 0
fi

# 检查容器是否运行
if ! docker ps --format '{{.Names}}' | grep -q "^${DB_CONTAINER}$"; then
    echo "错误: PostgreSQL 容器 ${DB_CONTAINER} 未运行"
    exit 1
fi

# 创建备份目录
mkdir -p "${BACKUP_DIR}"
BACKUP_FILE="${BACKUP_DIR}/codepop_backup_$(date +%Y%m%d_%H%M%S).sql"

echo ""
echo "[1/5] 备份当前数据库到 ${BACKUP_FILE} ..."
docker exec "${DB_CONTAINER}" pg_dump -U "${DB_USER}" "${DB_NAME}" > "${BACKUP_FILE}" || {
    echo "警告: 备份失败，是否继续？[y/N]"
    read -r confirm_backup
    if [[ "${confirm_backup}" != "y" && "${confirm_backup}" != "Y" ]]; then
        echo "已取消"
        exit 0
    fi
}

echo ""
echo "[2/5] 停止 backend 服务，避免写入冲突 ..."
cd "${PROJECT_ROOT}"
docker compose stop "${BACKEND_SERVICE}"

echo ""
echo "[3/5] 删除并重建数据库 ..."
docker exec -i "${DB_CONTAINER}" psql -U "${DB_USER}" -d postgres <<EOF
DROP DATABASE IF EXISTS ${DB_NAME};
CREATE DATABASE ${DB_NAME};
\c ${DB_NAME};
CREATE EXTENSION IF NOT EXISTS vector;
EOF

echo ""
echo "[4/5] 重新启动 backend 服务 ..."
docker compose up -d "${BACKEND_SERVICE}"

echo ""
echo "[5/5] 等待 backend 完成启动 ..."
sleep 5

echo ""
echo "=================================================="
echo "  数据库重置完成"
echo "=================================================="
echo "备份文件: ${BACKUP_FILE}"
echo ""
echo "请执行以下后续操作："
echo "1. 查看后端日志: docker compose logs -f ${BACKEND_SERVICE} --tail=50"
echo "2. 确认 health check: curl http://localhost:18080/health/deep"
echo "3. 在前端重新创建仓库并索引"
echo ""
echo "注意："
echo "- 本脚本未清理 Docker 构建缓存或镜像"
echo "- 模型文件和向量模型无需重新下载"
echo "- 如果不需要备份，可手动删除 ${BACKUP_DIR} 目录"
