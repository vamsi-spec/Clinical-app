FROM node:20-alpine

WORKDIR /app

# Install system dependencies for Prisma
RUN apk add --no-cache openssl libc6-compat

# Install dependencies first (layer caching)
COPY package*.json ./
RUN npm install

# Copy source
COPY . .

# Generate Prisma client
RUN npx prisma generate

EXPOSE 5000

CMD ["sh", "-c", "npx prisma generate && npm run dev"]