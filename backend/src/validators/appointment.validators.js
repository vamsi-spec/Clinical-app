import {z} from 'zod'

const uuidSchema = z.string().uuid('Must be a valid UUID')

const futureDateSchema = z.string().refine((val) => !isNaN(Date.parse(val)),'Invalid date format').transform((val)=> new Date(val)).refine((val) => val > new Date(),'Appointment must be in the  future')


export const createAppointmentSchema = z.object({
    patientId: uuidSchema,
    doctorId: uuidSchema.optional(),
    scheduledAt: futureDateSchema,
    duration: z.number().int().min(10).max(240).default(30),
    bufferMinutes: z.number().int().min(0).max(60).default(5),
    type: z
    .enum(['SCHEDULED', 'WALK_IN', 'FOLLOW_UP', 'REFERRAL', 'EMERGENCY'])
    .default('SCHEDULED'),
    chiefComplaint: z.string().min(3).max(500).trim().optional(),
    notes: z.string().max(2000).trim().optional(),

    isWalkIn: z.boolean().default(false),
  followUpOf: uuidSchema.optional(),
})

export const updateAppointmentSchema = z.object({
  scheduledAt: z
    .string()
    .refine((val) => !isNaN(Date.parse(val)), 'Invalid date')
    .transform((val) => new Date(val))
    .refine((val) => val > new Date(), 'Must be in the future')
    .optional(),
  duration: z.number().int().min(10).max(240).optional(),
  bufferMinutes: z.number().int().min(0).max(60).optional(),
  chiefComplaint: z.string().min(3).max(500).trim().optional(),
  notes: z.string().max(2000).trim().optional(),
  type: z
    .enum(['SCHEDULED', 'WALK_IN', 'FOLLOW_UP', 'REFERRAL', 'EMERGENCY'])
    .optional(),
})


export const cancelAppointmentSchema = z.object({
  cancelReason: z.string().min(5).max(500).trim(),
})

export const noShowSchema = z.object({
  notes: z.string().max(500).trim().optional(),
})

export const completeAppointmentSchema = z.object({
  notes: z.string().max(2000).trim().optional(),
  visitId: uuidSchema.optional(),
})


export const appointmentQuerySchema = z.object({
  dateFrom: z
    .string()
    .transform((val) => new Date(val))
    .optional(),
  dateTo: z
    .string()
    .transform((val) => new Date(val))
    .optional(),
  status: z
    .enum(['SCHEDULED', 'COMPLETED', 'CANCELLED', 'NO_SHOW'])
    .optional(),
  type: z
    .enum(['SCHEDULED', 'WALK_IN', 'FOLLOW_UP', 'REFERRAL', 'EMERGENCY'])
    .optional(),
  patientId: uuidSchema.optional(),
  doctorId: uuidSchema.optional(),
  today: z.string().transform((val) => val === 'true').optional(),
  upcoming: z.string().transform((val) => val === 'true').optional(),
  page: z
    .string()
    .transform((val) => parseInt(val, 10))
    .refine((val) => val > 0)
    .default('1'),
  limit: z
    .string()
    .transform((val) => parseInt(val, 10))
    .refine((val) => val > 0 && val <= 100)
    .default('20'),
  sortBy: z.enum(['scheduledAt', 'createdAt', 'status']).default('scheduledAt'),
  sortOrder: z.enum(['asc', 'desc']).default('asc'),
})

export const availabilityQuerySchema = z.object({
  doctorId: uuidSchema,
  date: z.string().refine((val) => !isNaN(Date.parse(val)), 'Invalid date'),
  duration: z
    .string()
    .transform((val) => parseInt(val, 10))
    .refine((val) => val >= 10 && val <= 240)
    .default('30'),
})

export const idParamSchema = z.object({
  id: uuidSchema,
})

