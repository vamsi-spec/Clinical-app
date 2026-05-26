import express from 'express'
import { auditLog } from '../middleware/audit.middleware'
import { authLimiter } from '../middleware/rateLimiter.middleware'
import { validate } from '../middleware/validate.middleware'
import { changePasswordSchema, loginSchema, registerSchema } from '../validators/auth.validator'
import { changePassword, getMe, login, logout, refresh, register } from '../controllers/auth.controller'
import { protect } from '../middleware/auth.middleware'




const authRouter = express.Router


authRouter.use(auditLog)


authRouter.post('/register',authLimiter,validate(registerSchema),register)

authRouter.post('/login',authLimiter,validate(loginSchema),login)

authRouter.post('/refresh',refresh)

authRouter.post('/logout',protect,logout)

authRouter.get('/me',protect,getMe)

authRouter.put('/change-password',protect,validate(changePasswordSchema),changePassword)


export default authRouter
