import jwt from 'jsonwebtoken'
import { prisma } from '../config/db.js'
import { isTokenBlacklisted } from '../config/redis.js'
import { errorResponse } from '../utils/apiResponse.js'
import logger from '../utils/logger.js'

export const protect = async (req,res,next) => {
    try {
        const token = req.cookies?.accessToken
        if(!token){
            return errorResponse(res,'Access denied', 401)
        }
        //check token is blacklisted in redis
        const blacklisted = await isTokenBlacklisted(token)
        if(blacklisted){
            return errorResponse(res,'Token has been invalidated. Please login again',401)
        }
        let decoded
        try {
            decoded = jwt.verify(token,process.env.JWT_ACCESS_SECRET) 
        } catch (jwtError) {
            if (jwtError.name === 'TokenExpiredError') {
                return errorResponse(res, 'Session expired. Please refresh your token.', 401)
            }
            if (jwtError.name === 'JsonWebTokenError') {
                return errorResponse(res, 'Invalid token. Please log in again.', 401)
            }
            throw jwtError
        }
        const user = await prisma.user.findUnique({
            where: {id: decoded.userId},
            select: {
                id: true,
                email: true,
                firstName: true,
                lastName: true,
                role: true,
                speciality: true,
                assignedDoctorId: true,
                isActive: true 
            },
        })
        if(!user){
            return errorResponse(res,'User not found',404)
        }
        if(!user.isActive){
            return errorResponse(res,'Your account is inactive. Please contact Admin',403)
        }
        req.user = user
        next()
    } catch (error) {
        logger.error(`Auth protect middleware error: ${error.message}`, { stack: error.stack })
        return errorResponse(res, 'Internal server error', 500)
    }
}


export const optionalAuth = async (req, res, next) => {
  try {
    const token = req.cookies?.accessToken
    if (!token) return next() // No token — continue without user

    const blacklisted = await isTokenBlacklisted(token)
    if (blacklisted) return next()

    const decoded = jwt.verify(token, process.env.JWT_ACCESS_SECRET)
    const user = await prisma.user.findUnique({
      where: { id: decoded.userId },
      select: {
        id: true,
        email: true,
        firstName: true,
        lastName: true,
        role: true,
        speciality: true,
        assignedDoctorId: true,
        isActive: true,
      },
    })

    if (user && user.isActive) {
      req.user = user
    }
    next()
  } catch (error) {
    // Silent fail — don't block the request
    next()
  }
}