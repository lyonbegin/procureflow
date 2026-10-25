# Dedicated n8n runtime for a separate Railway service.
# The existing Python Dockerfile no longer contains React Flow or DAG code.
FROM docker.n8n.io/n8nio/n8n:2.44.6
USER root
COPY --chown=node:node n8n/workflows /home/node/procureflow-demo-workflows
COPY --chown=node:node n8n/operational /home/node/procureflow-operational-workflows
COPY --chown=node:node n8n/custom_nodes/n8n-nodes-procureflow /home/node/.n8n/custom/node_modules/n8n-nodes-procureflow
USER node
EXPOSE 5678
# n8n main uses the image CMD. For another Railway service override to
# "n8n worker --concurrency=3"; configure same DB/Redis/encryption key.
