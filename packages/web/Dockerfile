FROM node:20-slim AS builder

WORKDIR /app

COPY package.json ./

RUN npm install --legacy-peer-deps --network-timeout=600000

COPY tsconfig.json ./
COPY vite.config.ts ./
COPY index.html ./
COPY postcss.config.js ./
COPY tailwind.config.js ./
COPY src ./src
COPY public ./public

RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
