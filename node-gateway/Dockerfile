FROM node:24-alpine

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --production
COPY . .

RUN mkdir -p /root/.wechat-quark-bot

CMD ["node", "src/index.js"]
