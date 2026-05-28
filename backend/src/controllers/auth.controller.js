import bcrypt from "bcryptjs";
import jwt from "jsonwebtoken";
import {prisma} from "../config/db.js";
import { redis,blacklistToken,isTokenBlacklisted } from "../config/redis.js";
import { successResponse,errorResponse } from "../utils/apiResponse.js";
import logger from "../utils/logger.js";

const ACCESS_COOKIE_OPTIONS = {
  httpOnly: true,
  secure: process.env.NODE_ENV === 'production',
  sameSite: process.env.NODE_ENV === 'production' ? 'strict' : 'lax',
  maxAge: 15 * 60 * 1000,
}

const REFRESH_COOKIE_OPTIONS = {
  httpOnly: true,
  secure: process.env.NODE_ENV === 'production',
  sameSite: process.env.NODE_ENV === 'production' ? 'strict' : 'lax',
  maxAge: 7 * 24 * 60 * 60 * 1000,
  path: '/api/auth/refresh',
}

const generateAccessToken = (userId,role) => {
    return jwt.sign(
        {userId,role},
        process.env.JWT_ACCESS_SECRET,
        {expiresIn: process.env.JWT_ACCESS_EXPIRES_IN || "15m"}
    )
}

const generateRefreshToken = (userId) => {
    return jwt.sign(
        {userId},
        process.env.JWT_REFRESH_SECRET,
        { expiresIn: process.env.JWT_REFRESH_EXPIRES_IN || "7d" }
    );
};


const sanitizeUser = (user) => {
    const {passwordHash, ...safeUser} = user
    return safeUser
}

//Register
//POST /api/auth/register


export const register = async (req, res) => {
    try {
        const {
            email,
            password,
            firstName,
            lastName,
            role,
            speciality,
            assignedDoctorId,
        } = req.body;

        const existingUser = await prisma.user.findUnique({
            where: { email },
        });

        if (existingUser) {
            return errorResponse(res,'Email already registered',409)
        }

        if(role === 'NURSE' && assignedDoctorId) {
            const doctor = await prisma.user.findUnique({
                where: {id: assignedDoctorId},
                select: {id: true,role: true,isActive: true},
            })

            if(!doctor){
                return errorResponse(res,'Assigned doctor not fount.',404)
            }

            if(doctor.role !== 'DOCTOR'){
                return errorResponse(res,'assignedDoctorId must belong to a Doctor.',400)
            }
            if(!doctor.isActive) {
                return errorResponse(res,'Assigned doctor account is inactive.',400)
            }
        }
        const passwordHash = await bcrypt.hash(password, 12);

        const user = await prisma.user.create({
            data: {
                email,
                passwordHash,
                firstName,
                lastName,
                role,
                speciality: role === "DOCTOR" ? speciality : null,
                assignedDoctorId: role === "NURSE" ? assignedDoctorId : null,
            },
        });

        logger.info(`New user registered: ${user.email} (${user.role})`)

    return successResponse(
      res,
      sanitizeUser(user),
      'Registration successful.',
      201
    )
  } catch (error) {
    logger.error('Register error:', error)
    return errorResponse(res, 'Registration failed.', 500, error)
  }
}


//Login 
//POST /api/auth/login

export const login = async (req, res) => {
    try {
        const { email, password } = req.body;

        const user = await prisma.user.findUnique({
            where: { email },
        });

        if (!user) {
            return errorResponse(res, 'Invalid email or password.', 401)
        }

        if (!user.isActive) {
            return errorResponse(
                res,
                'Account has been deactivated. Contact your administrator.',
                403
            )
        }

        const isPasswordMatched = await bcrypt.compare(password, user.passwordHash);

        if (!isPasswordMatched) {
            logger.warn(`Failed login attempt for: ${email}`)
            return errorResponse(res, 'Invalid email or password.', 401)
        }

        const accessToken = generateAccessToken(user.id, user.role);
        const refreshToken = generateRefreshToken(user.id);

        // store refresh token in redis

        await redis.setex(
            `refresh:${refreshToken}`,
            7*24*60*60, //7 days
            user.id
        )

        await prisma.user.update({
            where: {id: user.id},
            data: {lastLoginAt: new Date()}
        })

        res.cookie('accessToken',accessToken,ACCESS_COOKIE_OPTIONS)
        res.cookie('refreshToken',refreshToken,REFRESH_COOKIE_OPTIONS)

        return successResponse(
            res,
            {
                user: sanitizeUser(user),
                accessToken,
            },
            'Login successful'
        )


    }
    catch (error) {
        logger.error('Login error:', error)
    return errorResponse(res, 'Login failed.', 500, error)
    }
};

//Refresh token
//POST /api/auth/refresh

export const refresh = async (req,res) => {
    try {
        const refreshToken = req.cookies?.refreshToken

        if(!refreshToken){
            return errorResponse(res,'No refresh token provided.',401)
        }
        const blacklisted = await isTokenBlacklisted(refreshToken)

        if(blacklisted){
            return errorResponse(res,'Refresh token is INVALID. Please login again',401)
        }

        let decoded 
        try {
      decoded = jwt.verify(refreshToken, process.env.JWT_REFRESH_SECRET)
    } catch (jwtError) {
      if (jwtError.name === 'TokenExpiredError') {
        return errorResponse(res, 'Refresh token expired. Please log in again.', 401)
      }
      return errorResponse(res, 'Invalid refresh token.', 401)
    }

    const storedUserId = await redis.get(`refresh:${refreshToken}`)

    if (!storedUserId || storedUserId !== decoded.userId) {
      return errorResponse(res, 'Refresh token not recognized. Please log in again.', 401)
    }

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

    if (!user || !user.isActive) {
      return errorResponse(res, 'User not found or deactivated.', 401)
    }

    //Issue new access token
    const newAccessToken = generateAccessToken(user.id,user.role)

    const newRefreshToken = generateRefreshToken(user.id)

    await redis.del(`refresh:${refreshToken}`)

    await redis.setex(
        `refresh:${newRefreshToken}`,
        7*24*60*60,
        user.id
    )

    res.cookie('accessToken', newAccessToken, ACCESS_COOKIE_OPTIONS)
    res.cookie('refreshToken', newRefreshToken, REFRESH_COOKIE_OPTIONS)

    return successResponse(
      res,
      { accessToken: newAccessToken, user },
      'Token refreshed successfully.'
    )

        
    } catch (error) {
        logger.error('Refresh token error:', error)
    return errorResponse(res, 'Token refresh failed.', 500, error)
    }
}


//LOGOUT
//POST /api/auth/logout



export const logout = async (req, res) => {
    try {
       const accessToken = req.cookies?.accessToken
       const refreshToken = req.cookies?.refreshToken

       if(accessToken){
        try {
            const decoded = jwt.decode(accessToken)
            if(decoded?.exp) {
                const expirySeconds = decoded.exp - Math.floor(Date.now() / 1000)
                if(expirySeconds > 0)
                await blacklistToken(accessToken,expirySeconds)
            }
        } catch (error) {
            logger.warn('Failed to blacklist token',error.message)
        }
       }

       if(refreshToken){
        try {
            await redis.del(`refresh:${refreshToken}`)
        } catch (error) {
            logger.warn('Failed to remove refresh token',error.message)
        }
       }

    res.clearCookie('accessToken', {
        httpOnly: true,
        secure: process.env.NODE_ENV === 'production',
        sameSite: process.env.NODE_ENV === 'production' ? 'strict' : 'lax',
    })
    res.clearCookie('refreshToken', {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: process.env.NODE_ENV === 'production' ? 'strict' : 'lax',
      path: '/api/auth/refresh',
    })

    logger.info(`User logged out: ${req.user?.email}`)

    return successResponse(res, null, 'Logged out successfully.')
    }
    catch (error) {
        logger.error('Logout error:', error)
    return errorResponse(res, 'Logout failed.', 500, error)
    }
};

export const changePassword = async (req, res) => {
    try {
        const { currentPassword, newPassword } = req.body;
        const userId = req.user.id;

        const user = await prisma.user.findUnique({
            where: { id: userId },
        });

        

        const isPasswordMatched = await bcrypt.compare(
            currentPassword,
            user.passwordHash
        );

        if (!isPasswordMatched) {
            return errorResponse(res, 'Current password is incorrect', 401)
        }

        const newPasswordHash = await bcrypt.hash(newPassword, 12);

        await prisma.user.update({
            where: { id: userId },
            data: {
                passwordHash: newPasswordHash,
            },
        });

        const accessToken = req.cookies?.accessToken
        const refreshToken = req.cookies?.refreshToken

        if (accessToken) {
      const decoded = jwt.decode(accessToken)
      if (decoded?.exp) {
        const expirySeconds = decoded.exp - Math.floor(Date.now() / 1000)
        if (expirySeconds > 0) await blacklistToken(accessToken, expirySeconds)
      }
    }

    if (refreshToken) {
      await redis.del(`refresh:${refreshToken}`)
    }
    res.clearCookie('accessToken', {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: process.env.NODE_ENV === 'production' ? 'strict' : 'lax',
    })
    res.clearCookie('refreshToken', {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: process.env.NODE_ENV === 'production' ? 'strict' : 'lax',
      path: '/api/auth/refresh',
    })

    logger.info(`Password changed for user: ${user.email}`)

    return successResponse(
      res,
      null,
      'Password changed successfully. please login again.')
    }
    catch (error) {
        logger.error('Change password error:', error)
        return errorResponse(res, 'Failed to change password.', 500, error)
    }
};

export const getMe = async (req, res) => {
    try {
    const user = await prisma.user.findUnique({
      where: { id: req.user.id },
      select: {
        id: true,
        email: true,
        firstName: true,
        lastName: true,
        role: true,
        speciality: true,
        assignedDoctorId: true,
        isActive: true,
        lastLoginAt: true,
        createdAt: true,
        // If nurse — include assigned doctor info
        assignedDoctor: {
          select: {
            id: true,
            firstName: true,
            lastName: true,
            speciality: true,
          },
        },
      },
    })

    if (!user) {
      return errorResponse(res, 'User not found.', 404)
    }

    return successResponse(res, user, 'User profile retrieved.')
  } catch (error) {
    logger.error('Get me error:', error)
    return errorResponse(res, 'Failed to retrieve profile.', 500, error)
  }
}

