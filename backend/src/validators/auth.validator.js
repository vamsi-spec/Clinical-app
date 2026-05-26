import { z } from "zod";

const ROLES = ["ADMIN", "DOCTOR", "NURSE", "RECEPTIONIST"];


const passwordSchema = z
    .string()
    .min(8, "Password must be at least 8 characters")
    .regex(/[A-Z]/, "Password must contain at least one uppercase letter")
    .regex(/[a-z]/, "Password must contain at least one lowercase letter")
    .regex(/[0-9]/, "Password must contain at least one number")
    .regex(/[^A-Za-z0-9]/, "Password must contain at least one special character");


const registerSchema = z
    .object({
        email: z.string().email("Invalid email address").toLowerCase().trim(),
        password: passwordSchema,
        confirmPassword: z.string(),

        firstName: z
            .string()
            .min(2, "First name must be at least 2 characters")
            .max(50, "First name must not exceed 50 characters")
            .trim(),

        lastName: z
            .string()
            .min(2, "Last name must be at least 2 characters")
            .max(50, "Last name must not exceed 50 characters")
            .trim()
            .optional(),

        role: z.enum(ROLES, {
            message: "Invalid user role",
        }),

        specialty: z.string().trim().optional(),
        assignedDoctorId: z.string().uuid("Invalid doctor id").optional(),
    })
    .refine((data) => data.password === data.confirmPassword, {
        message: "Password and confirm password do not match",
        path: ["confirmPassword"],
    })
    .superRefine((data, ctx) => {
        if (data.role === "DOCTOR" && !data.specialty) {
            ctx.addIssue({
                path: ["specialty"],
                message: "Specialty is required for doctors",
                code: z.ZodIssueCode.custom,
            });
        }

        if (data.role === "NURSE" && !data.assignedDoctorId) {
            ctx.addIssue({
                path: ["assignedDoctorId"],
                message: "Assigned doctor id is required for nurses",
                code: z.ZodIssueCode.custom,
            });
        }
    });


const loginSchema = z.object({
    email: z.string().email("Invalid email address").toLowerCase().trim(),
    password: z.string().min(1, "Password is required"),
});


const changePasswordSchema = z
    .object({
        currentPassword: z.string().min(1, "Current password is required"),
        newPassword: passwordSchema,
        confirmNewPassword: z.string(),
    })
    .refine((data) => data.newPassword === data.confirmNewPassword, {
        message: "New password and confirm password do not match",
        path: ["confirmNewPassword"],
    })
    .refine((data) => data.currentPassword !== data.newPassword, {
        message: "New password must be different from current password",
        path: ["newPassword"],
    });



const logoutSchema = z.object({}).strict();

const validate = (schema) => {
    return (req, res, next) => {
        const result = schema.safeParse(req.body || {});

        if (!result.success) {
            const errors = result.error.issues.map((err) => ({
                field: err.path.join("."),
                message: err.message,
            }));

            return res.status(400).json({
                success: false,
                message: "Validation failed",
                errors,
            });
        }

        req.body = result.data;
        next();
    };
};

export {
    registerSchema,
    loginSchema,
    logoutSchema,
    changePasswordSchema,
    validate,
    passwordSchema,
};