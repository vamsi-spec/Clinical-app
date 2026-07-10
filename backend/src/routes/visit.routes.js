import express from 'express'
import protect from '../middleware/auth.middleware.js'
import { allowRoles,adminOnly,clinicalStaff,doctorAndAdmin } from '../middleware/role.middleware.js'
import { validate,validateParams,validateQuery } from '../middleware/validate.middleware'
import { auditLog } from '../middleware/audit.middleware'

import { createVisitSchema,updateVisitSchema,visitQuerySchema,visitIdParamSchema } from '../validators/visit.validators'
import { createVisit,listVisits,getVisit,getVisitStatus,updateVisit,archiveVisit,restoreVisit,retryPipeline } from '../controllers/visit.controller'


const visitRouter = express.Router()
visitRouter.use(protect)
visitRouter.use(auditLog)

//create
visitRouter.post('/',doctorAndAdmin,validate(createVisitSchema),createVisit)

//List
visitRouter.get('/:id',clinicalStaff,validateParams(visitIdParamSchema),getVisit)

//Status
visitRouter.get('/:id/status',clinicalStaff,validateParams(visitIdParamSchema),getVisitStatus)

//Update
visitRouter.put('/:id',doctorAndAdmin,validateParams(visitIdParamSchema),validate(updateVisitSchema),updateVisit)

//Archive / Restore
visitRouter.put('/:id/archive',adminOnly,validateParams(visitIdParamSchema),archiveVisit)

visitRouter.put('/:id/restore',adminOnly,validateParams(visitIdParamSchema),restoreVisit)

//Retry failed pipeline
visitRouter.post('/:id/retry',doctorAndAdmin,validateParams(visitIdParamSchema),retryPipeline);

export default visitRouter


