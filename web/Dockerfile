# Stage 1: build the website with Node.
FROM node:22-alpine AS build
WORKDIR /web
# Packages first, in their own layer, so a code change doesn't reinstall them.
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# Stage 2: serve only the built files with nginx. Node isn't in the final image.
FROM nginx:1.29-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 80
