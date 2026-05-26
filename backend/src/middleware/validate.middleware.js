import { validationErrorResponse } from "../utils/apiResponse.js";
import logger from "../utils/logger.js";

export const validate = (schema) =>{
    return (req,res,next) => {
        const result = schema.safeParse(req.body)
        if(!result.success){
            const errors = result.error.errors.map((err) => ({
                field: err.path.join('.'),
                message: err.message,
            }))
            logger.warn('Validation failed', {
        url: req.originalUrl,
        method: req.method,
        errors,
      })
      return validationErrorResponse(res, errors)
        }
        req.body = result.data
    next()
        
    }
}


export const validateQuery = (schema) => {
    return (req,res,next)=>{
        const result = schema.safeParse(req.query)
        if(!result.success){
            const errors = result.error.errors.map((err) => ({
                field: err.path.join('.'),
                message: err.message,
            }))
            logger.warn('Validation failed', {
        url: req.originalUrl,
        method: req.method,
        errors,
      })
      return validationErrorResponse(res, errors)
        }
        req.query = result.data
        next()
    }
}


export const validateParams = (schema) => {
  return (req, res, next) => {
    const result = schema.safeParse(req.params)

    if (!result.success) {
      const errors = result.error.errors.map((err) => ({
        field: err.path.join('.'),
        message: err.message,
      }))
      return validationErrorResponse(res, errors)
    }

    req.params = result.data
    next()
  }
}
