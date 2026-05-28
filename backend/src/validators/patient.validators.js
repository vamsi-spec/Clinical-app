import {z} from "zod"

const uuidSchema = z.string().uuid('Must be a valid UUID')

const phoneSchema = z
  .string()
  .regex(
    /^(\+91[-\s]?)?[0]?(91)?[789]\d{9}$|^\+?[1-9]\d{6,14}$/,
    'Invalid phone number format'
  )
  .optional()

const dateSchema = z
  .string()
  .refine((val) => !isNaN(Date.parse(val)), 'Invalid date format')
  .transform((val) => new Date(val))



//Register patient schema
//Receptionist creates demograpthic shell
//doctor fills clinical data

export const registerPatientSchema = z.object({
    firstName: z.string().min(3,'First name must be atleast 2 characters').max(25).trim(),
    lastName: z.string().min(2,'Last name must be atleast 2 characters').max(25).trim(),dob: dateSchema,
    gender: z.enum(['Male','Female','Other','Prefer not to say'],{
        errorMap: () => ({
            message: 'Gender must be a male,female,Other or prefer not to say'
        })
    }),
    //which doctor this patient is being registered under
    //receptionist select from active doctor list
    doctorId: uuidSchema,
    phone: phoneSchema,
    email: z
    .string()
    .email('Invalid email address')
    .toLowerCase()
    .trim()
    .optional(),

    address: z.string().max(500).trim().optional(),
  city: z.string().max(100).trim().optional(),
  state: z.string().max(100).trim().optional(),

  pincode: z
    .string()
    .regex(/^\d{6}$/, 'Pincode must be 6 digits')
    .optional(),

    nationality: z.string().max(50).trim().optional(),
  preferredLanguage: z.string().max(50).trim().optional(),

  emergencyContactName: z.string().max(100).trim().optional(),
  emergencyContactPhone: phoneSchema,
  emergencyContactRel: z
    .enum(['Spouse', 'Parent', 'Sibling', 'Child', 'Friend', 'Guardian', 'Other'])
    .optional(),

    primaryInsurance: z.string().max(200).trim().optional(),
  insuranceNumber: z.string().max(100).trim().optional(),
  secondaryInsurance: z.string().max(200).trim().optional(),

  consentGiven: z
    .boolean()
    .refine((val) => val === true, {
      message: 'Patient consent must be obtained and recorded before registration',
    }),
}).refine(
  (data) => {
    const hasAny =
      data.emergencyContactName ||
      data.emergencyContactPhone ||
      data.emergencyContactRel
    if (hasAny) {
      return data.emergencyContactName && data.emergencyContactPhone
    }
    return true
  },
  {
    message: 'Emergency contact name and phone are both required',
    path: ['emergencyContactName'],
  }
)


//updating the demographic info not clinical data
//only by receptionist 

export const updateDemographicsSchema = z.object({
  firstName: z.string().min(2).max(50).trim().optional(),
  lastName: z.string().min(2).max(50).trim().optional(),
  dob: dateSchema.optional(),
  gender: z.enum(['Male', 'Female', 'Other', 'Prefer not to say']).optional(),
  nationality: z.string().max(50).trim().optional(),
  preferredLanguage: z.string().max(50).trim().optional(),
  phone: phoneSchema,
  email: z.string().email().toLowerCase().trim().optional(),
  address: z.string().max(500).trim().optional(),
  city: z.string().max(100).trim().optional(),
  state: z.string().max(100).trim().optional(),
  pincode: z.string().regex(/^\d{6}$/).optional(),
  emergencyContactName: z.string().max(100).trim().optional(),
  emergencyContactPhone: phoneSchema,
  emergencyContactRel: z
    .enum(['Spouse', 'Parent', 'Sibling', 'Child', 'Friend', 'Guardian', 'Other'])
    .optional(),
  primaryInsurance: z.string().max(200).trim().optional(),
  insuranceNumber: z.string().max(100).trim().optional(),
  secondaryInsurance: z.string().max(200).trim().optional(),
})



//Doctor - update clinical profile

export const updateClinicalProfileSchema = z.object({
    bloodType: z
    .enum(['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-', 'Unknown'])
    .optional(),

  allergies: z
    .array(z.string().min(1).max(100))
    .max(50, 'Cannot exceed 50 allergy entries')
    .optional(),

  currentMedications: z
    .array(z.string().min(1).max(200))
    .max(50, 'Cannot exceed 50 medication entries')
    .optional(),

  pastSurgeries: z
    .array(z.string().min(1).max(200))
    .max(30, 'Cannot exceed 30 surgery entries')
    .optional(),

    chronicConditions: z
    .array(z.string().min(1).max(200))
    .max(30, 'Cannot exceed 30 condition entries')
    .optional(),

  familyHistory: z
    .string()
    .max(2000, 'Family history cannot exceed 2000 characters')
    .trim()
    .optional(),

  referredBy: uuidSchema.optional(),
})



export const patientQuerySchema = z.object({
  search: z.string().max(100).trim().optional(),
  mrn: z.string().optional(),
  gender: z.enum(['Male', 'Female', 'Other', 'Prefer not to say']).optional(),
  bloodType: z
    .enum(['A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-', 'Unknown'])
    .optional(),
  isActive: z
    .string()
    .transform((val) => val === 'true')
    .optional(),
  chronicCondition: z.string().max(100).optional(),
  doctorId: uuidSchema.optional(),

  page: z
    .string()
    .transform((val) => parseInt(val, 10))
    .refine((val) => val > 0, 'Page must be greater than 0')
    .default('1'),

    limit: z
    .string()
    .transform((val) => parseInt(val, 10))
    .refine((val) => val > 0 && val <= 100, 'Limit must be between 1 and 100')
    .default('20'),

  sortBy: z
    .enum(['firstName', 'lastName', 'createdAt', 'mrn', 'dob'])
    .default('createdAt'),

  sortOrder: z.enum(['asc', 'desc']).default('desc'),
})


export const archivePatientSchema = z.object({
  deleteReason: z
    .string()
    .min(10, 'Archive reason must be at least 10 characters')
    .max(500)
    .trim(),
})

export const idParamSchema = z.object({
  id: uuidSchema,
})