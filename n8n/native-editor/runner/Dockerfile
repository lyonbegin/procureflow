# Isolated native n8n CLI runner. NO custom DAG engine. Only 10 immutable safe fixtures.
FROM n8nio/n8n:2.44.6
USER root
RUN mkdir -p /opt/procureflow-scenarios /home/node/.n8n && chown -R node:node /home/node/.n8n
COPY n8n/workflows/S01.json n8n/workflows/S02.json n8n/workflows/S03.json n8n/workflows/S04.json n8n/workflows/S05.json n8n/workflows/S06.json n8n/workflows/S07.json n8n/workflows/S08.json n8n/workflows/S09.json n8n/workflows/S10.json /opt/procureflow-scenarios/
COPY n8n/native-editor/runner/compile-prefixes.mjs /opt/procureflow-prefixes.mjs
COPY n8n/native-editor/runner/server.mjs /opt/procureflow-server.mjs
COPY n8n/native-editor/runner/start.sh /opt/procureflow-start.sh
RUN chmod 755 /opt/procureflow-start.sh
USER node
ENV NODE_ENV=production N8N_DIAGNOSTICS_ENABLED=false N8N_PERSONALIZATION_ENABLED=false N8N_TEMPLATES_ENABLED=false N8N_USER_FOLDER=/home/node/.n8n PORT=3001
EXPOSE 3001
ENTRYPOINT ["tini","--"]
CMD ["/opt/procureflow-start.sh"]
