FROM node:20-slim AS builder

WORKDIR /app

RUN npm install -g pnpm

# 安装编译原生模块所需的系统工具（esbuild 等）
RUN apt-get update && apt-get install -y \
    python3 \
    make \
    g++ \
    && rm -rf /var/lib/apt/lists/*

COPY pnpm-workspace.yaml package.json pnpm-lock.yaml ./
COPY packages/web ./packages/web

RUN pnpm install --frozen-lockfile

WORKDIR /app/packages/web

RUN pnpm run build

RUN ls -la dist

FROM nginx:alpine
COPY --from=builder /app/packages/web/dist /usr/share/nginx/html
COPY packages/web/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
