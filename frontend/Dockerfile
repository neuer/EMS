# 前端镜像：node 构建 → nginx 托管
# EXC-20260617-001：本项目栈为 Vue3+Vite，Sprint 0 用 npm 构建以保证可重现。
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
