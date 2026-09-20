FROM node:20-alpine
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
ARG NEXT_PUBLIC_API_BASE=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE
ENV PORT=3000
EXPOSE 3000
RUN npm run build
CMD ["sh", "-c", "npx next start -p ${PORT:-3000}"]
