FROM node:22.13.1-alpine3.21 AS deps
WORKDIR /app
COPY package.json package-lock.json tsconfig.base.json ./
COPY apps/customer-web/package.json ./apps/customer-web/package.json
COPY apps/admin-web/package.json ./apps/admin-web/package.json
COPY apps/reseller-web/package.json ./apps/reseller-web/package.json
COPY packages/shared-typescript/package.json ./packages/shared-typescript/package.json
COPY packages/ui/package.json ./packages/ui/package.json
RUN npm ci

FROM deps AS builder
ARG APP_NAME
ARG NEXT_PUBLIC_API_BASE_URL
ARG NEXT_PUBLIC_CUSTOMER_API_BASE_URL
ARG NEXT_PUBLIC_TELEGRAM_BOT_USERNAME
ARG NEXT_PUBLIC_CUSTOMER_APP_NAME
ARG NEXT_PUBLIC_CUSTOMER_FAKE_TELEGRAM=false
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL \
    NEXT_PUBLIC_CUSTOMER_API_BASE_URL=$NEXT_PUBLIC_CUSTOMER_API_BASE_URL \
    NEXT_PUBLIC_TELEGRAM_BOT_USERNAME=$NEXT_PUBLIC_TELEGRAM_BOT_USERNAME \
    NEXT_PUBLIC_CUSTOMER_APP_NAME=$NEXT_PUBLIC_CUSTOMER_APP_NAME \
    NEXT_PUBLIC_CUSTOMER_FAKE_TELEGRAM=$NEXT_PUBLIC_CUSTOMER_FAKE_TELEGRAM
COPY packages ./packages
COPY apps ./apps
RUN chmod -R u+rwX,go+rX /app/packages /app/apps
RUN case "$APP_NAME" in customer-web|admin-web|reseller-web) npm run build -w @vpnsale/$APP_NAME ;; *) echo "Unknown APP_NAME: $APP_NAME" >&2; exit 64 ;; esac

FROM node:22.13.1-alpine3.21 AS runtime
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
RUN addgroup -S vpnsale && adduser -S -G vpnsale vpnsale
ARG APP_NAME
ENV APP_NAME=$APP_NAME
COPY --from=builder --chown=vpnsale:vpnsale /app/package.json /app/package-lock.json ./
COPY --from=builder --chown=vpnsale:vpnsale /app/node_modules ./node_modules
COPY --from=builder --chown=vpnsale:vpnsale /app/apps/${APP_NAME} ./apps/${APP_NAME}
COPY --from=builder --chown=vpnsale:vpnsale /app/packages ./packages
RUN chmod -R u+rwX,go+rX /app/package.json /app/package-lock.json /app/node_modules /app/apps /app/packages
USER vpnsale
RUN test "$(id -u)" -ne 0 && test -r package.json
EXPOSE 3000
WORKDIR /app/apps/${APP_NAME}
CMD ["npm", "run", "start"]
