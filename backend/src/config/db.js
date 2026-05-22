import { PrismaClient } from '@prisma/client'
import logger from "../utils/logger.js"

//singleton-pattern   prevent multiple prisma instances during hot reload
const globalForPrisma = globalThis

export const prisma =
    globalForPrisma.prisma ??
    new PrismaClient({
        log: [
            { level: 'query', emit: 'event' },
            { level: 'error', emit: 'stdout' },
            { level: 'warn', emit: 'stdout' },
        ],
    })

// Log slow queries in development
if (process.env.NODE_ENV === 'development') {
    prisma.$on('query', (e) => {
        if (e.duration > 2000) {
            logger.warn(`Slow query detected (${e.duration}ms): ${e.query}`)
        }
    })
}

if (process.env.NODE_ENV !== 'production') {
    globalForPrisma.prisma = prisma
}

export const connectDB = async () => {
    try {
        await prisma.$connect()
        logger.info('PostgreSQL connected via Prisma')
    } catch (error) {
        logger.error('PostgreSQL connection failed:', error)
        process.exit(1)
    }
}
