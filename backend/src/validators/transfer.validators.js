import { z } from "zod";

const uuidSchema = z.string().uuid('Must be a valid UUID')


//Doctor raises a request

export const requestTransferSchema = z.object({
    patientId: uuidSchema,

    toDoctorId: uuidSchema,

    reason: z
    .string()
    .min(20, 'Transfer reason must be at least 20 characters — be specific')
    .max(1000, 'Reason cannot exceed 1000 characters')
    .trim(),
})

//Admin review transfer request

export const reviewTransferSchema = z.object({
  decision: z.enum(['APPROVED', 'REJECTED'], {
    errorMap: () => ({
      message: 'Decision must be APPROVED or REJECTED',
    }),
  }),

  adminNote: z
    .string()
    .min(5, 'Please provide a note explaining your decision')
    .max(500)
    .trim(),
})

// RECEPTIONIST — EXECUTE TRANSFER SCHEMA

export const executeTransferSchema = z.object({
  confirmationNote: z
    .string()
    .max(500)
    .trim()
    .optional(),
})

// DOCTOR — CANCEL OWN REQUEST SCHEMA

export const cancelTransferRequestSchema = z.object({
  cancelNote: z
    .string()
    .min(5, 'Please provide a reason for cancellation')
    .max(500)
    .trim(),
})

export const transferQuerySchema = z.object({
  status: z
    .enum(['PENDING', 'APPROVED', 'REJECTED', 'COMPLETED', 'CANCELLED'])
    .optional(),

  patientId: uuidSchema.optional(),
  fromDoctorId: uuidSchema.optional(),
  toDoctorId: uuidSchema.optional(),

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

    sortBy: z
    .enum(['createdAt', 'updatedAt', 'status'])
    .default('createdAt'),

  sortOrder: z.enum(['asc', 'desc']).default('desc'),
})


export const idParamSchema = z.object({
  id: uuidSchema,
})