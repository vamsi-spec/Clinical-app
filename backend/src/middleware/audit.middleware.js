import { prisma } from "../config/db.js";
import logger from "../utils/logger.js";


const ACTION_MAP = {
  // Auth
  'POST /api/auth/register': 'REGISTER',
  'POST /api/auth/login': 'LOGIN',
  'POST /api/auth/logout': 'LOGOUT',
  'POST /api/auth/refresh': 'REFRESH_TOKEN',

  // Patients
  'GET /api/patients': 'LIST_PATIENTS',
  'POST /api/patients': 'CREATE_PATIENT',
  'GET /api/patients/:id': 'VIEW_PATIENT',
  'PUT /api/patients/:id': 'UPDATE_PATIENT',
  'DELETE /api/patients/:id': 'DELETE_PATIENT',

  // Visits
  'POST /api/visits': 'CREATE_VISIT',
  'GET /api/visits/:id': 'VIEW_VISIT',
  'PUT /api/visits/:id': 'UPDATE_VISIT',
  'GET /api/patients/:id/visits': 'LIST_PATIENT_VISITS',

  // Admin
  'GET /api/admin/users': 'ADMIN_LIST_USERS',
  'PUT /api/admin/users/:id': 'ADMIN_UPDATE_USER',
  'GET /api/admin/audit-logs': 'ADMIN_VIEW_AUDIT_LOGS',
}



export const resolveAction = (method,url) => {
    const cleanUrl = url.split('?')[0]

    const exactKey = `${method} ${cleanUrl}`
    if(ACTION_MAP[exactKey]) return ACTION_MAP[exactKey]

    const patternUrl = cleanUrl.replace(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi,
    ':id')

    const patternKey = `${method}${patternUrl}`

    if(ACTION_MAP[patternKey]) return ACTION_MAP[patternKey]
    return `${method}${cleanUrl}`
}


export const extractResourceInfo = (req) => {
  const url = req.originalUrl.split('?')[0]
  const segments = url.split('/').filter(Boolean)

  // segments[0] = 'api', segments[1] = resource name
  const rawResource = segments[1] || 'unknown'

  
  const resourceTypeMap = {
    patients: 'Patient',
    visits: 'Visit',
    auth: 'Auth',
    admin: 'Admin',
    analytics: 'Analytics',
    appointments: 'Appointment',
  }

  const resourceType = resourceTypeMap[rawResource] || 
    rawResource.charAt(0).toUpperCase() + rawResource.slice(1)

  // Extract UUID from URL if present
  const uuidRegex = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi
  const uuids = url.match(uuidRegex)
  const resourceId = uuids ? uuids[0] : null

  return { resourceType, resourceId }
}
//Audit middleware
//logs every req after response sent - res.on('finish)
//why -> so it never blocks or slow down the response
//Usage: app.use(auditLog) -apply globally after auth

export const auditLog = (req,res,next) => {
    res.on('finish',async () => {
        try {
            if(
                req.originalUrl === '/api/health' || req.method === 'OPTIONS' || req.originalUrl.startsWith('/api/health')
            )
            return
            if (res.statusCode >= 300 && res.statusCode < 400) return
      if (res.statusCode >= 500) return

      const action = resolveAction(req.method,req.originalUrl)
      const {resourceType,resourceId} = extractResourceInfo(req)

      const metadata = {
        statusCode: res.statusCode,
        method: req.method,
        url: req.originalUrl
      }

      if (['POST', 'PUT', 'PATCH'].includes(req.method) && req.body) {
        const safeBody = { ...req.body }
        delete safeBody.password
        delete safeBody.passwordHash
        delete safeBody.confirmPassword
        delete safeBody.token
        delete safeBody.refreshToken
        if (JSON.stringify(safeBody).length < 1000) {
          metadata.body = safeBody
        }
      }

      await prisma.auditLog.create({
        data: {
          userId: req.user?.id || null,
          action,
          resourceType,
          resourceId,
          ipAddress: req.ip || req.connection.remoteAddress || 'unknown',
          userAgent: req.get('User-Agent') || null,
          metadata,
        },
      })
    } catch (error) {
     
      logger.error('Audit log write failed:', error.message)
    }
  })

  next()
}


//Selective audit 
//Use this on routes where you only want to log specific actions

export const auditAction = (action,getResourceId = null) => {
    return async (req,res,next) => {
        res.on('finish',async () => {
            try {
                if (res.statusCode >= 400) return
                const resourceId = getResourceId ? getResourceId(req,res) : req.params.id || null

                await prisma.auditLog.create({
          data: {
            userId: req.user?.id || null,
            action,
            resourceType: action.split('_').pop(), // 'CREATE_VISIT' → 'VISIT'
            resourceId,
            ipAddress: req.ip || 'unknown',
            userAgent: req.get('User-Agent') || null,
            metadata: {
              statusCode: res.statusCode,
              method: req.method,
              url: req.originalUrl,
            },
          },
        })
      } catch (error) {
        logger.error('Selective audit log failed:', error.message)
      }
    })
    next()
  }
}