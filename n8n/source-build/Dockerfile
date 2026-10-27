# Build actual upstream n8n GitHub source (NOT a FROM n8nio/n8n image).
# Isolated evaluation image: never replace a production n8n service until this
# build, runtime smoke tests, DB compatibility, and backup/rollback are verified.
FROM node:26.12.1-bookworm-slim AS builder
ENV CI=true \
    NODE_OPTIONS=--max-old-space-size=6144 \
    PNPM_HOME=/opt/pnpm
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git python3 make g++ pkg-config cmake libssl-dev \
    && rm -rf /var/lib/apt/lists/*
RUN npm install -g pnpm@12.4.2
ARG N8N_SOURCE_REF=n8n@2.44.6
ARG N8N_SOURCE_SHA=b58d9e89d60e9a3485bb511c5091d8be0d9511e4
RUN git clone --depth 1 --branch "${N8N_SOURCE_REF}" \
      https://github.com/n8n-io/n8n.git /src/n8n \
    && test "$(git -C /src/n8n rev-parse HEAD)" = "${N8N_SOURCE_SHA}"
WORKDIR /src/n8n
# Official upstream production builder generates ./compiled from original source.
RUN pnpm install --frozen-lockfile --trust-lockfile \
    && pnpm run build:deploy \
    && test -f compiled/bin/n8n \
    && node -p "require('./compiled/package.json').version" | grep -qx '2.44.6'

FROM node:26.12.1-bookworm-slim AS runtime
ENV NODE_ENV=production \
    N8N_RELEASE_TYPE=stable \
    SHELL=/bin/sh
RUN apt-get update && apt-get install -y --no-install-recommends \
    tini ca-certificates curl openssl libstdc++6 libgcc-s1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /home/node
COPY --from=builder --chown=node:node /src/n8n/compiled /usr/local/lib/node_modules/n8n
RUN chmod +x /usr/local/lib/node_modules/n8n/bin/n8n \
    && ln -s /usr/local/lib/node_modules/n8n/bin/n8n /usr/local/bin/n8n \
    && mkdir -p /home/node/.n8n \
    && chown -R node:node /home/node
COPY --chown=node:node n8n/operational /home/node/procureflow-operational-workflows
COPY --chown=node:node n8n/workflows /home/node/procureflow-demo-workflows
USER node
EXPOSE 5678
ENTRYPOINT ["tini", "--"]
CMD ["n8n"]
