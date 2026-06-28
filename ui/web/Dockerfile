# ================================================================
# ui/web/Dockerfile — multi-stage
#
# 빌드 타겟:
#   docker build --target dev  -t alpha-ui:dev  ui/web/   # Vite dev server (개발)
#   docker build --target prod -t alpha-ui:prod ui/web/   # nginx static (운영)
# ================================================================

# ── dev: Vite dev server ──
FROM node:20-alpine AS dev
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]

# ── build: 정적 자산 빌드 ──
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# ── prod: nginx 로 정적 서빙 ──
FROM nginx:1.27-alpine AS prod
RUN rm /etc/nginx/conf.d/default.conf
COPY <<'NGINX' /etc/nginx/conf.d/app.conf
server {
    listen 80 default_server;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    # SPA 라우팅: 존재하지 않는 경로는 index.html 로 (history mode 지원)
    location / {
        try_files $uri $uri/ /index.html;
    }

    # gzip
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript;
    gzip_min_length 1024;
}
NGINX
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
