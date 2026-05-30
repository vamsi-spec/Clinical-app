import express from 'express'
import { protect } from '../middleware/auth.middleware'
import { apiLimiter } from '../middleware/rateLimiter.middleware'
import { auditLog } from '../middleware/audit.middleware'
import { allowRoles, allRoles } from '../middleware/role.middleware'
import { getActiveDoctors, getPatient, listPatients, registerPatient, updateDemographics } from '../controllers/patient.controller'
import { validate, validateParams, validateQuery } from '../middleware/validate.middleware'
import { idParamSchema, patientQuerySchema, registerPatientSchema } from '../validators/patient.validators'


const patientRouter = express.Router()






patientRouter.use(protect)
patientRouter.use(apiLimiter)
patientRouter.use(auditLog)


patientRouter.get('/doctors',allowRoles('RECEPTIONIST', 'ADMIN', 'DOCTOR', 'NURSE'),getActiveDoctors)

patientRouter.get('/',allRoles,validateQuery(patientQuerySchema),listPatients)

patientRouter.post('/',allowRoles('RECEPTIONIST','ADMIN'),validate(registerPatientSchema),registerPatient)

patientRouter.get('/:id',allRoles,validateParams(idParamSchema),getPatient)

patientRouter.put('/:id/demographics',allowRoles('RECEPTIONIST','ADMIN'),validateParams(idParamSchema),validate(updateDemographicsSchema),updateDemographics)

patientRouter.put(
  '/:id/clinical',
  doctorAndAdmin,
  validateParams(idParamSchema),
  validate(updateClinicalProfileSchema),
  updateClinicalProfile
)

patientRouter.get(
  '/:id/visits',
  clinicalStaff,
  validateParams(idParamSchema),
  getPatientVisits
)


patientRouter.get(
  '/:id/stats',
  clinicalStaff,
  validateParams(idParamSchema),
  getPatientStats
)


patientRouter.delete(
  '/:id',
  adminOnly,
  validateParams(idParamSchema),
  validate(archivePatientSchema),
  archivePatient
)


patientRouter.put(
  '/:id/restore',
  adminOnly,
  validateParams(idParamSchema),
  restorePatient
)




export default patientRouter
