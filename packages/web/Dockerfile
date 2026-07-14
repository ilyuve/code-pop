FROM node:20-slim AS builder

WORKDIR /app

# Install pnpm.
RUN npm install -g pnpm

# Copy root-level config and lockfile.
COPY pnpm-lock.yaml ./

# Copy web package config.
COPY packages/web/package.json ./

# Install dependencies.
RUN pnpm install --config.ignore-scripts=false

# Copy source files.
COPY packages/web/src ./src
COPY packages/web/index.html ./
COPY packages/web/vite.config.ts ./
COPY packages/web/tsconfig.json ./
COPY packages/web/tailwind.config.js ./
COPY packages/web/postcss.config.js ./

# Build the application.
RUN pnpm run build

# Serve with nginx.
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY packages/web/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
