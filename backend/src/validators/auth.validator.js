import { z } from "zod";


export const passwordSchema = z
  .string()
  .min(8, 'Password must be at least 8 characters')
  .max(72, 'Password cannot exceed 72 characters') 
  .regex(/[A-Z]/, 'Password must contain at least one uppercase letter')
  .regex(/[a-z]/, 'Password must contain at least one lowercase letter')
  .regex(/[0-9]/, 'Password must contain at least one number')
  .regex(/[^A-Za-z0-9]/, 'Password must contain at least one special character');

export const registerSchema = z.object({
  email: z
    .string()
    .email('Invalid email address')
    .toLowerCase()
    .trim(),

  password: passwordSchema,

  confirmPassword: z.string(),

  firstName: z
    .string()
    .min(2, 'First name must be at least 2 characters')
    .max(50, 'First name cannot exceed 50 characters')
    .trim(),

  lastName: z
    .string()
    .min(2, 'Last name must be at least 2 characters')
    .max(50, 'Last name cannot exceed 50 characters')
    .trim(),

  role: z.enum(['ADMIN', 'DOCTOR', 'NURSE', 'RECEPTIONIST'], {
    errorMap: () => ({
      message: 'Role must be one of: ADMIN, DOCTOR, NURSE, RECEPTIONIST',
    }),
  }),


  speciality: z
    .string()
    .max(100, 'Speciality cannot exceed 100 characters')
    .trim()
    .optional(),

  assignedDoctorId: z
    .string()
    .uuid('assignedDoctorId must be a valid UUID')
    .optional(),
}).refine(
  (data) => data.password === data.confirmPassword,
  {
    message: 'Passwords do not match',
    path: ['confirmPassword'],
  }
).refine(
  (data) => {
    if (data.role === 'DOCTOR' && !data.speciality) return false
    return true
  },
  {
    message: 'Speciality is required for Doctor role',
    path: ['speciality'],
  }
).refine(
  (data) => {
    // NURSE must have assignedDoctorId
    if (data.role === 'NURSE' && !data.assignedDoctorId) return false
    return true
  },
  {
    message: 'assignedDoctorId is required for Nurse role',
    path: ['assignedDoctorId'],
  }
);

export const loginSchema = z.object({
  email: z
    .string()
    .email('Invalid email address')
    .toLowerCase()
    .trim(),

  password: z
    .string()
    .min(1, 'Password is required'),
});


export const refreshSchema = z.object({
  refreshToken: z.string().optional(),
});

export const changePasswordSchema = z.object({
  currentPassword: z
    .string()
    .min(1, 'Current password is required'),

  newPassword: passwordSchema,

  confirmNewPassword: z.string(),
}).refine(
  (data) => data.newPassword === data.confirmNewPassword,
  {
    message: 'New passwords do not match',
    path: ['confirmNewPassword'],
  }
).refine(
  (data) => data.currentPassword !== data.newPassword,
  {
    message: 'New password must be different from current password',
    path: ['newPassword'],
  }
);

