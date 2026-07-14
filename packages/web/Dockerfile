FROM node:20-slim AS builder

WORKDIR /app

RUN npm install -g pnpm

COPY pnpm-workspace.yaml package.json pnpm-lock.yaml ./

COPY packages/web ./packages/web

RUN pnpm install --config.ignore-scripts=false --network-timeout=600000

WORKDIR /app/packages/web

RUN pnpm exec tsc --noEmit

RUN pnpm run build

RUN ls -la dist

FROM nginx:alpine
COPY --from=builder /app/packages/web/dist /usr/share/nginx/html
COPY packages/web/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
