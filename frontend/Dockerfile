# syntax=docker/dockerfile:1.7
# COGNUANCE web — build the Vite bundle, serve only the static output through Caddy (guide 07 §9).
FROM node:24-bookworm-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY . .
# Build-time, public setting compiled into the bundle (never a secret).
ARG VITE_API_BASE_URL=/api/v1
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM caddy:2.10-alpine
COPY --from=build /app/dist /srv
# The Caddyfile is mounted read-only by compose.deploy.yaml (hosted vs local variant).
