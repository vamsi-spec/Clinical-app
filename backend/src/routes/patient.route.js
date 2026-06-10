import express from 'express'
import { protect } from '../middleware/auth.middleware.js'
import { apiLimiter } from '../middleware/rateLimiter.middleware.js'
import { auditLog } from '../middleware/audit.middleware.js'
import { allowRoles, allRoles, doctorAndAdmin, clinicalStaff, adminOnly } from '../middleware/role.middleware.js'
import { getActiveDoctors, getPatient, listPatients, registerPatient, updateDemographics, updateClinicalProfile, getPatientVisits, getPatientStats, archivePatient, restorePatient } from '../controllers/patient.controller.js'
import { validate, validateParams, validateQuery } from '../middleware/validate.middleware.js'
import { idParamSchema, patientQuerySchema, registerPatientSchema, updateDemographicsSchema, updateClinicalProfileSchema, archivePatientSchema } from '../validators/patient.validators.js'


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
