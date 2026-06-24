FROM node:20-slim AS builder

WORKDIR /app

# Install dependencies.
COPY package.json package-lock.json ./
RUN npm ci

# Build the application.
COPY . .
RUN npm run build

# Serve with nginx.
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
