import express from "express";
import { protect } from "../middleware/auth.middleware.js";
import { apiLimiter } from "../middleware/rateLimiter.middleware.js";
import { auditLog } from "../middleware/audit.middleware.js";
import { allowRoles, allRoles, doctorAndAdmin } from "../middleware/role.middleware.js";
import { cancelAppointment, checkAvailability, completeAppointment, createAppointment, getAppointment, getTodaySchedule, listAppointments, markNoShow, updateAppointment } from "../controllers/appointment.controller.js";
import { validate, validateParams, validateQuery } from "../middleware/validate.middleware.js";
import { appointmentQuerySchema, availabilityQuerySchema, cancelAppointmentSchema, completeAppointmentSchema, createAppointmentSchema, idParamSchema, noShowSchema, updateAppointmentSchema } from "../validators/appointment.validators.js";



const appointmentRouter = express.Router();



appointmentRouter.use(protect)
appointmentRouter.use(apiLimiter)
appointmentRouter.use(auditLog)

appointmentRouter.get('/today',allRoles,getTodaySchedule)
appointmentRouter.get('/availability',allowRoles('RECEPTIONIST', 'DOCTOR', 'ADMIN'),validateQuery(availabilityQuerySchema),checkAvailability)

appointmentRouter.get('/',allRoles,validateQuery(appointmentQuerySchema),listAppointments)

appointmentRouter.post('/',allowRoles('RECEPTIONIST','ADMIN','DOCTOR'),validate(createAppointmentSchema),createAppointment)

appointmentRouter.get('/:id',allRoles,validateParams(idParamSchema),getAppointment)

appointmentRouter.put('/:id',allowRoles('RECEPTIONIST','ADMIN','DOCTOR'),validateParams(idParamSchema),validate(updateAppointmentSchema),updateAppointment)

appointmentRouter.put('/:id/cancel',allowRoles('RECEPTIONIST','ADMIN','DOCTOR'),validateParams(idParamSchema),validate(cancelAppointmentSchema),cancelAppointment)

appointmentRouter.put('/:id/no-show',allowRoles('RECEPTIONIST', 'ADMIN'),validateParams(idParamSchema),validate(noShowSchema),markNoShow)

appointmentRouter.put('/:id/complete',doctorAndAdmin,validateParams(idParamSchema),validate(completeAppointmentSchema),completeAppointment)

export default appointmentRouter