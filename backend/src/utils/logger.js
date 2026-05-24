import winston from "winston";

import path from 'path'


const { combine, timestamp, colorize, printf, json, errors } = winston.format

const devFormat = combine(
    colorize({ all: true }),
    timestamp({ format: 'YYYY-MM-DD HH:mm:ss' }),
    errors({ stack: true }),
    printf(({ level, message, timestamp, stack, ...metadata }) => {
        let log = `${timestamp} [${level}]: ${message}`
        if (stack) log += `\n${stack}`
        if (Object.keys(metadata).length > 0) {
            log += `\n${JSON.stringify(metadata, null, 2)}`
        }
        return log
    })
)


const prodFormat = combine(
    timestamp(),
    errors({ stack: true }),
    json()
)


const transports = [
    // Console — always on
    new winston.transports.Console({
        format: process.env.NODE_ENV === 'production' ? prodFormat : devFormat,
    }),
]


if (process.env.NODE_ENV === 'production' || process.env.LOG_TO_FILE === 'true') {
    transports.push(
        // Error log
        new winston.transports.File({
            filename: path.join('logs', 'error.log'),
            level: 'error',
            format: prodFormat,
            maxsize: 10 * 1024 * 1024, // 10MB
            maxFiles: 5,
        }),
        // Combined log
        new winston.transports.File({
            filename: path.join('logs', 'combined.log'),
            format: prodFormat,
            maxsize: 10 * 1024 * 1024, // 10MB
            maxFiles: 10,
        })
    )
}

const logger = winston.createLogger({
    level: process.env.LOG_LEVEL || 'info',
    transports,
    // Don't exit on handled exceptions
    exitOnError: false,
})

// Morgan stream integration
logger.stream = {
    write: (message) => logger.http(message.trim()),
}

export default logger