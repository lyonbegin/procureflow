# Display actual native n8n workflow JSON via n8n's underlying Vue Flow renderer.
# Read-only viewer, never a competing execution engine.
FROM node:22-alpine AS frontend
WORKDIR /preview
COPY n8n/native-preview/package.json ./
RUN npm install --no-audit --no-fund
COPY n8n/native-preview/index.html ./index.html
COPY n8n/native-preview/src ./src
RUN npm run build
FROM node:22-alpine
WORKDIR /preview
COPY --from=frontend /preview/dist ./dist
COPY n8n/native-preview/server.mjs ./server.mjs
COPY n8n/operational ./workflows/operational
COPY n8n/workflows ./workflows/scenarios
ENV PORT=3000 NODE_ENV=production
EXPOSE 3000
CMD ["node", "server.mjs"]
