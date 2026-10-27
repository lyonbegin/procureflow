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
    tini ca-certificates curl openssl libstdc++6 libgcc-s1 python3 \
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
COPY --chown=node:node n8n/operational /home/node/procureflow-operational-workflows
COPY --chown=node:node n8n/workflows /home/node/procureflow-demo-workflows
COPY --chown=node:node n8n/operational_manifest.json /home/node/procureflow-operational-manifest.json
COPY --chown=node:node n8n/source-build/compile-native-topology.mjs /usr/local/bin/procureflow-compile-topology
COPY --chown=node:node n8n/source-build/test-native-topology.mjs /usr/local/bin/procureflow-test-topology
COPY --chown=node:node n8n/source-build/bootstrap-workflows.sh /usr/local/bin/procureflow-n8n-bootstrap
RUN chmod 755 /usr/local/bin/procureflow-n8n-bootstrap
USER node
EXPOSE 5678
ENTRYPOINT ["tini", "--"]
CMD ["/usr/local/bin/procureflow-n8n-bootstrap"]
