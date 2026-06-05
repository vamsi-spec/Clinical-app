import express from 'express'
import { apiLimiter } from '../middleware/rateLimiter.middleware'
import { protect } from '../middleware/auth.middleware'
import { auditLog } from '../middleware/audit.middleware'
import { adminOnly, allowRoles } from '../middleware/role.middleware'
import { validate, validateParams, validateQuery } from '../middleware/validate.middleware'
import { cancelTransferRequestSchema, executeTransferSchema, requestTransferSchema, reviewTransferSchema, transferQuerySchema } from '../validators/transfer.validators'
import { cancelTransfer, executeTransfer, getTransfer, listTransfers, requestTransfer, reviewTransfer } from '../controllers/transfer.controller'
import { idParamSchema } from '../validators/patient.validators'
const transferRouter = express.Router()




transferRouter.use(protect)
transferRouter.use(apiLimiter)
transferRouter.use(auditLog)


transferRouter.get('/',allowRoles('DOCTOR','ADMIN','RECEPTIONIST','NURSE'),validateQuery(transferQuerySchema),listTransfers)

transferRouter.post('/',allowRoles('DOCTOR'),validate(requestTransferSchema),requestTransfer)

transferRouter.get('/:id',allowRoles('DOCTOR','ADMIN','RECEPTIONIST','NURSE'),validateParams(idParamSchema),getTransfer)

transferRouter.put('/:id/review',adminOnly,validateParams(idParamSchema),validate(reviewTransferSchema),reviewTransfer)

transferRouter.put('/:id/execute',allowRoles('RECEPTIONIST'),validateParams(idParamSchema),validate(executeTransferSchema),executeTransfer)

transferRouter.put('/:id/cancel',allowRoles('DOCTOR','ADMIN'),validateParams(idParamSchema),validate(cancelTransferRequestSchema),cancelTransfer)

export default transferRouter