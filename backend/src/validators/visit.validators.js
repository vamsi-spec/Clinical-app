import { z } from "zod";

export const createVisitSchema = z.object({
    patientId: z.string().uuid('Invalid patient ID'),
  doctorId: z.string().uuid('Invalid doctor ID').optional(),
  appointmentId: z.string().uuid('Invalid appointment ID').optional(),
  visitDate: z.string().datetime().optional(), // defaults to now() if omitted
  specialty: z.string().min(2).max(100).optional(), // defaults to doctor.specialty
})


// UPDATE VISIT
// Deliberately narrow — most Visit fields are
// populated by the pipeline, not editable by hand.
// Doctor-editable fields only.

export const updateVisitSchema = z.object({
    visitDate: z.string().datetime().optional(),
    specialty: z.string().min(2).max(100).optional(),
}).refine((data) => Object.keys(data).length > 0,{message: 'At least one field must be provided'});

//Query / List Visits
//Supports the filters the frontend visit list
//paging needs -> by patient,by doctor , by status,by date range,plus pagination

export const visitQuerySchema = z.object({
    patientId: z.string()
.uuid().optional(),
doctorId: z.string().uuid().optional(),
status: z.enum([
    'PENDING', 'AUDIO_UPLOADED', 'TRANSCRIBING', 'DIARIZING',
    'CORRECTING', 'EXTRACTING_ENTITIES', 'GENERATING_SOAP',
    'CHECKING_INCONSISTENCIES', 'MAPPING_EXPLAINABILITY',
    'CHECKING_BILLING', 'CHECKING_DRUGS', 'COMPLETED', 'FAILED',
  ]).optional(),
  dateFrom: z.string().datetime().optional(),
  dateTo: z.string().datetime().optional(),
  includeArchived: z.enum(['true', 'false']).optional().default('false'),
  page: z.string().regex(/^\d+$/).optional().default('1'),
  limit: z.string().regex(/^\d+$/).optional().default('20'),
})

export const visitIdParamSchema = z.object({
  id: z.string().uuid('Invalid visit ID'),
});


