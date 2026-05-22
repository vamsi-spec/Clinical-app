import Redis from "ioredis"
import logger from "../utils/logger.js"

export const redis = new Redis({
    host: process.env.REDIS_HOST || 'redis',
    port: parseInt(process.env.REDIS_PORT || '6379'),
    password: process.env.REDIS_PASSWORD,
    lazyConnect: true,
    retryStrategy: (times) => {
        if (times > 10) {
            logger.error('Redis max retries reached - giving up')
            return null
        }
        return Math.min(times * 200, 2000)
    },
    reconnectOnError: (err) => {
        const targetErrors = ['READONLY', 'ECONNRESET']
        if (targetErrors.some((e) => err.message.includes(e))) {
            return true
        }
        return false
    },
})

redis.on('connect', () => logger.info('Redis connected'))
redis.on('error', (err) => logger.error('Redis error:', err.message))
redis.on('close', () => logger.warn('Redis connection closed'))
redis.on('reconnecting', () => logger.info('Redis reconnecting...'))


export const connectRedis = async () => {
    try {
        await redis.connect()

        await redis.ping()
        logger.info('Redis ping successfult')
    } catch (error) {
        logger.error('Redis connection failed:', error.message)
        logger.warn('Running without Redis — rate limiting and token blacklist disabled')
    }
}


export const blacklistToken = async (token, expiresInSeconds) => {
    try {
        await redis.setex(`blacklist:${token}`, expiresInSeconds, '1')
    } catch (error) {
        logger.error('Failed to blacklist token:', error.message)
    }
}


export const isTokenBlacklisted = async (token) => {
    try {
        const result = await redis.get(`blacklist:${token}`)
        return result === '1'
    } catch (error) {
        logger.error('Failed to check token blacklist:', error.message)
        return false
    }
}