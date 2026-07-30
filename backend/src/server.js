import express from 'express'
import dotenv from 'dotenv'
import http from 'http'
import helmet from 'helmet'
import cors from 'cors'
import cookieParser from 'cookie-parser'
import morgan from 'morgan'
import { Server } from 'socket.io'

import logger from './utils/logger.js'
import { connectDB } from './config/db.js'
import { connectRedis } from './config/redis.js'
import { errorResponse } from './utils/apiResponse.js'

import { ensureTempDir } from './middleware/upload.middleware.js'

import authRouter from './routes/auth.routes.js'
import patientRouter from './routes/patient.route.js'
import transferRouter from './routes/transfer.routes.js'
import appointmentRouter from './routes/appointment.routes.js'
import visitRouter from './routes/visit.routes.js'

import startPipelineConsumer from './consumers/pipelineResultConsumer.js'
import { disconnectKafka } from './config/kafka.js'

import { setIO } from './services/socketRelay.services.js'
import { registerVisitSocketHandlers } from './sockets/visitSocket.js'
import { startPipelineProgressConsumer } from './consumers/pipelineProgressConsumer.js'
import { startPipelineResultConsumer } from './consumers/pipelineResultConsumer.js'
import { disconnectKafka } from './config/kafka.js'


dotenv.config()

const PORT = process.env.PORT || 5000

export const app = express()
export const httpServer = http.createServer(app)


export const io = new Server(httpServer, {
    cors: {
        origin: process.env.FRONTEND_URL || 'http://localhost:3000',
        credentials: true,
    }
})

setIO(io);
registerVisitSocketHandlers(io);




app.use((req, _res, next) => {
    req.io = io
    next()
})

app.use(helmet({
    crossOriginResourcePolicy: { policy: 'cross-origin' },
}))


app.use(cors({
    origin: process.env.FRONTEND_URL || 'http://localhost:3000',
    credentials: true,
    methods: ['GET', 'POST', 'PUT', 'DELETE', 'PATCH'],
    allowedHeaders: ['Content-Type', 'Authorization'],
}))


app.use(express.json({ limit: '10mb' }))
app.use(express.urlencoded({ extended: true, limit: '10mb' }))
app.use(cookieParser())
app.use(morgan('combined', { stream: logger.stream }))


app.get('/api/health', (_req, res) => {
    res.status(200).json({
        success: true,
        message: 'Clinical Note Platform API is running',
        environment: process.env.NODE_ENV,
        timestamp: new Date().toISOString(),
    })
})

io.on('connection', (socket) => {
    logger.info(`User connected: ${socket.id}`)

    socket.on('join-visit', (visitId) => {
        socket.join(`visit-${visitId}`)
        logger.info(`Socket ${socket.id} joined room: visit-${visitId}`)
    })

    socket.on('disconnect', () => {
        logger.info(`User disconnected: ${socket.id}`)
    })
})

//Routes
app.use('/api/auth',authRouter)
app.use('/api/patients',patientRouter)
app.use('/api/appointments',appointmentRouter)
app.use('/api/transfers',transferRouter)
app.use('/api/visits',visitRouter)

app.use((req, res) => {
    errorResponse(res, `Route ${req.method} ${req.originalUrl} not found`, 404)
})


app.use((err, req, res, _next) => {
    logger.error('Unhandled error:', {
        message: err.message,
        stack: err.stack,
        url: req.originalUrl,
        method: req.method,
    })
    errorResponse(res, err.message || 'Internal server error', err.status || 500, err)
})

const startServer = async () => {
    try {
        await connectDB()
        await connectRedis()
        await ensureTempDir()

        await startPipelineConsumer();

        await startPipelineProgressConsumer();
        await startPipelineResultConsumer();


        httpServer.listen(PORT, () => {
            logger.info(`Server running on port ${PORT} - ${process.env.NODE_ENV}`)
            logger.info(`Environment: ${process.env.NODE_ENV}`)
            logger.info(`Clinical Note Intelligence Platform ready`)
        })

        httpServer.listen(process.env.PORT || 5000, () => {
      logger.info(`Server running on port ${process.env.PORT || 5000}`);
      logger.info('Socket.IO ready for visit room subscriptions');
    });
    } catch (error) {
        logger.error('Server failed to start:', error)
        process.exit(1)
    }
}





process.on('unhandledRejection', (reason, promise) => {
    logger.error('Unhandled Rejection at:', promise, 'reason:', reason)
    process.exit(1)
})

process.on('uncaughtException', (error) => {
    logger.error('Uncaught Exception:', error)
    process.exit(1)
})

process.on('SIGTERM', async () => {
    logger.info('SIGTERM received — shutting down gracefully');
    await disconnectKafka();
    io.close();
    httpServer.close(() => {
        logger.info('HTTP server closed')
        process.exit(0)
    })
})

startServer()