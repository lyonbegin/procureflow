# The ONE existing Railway n8n main/worker image.
# Upstream n8n 2.44.6 + shared-n8n-studio pinned native canvas Pan patch.
# Deploy this image ONLY into existing 'n8n' and 'procureflow-n8n-worker'
# using the current PostgreSQL, Redis, N8N_ENCRYPTION_KEY and n8n owner.
# No new SQLite database, no new n8n server, no owner bootstrap or extra login.
# Safety: changing branch does not authorize production DB migrations; take a
# verified backup of the existing PostgreSQL and credentials before rollout.
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
# Existing n8n editor implementation: official upstream Vue canvas + pinned shared Pan patch.
ARG SHARED_N8N_STUDIO_COMMIT=999062f1676bdffafa852a36e6c986ef5ce7589f
RUN git clone https://github.com/lyonbegin/shared-n8n-studio.git /tmp/shared-n8n-studio \
    && git -C /tmp/shared-n8n-studio checkout --detach "${SHARED_N8N_STUDIO_COMMIT}" \
    && test "$(git -C /tmp/shared-n8n-studio rev-parse HEAD)" = "${SHARED_N8N_STUDIO_COMMIT}" \
    && node /tmp/shared-n8n-studio/scripts/apply-pan-patch.mjs \
      /src/n8n/packages/frontend/editor-ui/src/features/workflows/canvas/components/Canvas.vue
WORKDIR /src/n8n
# Railway Dockerfile builder does not support BuildKit secret mounts.
# Keep build token-free; build is pinned by upstream SHA and shared Pan SHA.
RUN pnpm install --frozen-lockfile --trust-lockfile \
    && pnpm run build:deploy \
    && test -f compiled/bin/n8n \
    && node -p "require('./compiled/package.json').version" | grep -qx '2.44.6'

# Upstream removes isolated-vm prebuilt binaries. Rebuild for this Node runtime.
FROM builder AS native-modules
RUN set -eux; \
    package_file="$(find /src/n8n/compiled/node_modules/.pnpm -path '*/node_modules/isolated-vm/package.json' -print -quit)"; \
    test -n "$package_file"; \
    cd "$(dirname "$package_file")"; \
    node /usr/local/lib/node_modules/npm/node_modules/node-gyp/bin/node-gyp.js rebuild --release -j 2; \
    test -s build/Release/isolated_vm.node; \
    cp build/Release/isolated_vm.node /tmp/isolated_vm.node

FROM node:26.12.1-bookworm-slim AS runtime
ENV NODE_ENV=production \
    N8N_RELEASE_TYPE=stable \
    SHELL=/bin/sh
RUN apt-get update && apt-get install -y --no-install-recommends \
    tini gosu ca-certificates curl openssl libstdc++6 libgcc-s1 python3 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /home/node
COPY --from=builder --chown=node:node /src/n8n/compiled /usr/local/lib/node_modules/n8n
COPY --from=native-modules /tmp/isolated_vm.node /tmp/isolated_vm.node
RUN set -eux; \
    package_file="$(find /usr/local/lib/node_modules/n8n/node_modules/.pnpm -path '*/node_modules/isolated-vm/package.json' -print -quit)"; \
    test -n "$package_file"; \
    install -D /tmp/isolated_vm.node "$(dirname "$package_file")/build/Release/isolated_vm.node"; \
    rm /tmp/isolated_vm.node
RUN chmod +x /usr/local/lib/node_modules/n8n/bin/n8n \
    && ln -s /usr/local/lib/node_modules/n8n/bin/n8n /usr/local/bin/n8n \
    && mkdir -p /home/node/.n8n \
    && chown -R node:node /home/node
# The custom node is an official n8n extension; its execution is fail-closed
# unless separately authorized. Do not introduce a second execution engine.
COPY --chown=node:node n8n/custom-nodes /home/node/procureflow-custom-nodes
COPY --chown=node:node n8n/operational_manifest.json /home/node/procureflow-custom-nodes/operational_manifest.json
ENV N8N_CUSTOM_EXTENSIONS=/home/node/procureflow-custom-nodes

# Keep the original operational workflow paths used by the existing Railway
# n8n pre-deploy import command; NEVER run the isolated 26-flow bootstrap here.
COPY --chown=node:node n8n/operational /home/node/procureflow-operational-workflows
COPY --chown=node:node n8n/workflows /home/node/procureflow-demo-workflows

# Preserve the existing n8n main start and Railway worker start-command
# override (n8n worker --concurrency=3), owner, PostgreSQL and Redis settings.
# Original Issue #21 candidate's 26-flow/43-gate graph is compiled OFFLINE.
# Include graph files in the existing Main/Worker image; NEVER import them
# into PostgreSQL or create/publish workflows automatically on server startup.
# The actual release requires a DB-backed workflow diff, backup and owner check.
COPY --chown=node:node n8n/operational_manifest.json /home/node/procureflow-operational-manifest.json
COPY --chown=node:node n8n/source-build/compile-native-topology.mjs /home/node/procureflow-native-tools/compile-native-topology.mjs
COPY --chown=node:node n8n/source-build/test-native-topology.mjs /home/node/procureflow-native-tools/test-native-topology.mjs
COPY --chown=node:node n8n/source-build/augment-business-operations.mjs /home/node/procureflow-native-tools/augment-business-operations.mjs
COPY --chown=node:node n8n/source-build/verify-packaged-graph.mjs /home/node/procureflow-native-tools/verify-packaged-graph.mjs
USER node
RUN PF_SOURCE=/home/node PF_OUTPUT=/home/node/compiled-native \
       node /home/node/procureflow-native-tools/compile-native-topology.mjs \
    && PF_SOURCE=/home/node PF_OUTPUT=/home/node/compiled-native \
       node /home/node/procureflow-native-tools/test-native-topology.mjs \
    && PF_SOURCE=/home/node PF_OUTPUT=/home/node/compiled-native \
       node /home/node/procureflow-native-tools/augment-business-operations.mjs \
    && PF_SOURCE=/home/node PF_OUTPUT=/home/node/compiled-native \
       node /home/node/procureflow-native-tools/verify-packaged-graph.mjs
# No DB import, publishing, owner creation, authentication bypass or second n8n.
EXPOSE 5678
ENTRYPOINT ["tini", "--"]
CMD ["n8n", "start"]
