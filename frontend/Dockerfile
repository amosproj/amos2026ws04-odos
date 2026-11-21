FROM node:22-bookworm-slim
WORKDIR /app/frontend
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# the SBOM sits outside the frontend context; the build reads it from ../sbom.spdx.json (Legal Notices)
COPY --from=repo sbom.spdx.json /app/sbom.spdx.json
RUN npm run build
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173", "--strictPort"]
