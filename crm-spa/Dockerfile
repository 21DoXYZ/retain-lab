# CRM-SPA (Next.js) — multi-stage: собираем в одном слое, отдаём в тонком.
#
# NEXT_PUBLIC_* нужны именно на этапе BUILD: Next вшивает их в клиентский бандл.
# Поэтому они приходят аргументами (см. docker-compose.yml), а не только env
# рантайма — иначе в браузер уехали бы пустые значения.
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

ARG NEXT_PUBLIC_SUPABASE_URL
ARG NEXT_PUBLIC_SUPABASE_ANON_KEY
ARG NEXT_PUBLIC_FLASK_API_URL
ENV NEXT_PUBLIC_SUPABASE_URL=$NEXT_PUBLIC_SUPABASE_URL \
    NEXT_PUBLIC_SUPABASE_ANON_KEY=$NEXT_PUBLIC_SUPABASE_ANON_KEY \
    NEXT_PUBLIC_FLASK_API_URL=$NEXT_PUBLIC_FLASK_API_URL \
    NEXT_TELEMETRY_DISABLED=1

RUN npm run build

# ── рантайм: только standalone-сборка, без исходников и node_modules целиком ──
FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0

RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001

# output: "standalone" кладёт сюда минимальный сервер + только нужные зависимости
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
