FROM node:22-alpine AS build

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json /app/frontend/
WORKDIR /app/frontend
RUN npm ci

COPY frontend/ /app/frontend/

ARG VITE_API_URL=http://localhost:5173
ENV VITE_API_URL=${VITE_API_URL}

RUN npm run build

FROM nginx:1.27-alpine

COPY --from=build /app/frontend/dist /usr/share/nginx/html
RUN printf '%s\n' \
  'server {' \
  '    listen 5173;' \
  '    server_name _;' \
  '' \
  '    root /usr/share/nginx/html;' \
  '    index index.html;' \
  '' \
  '    location / {' \
  '        try_files $uri $uri/ /index.html;' \
  '    }' \
  '' \
  '    location /api/ {' \
  '        proxy_pass http://backend:8000/api/;' \
  '        proxy_http_version 1.1;' \
  '        proxy_set_header Host $host;' \
  '        proxy_set_header X-Real-IP $remote_addr;' \
  '        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;' \
  '        proxy_set_header X-Forwarded-Proto $scheme;' \
  '    }' \
  '' \
  '    location /v1/ {' \
  '        proxy_pass http://backend:8000/v1/;' \
  '        proxy_http_version 1.1;' \
  '        proxy_set_header Host $host;' \
  '        proxy_set_header X-Real-IP $remote_addr;' \
  '        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;' \
  '        proxy_set_header X-Forwarded-Proto $scheme;' \
  '    }' \
  '' \
  '    location = /openapi.json {' \
  '        proxy_pass http://backend:8000/openapi.json;' \
  '    }' \
  '' \
  '    location /docs {' \
  '        proxy_pass http://backend:8000/docs;' \
  '    }' \
  '' \
  '    location /redoc {' \
  '        proxy_pass http://backend:8000/redoc;' \
  '    }' \
  '}' \
  > /etc/nginx/conf.d/default.conf

EXPOSE 5173

CMD ["nginx", "-g", "daemon off;"]
