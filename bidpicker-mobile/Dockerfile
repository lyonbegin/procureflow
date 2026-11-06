FROM node:22-alpine
ENV NODE_ENV=production
WORKDIR /app
COPY bidpicker-mobile/package.json ./
RUN npm install --no-audit --no-fund
COPY bidpicker-mobile/ ./
RUN npm run build
EXPOSE 8080
CMD ["sh","-c","node server.mjs"]
