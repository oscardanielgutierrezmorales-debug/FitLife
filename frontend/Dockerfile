# Etapa 1: compilar el frontend
FROM node:24-alpine AS build

WORKDIR /app

COPY package.json ./
RUN npm install --no-audit --no-fund

COPY . .

ARG VITE_API_URL
ENV VITE_API_URL=$VITE_API_URL

RUN npm run build


# Etapa 2: servir la aplicación
FROM node:24-alpine

WORKDIR /app

RUN npm install -g serve

COPY --from=build /app/dist ./dist

ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "serve -s dist -l ${PORT}"]