import rateLimit from 'express-rate-limit'
import { errorResponse } from '../utils/apiResponse'
import logger from '../utils/logger'


//Auth Rate limiter

export const authLimiter = rateLimit({
    windowMs: 15*60*1000,
    max: 5,
    standardHeaders: true,
    legacyHeaders: false,
    skipSuccessfulRequests: false,
    handler: (req,res)=> {
        logger.warn(`rate limit exceeded on auth route`,{
            ip: req.ip,
            url: req.originalUrl,
            userAgent: req.get('User-Agent')
        })
        return errorResponse(
            res,
            'Too many attempts please try again',
            429
        )
    },
    keyGenerator: (req) => {
        return req.ip || req.connection.remoteAddress
    }
})

//API Rate limiter

export const apiLimiter = rateLimit({
    windowMs: 60*1000,
    max:100,
    standardHeaders:true,
    legacyHeaders: false,
    handler: (req,res)=>{
        logger.warn(`rate limit exceeded on api route`,{
            ip: req.ip,
            url: req.originalUrl,
            userId: req.user?.id || 'unauthenticated',
        })
        return errorResponse(
            res,
            'Too many requests please try again',
            429
        )
    },
    keyGenerator: (req) => {
        if(req.user?.id) return `user:${req.user.id}`
        return req.ip || req.connection.remoteAddress
    }
})

//Upload rate limiter

export const uploadLimiter = rateLimit({
    windowMs: 60*60*1000,
    max: 10,
    standardHeaders: true,
    legacyHeaders: false,
    handler: (req,res)=>{
        logger.warn(`rate limit exceeded on upload route`,{
            ip: req.ip,
            userId: req.user?.id
        })
        return errorResponse(
      res,
      'Upload limit reached. Maximum 10 audio uploads per hour.',
      429
    )

    },
    keyGenerator: (req) => {
        return req.user?.id
      ? `upload:${req.user.id}`
      : req.ip || req.connection.remoteAddress
    }
})