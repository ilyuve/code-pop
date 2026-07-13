FROM node:20-slim AS builder

WORKDIR /app

# Install pnpm.
RUN npm install -g pnpm

# Install dependencies.
COPY package.json pnpm-lock.yaml ./
RUN pnpm install

# Build the application.
COPY . .
RUN pnpm run build

# Serve with nginx.
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
