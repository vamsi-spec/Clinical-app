import { errorResponse } from "../utils/apiResponse.js";
import logger from "../utils/logger.js";


export const allowRoles = (...roles) => {
    return (req,res,next) => {
        if(!req.user){
            return errorResponse(res,'User session not found. Please log in again',401);
        }
        if(!roles.includes(req.user.role)) {
            logger.warn('Unauthorized access attempt',{
                userId: req.user.id,
                userRole: req.user.role,
                requiredRoles: roles,
                url: req.originalUrl,
                method: req.method,
            });
            return errorResponse(
                res,
                `Access denied. Required role: ${roles.join(' or ')}.`,
                403
            )
        }
        next()
    }
}


// Only system admin
const adminOnly = allowRoles('ADMIN')

// Clinical staff — can view and interact with clinical data
const clinicalStaff = allowRoles('ADMIN', 'DOCTOR', 'NURSE')

// Doctor and admin only — for write operations on clinical notes
const doctorAndAdmin = allowRoles('ADMIN', 'DOCTOR')

// All authenticated users — for shared resources like appointments
const allRoles = allowRoles('ADMIN', 'DOCTOR', 'NURSE', 'RECEPTIONIST')


export const selfOrAdmin = (paramName = 'id') => {
    return (req,res,next) => {
        if(!req.user){
            return errorResponse(res, 'Authentication required.', 401)
        }
        const isAdmin = req.user.role === 'ADMIN'
        const isSelf = req.params[paramName] === req.user.id
        if(!isAdmin && !isSelf){
            logger.warn('Unauthorized self/admin access attempt', {
        userId: req.user.id,
        paramId: req.params[paramName],
        url: req.originalUrl,
      })
      return errorResponse(res, 'Access denied.', 403)
        }
        next()
    }
}


export const checkDoctorScope = (doctorIdField = 'doctorId') => {
    return (req,res,next) => {
        if(!req.user){
            return errorResponse(res,'Authentication Required',401)
        }
        if (req.user.role === 'ADMIN'){
            return next()
        }
        if(req.user.role === 'DOCTOR'){
            req.scopedDoctorId = req.user.id;
            return next()
        }
        if(req.user.role === "NURSE"){
            if(!req.user.assignedDoctorId){
                return errorResponse(res,'Nurse not assigned to any doctor. Contact Admin', 403)
            }
            req.scopedDoctorId = req.user.assignedDoctorId
            return next()
        }
        if (req.user.role === 'RECEPTIONIST') {
      return errorResponse(
        res,
        'Receptionists cannot access clinical data.',
        403
      )
    }

    return errorResponse(res, 'Access denied.', 403)
  }
}