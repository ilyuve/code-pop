FROM node:20-slim AS builder

WORKDIR /app

# Install pnpm.
RUN npm install -g pnpm

# Copy pnpm workspace config and lockfile from root.
COPY pnpm-workspace.yaml package.json pnpm-lock.yaml ./

# Copy web package.
COPY packages/web ./packages/web

# Install dependencies.
RUN pnpm install

# Build the application.
WORKDIR /app/packages/web
RUN pnpm run build

# Serve with nginx.
FROM nginx:alpine
COPY --from=builder /app/packages/web/dist /usr/share/nginx/html
COPY packages/web/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
