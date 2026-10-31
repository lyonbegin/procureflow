# Issue #21: legacy preview URL compatibility only.
# The former Vue Flow/npm/Vite graph renderer MUST NOT be built or deployed.
# This is an unprivileged redirect to the authenticated official n8n editor.
FROM node:22-alpine
WORKDIR /preview
COPY n8n/native-preview/server.mjs /preview/server.mjs
ENV PORT=3000 NODE_ENV=production
USER node
EXPOSE 3000
CMD ["node", "/preview/server.mjs"]
