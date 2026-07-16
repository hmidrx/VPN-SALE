FROM node:22-alpine
WORKDIR /app
ARG APP_NAME
COPY package.json tsconfig.base.json ./
COPY packages ./packages
COPY apps/${APP_NAME} ./apps/${APP_NAME}
RUN npm install
RUN npm run build -w @vpnsale/${APP_NAME}
WORKDIR /app/apps/${APP_NAME}
CMD ["npm", "run", "start"]
