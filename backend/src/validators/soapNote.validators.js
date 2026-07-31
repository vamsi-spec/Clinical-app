import { object, z } from 'zod';

export const editSoapNoteSchema = z.object({
    subjective: z.string().min(1).optional(),
    objective: z.string().min(1).optional(),
    assessment: z.string().min(1).optional(),
    plan: z.string().min(1).optional(),
    editReason: z.string().max(500).optional()
}).refine(
    (data) => ['subjective','objective','assessment','plan'].some((k) => data[k] !== undefined),
    {message: 'At least one SOAP section must be provided'}
);

export const finalizeSoapNoteSchema = z.object({
    subjective: z.string().min(1).optional(),
    objective: z.string().min(1).optional(),
    assessment: z.string().min(1).optional(),
    plan: z.string().min(1).optional()
}).optional();


