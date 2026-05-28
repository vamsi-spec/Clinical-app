import express from 'express'
import { auditLog } from '../middleware/audit.middleware.js'
import { authLimiter } from '../middleware/rateLimiter.middleware.js'
import { validate } from '../middleware/validate.middleware.js'
import { changePasswordSchema, loginSchema, registerSchema } from '../validators/auth.validator.js'
import { changePassword, getMe, login, logout, refresh, register } from '../controllers/auth.controller.js'
import { protect } from '../middleware/auth.middleware.js'




const authRouter = express.Router()


authRouter.use(auditLog)


authRouter.post('/register',authLimiter,validate(registerSchema),register)

authRouter.post('/login',authLimiter,validate(loginSchema),login)

authRouter.post('/refresh',refresh)

authRouter.post('/logout',protect,logout)

authRouter.get('/me',protect,getMe)

authRouter.put('/change-password',protect,validate(changePasswordSchema),changePassword)


export default authRouter
