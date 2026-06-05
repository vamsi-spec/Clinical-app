import {prisma} from "../config/db.js";

import logger from "../utils/logger.js";


//Conflict detection
//Checks if a doctor already has a appointment

const checkConflict = async (doctorId,scheduledAt,duration,bufferMinutes,excludeAppointmentId = null) => {
    //Calculate the full time this appointment occupies

    const appointmentStart = new Date(scheduledAt)
    const appointmentEnd = new Date(appointmentStart.getTime() + (duration + bufferMinutes)*60*1000)

    //Find the existing appintment for this doctor that overlaps with the requested time window

    const conflict = await prisma.appointment.findFirst({
        where: {
            doctorId,
            status: {in: ['SCHEDULED']},
            id: excludeAppointmentId ? {not: excludeAppointmentId} : undefined,
            AND: [
                {
                    scheduledAt: {lt: appointmentEnd},
                },
                {
                    endsAt: {gt: appointmentStart},
                }
            ]
        },
        select: {
            id: true,
            scheduledAt: true,
            endsAt: true,
            duration: true,
            patient: {
                select: {
                    firstName: true,
                    lastName: true,
                    mrn: true,
                }
            }
        }
    })

    return conflict
}

const calculateEndsAt = (scheduledAt,duration) => {
    return new Date(new Date(scheduledAt).getTime() + duration*60*1000)
}


const buildScopeFilter = (user) => {
    if(user.role === 'ADMIN') return {}

    if(user.role === 'DOCTOR') {
        return {doctorId: user.id}
    }

    if(user.role === 'NURSE') {
        return {doctorId: user.assignedDoctorId}
    }

    return {}
}

//List Appointments
//Roles-> all
//Receptioist can see allappointments
//Doctor can only see their ownappointments
//Nurse can only see their assigned doctor's appointments
//Admin can see allappointments

export const listAppointments = async (req,res) => {
    try {
        const {dateFrom,dateTo,status,type,patientId,doctorId,today,upcoming,page,limit,sortBy,sortOrder} = req.query

        const skip = (page - 1) * limit
        const scopeFilter = buildScopeFilter(req.user)

        const where = {...scopeFilter}

        if(today) {
            const todayStart = new Date()
            todayStart.setHours(0,0,0,0)
            const todayEnd = new Date()
            todayEnd.setHours(23,59,59,999)
            where.scheduledAt = {gte: todayStart,lte: todayEnd}
        }

        if(upcoming && !today) {
            where.scheduledAt = {gte: new Date()}
        }

        if(dateFrom || dateTo) {
            where.scheduledAt = {}
            if(dateFrom) where.scheduledAt.gte = dateFrom
            if(dateTo) where.scheduledAt.lte = dateTo
        }

        if(status) where.status = status

        if(type) where.type = type

        if(patientId) where.patientId = patientId

        if (doctorId && req.user.role === 'ADMIN') {
      where.doctorId = doctorId
        }

        const [total, appointments] = await Promise.all([
      prisma.appointment.count({ where }),
      prisma.appointment.findMany({
        where,
        orderBy: { [sortBy]: sortOrder },
        skip,
        take: limit,
        select: {
          id: true,
          scheduledAt: true,
          endsAt: true,
          duration: true,
          bufferMinutes: true,
          status: true,
          type: true,
          chiefComplaint: true,
          isWalkIn: true,
          reminderSent: true,
          createdAt: true,
          patient: {
            select: {
              id: true,
              mrn: true,
              firstName: true,
              lastName: true,
              phone: true,
            },
          },
          doctor: {
            select: {
              id: true,
              firstName: true,
              lastName: true,
              specialty: true,
            },
          },
        },
      }),
    ])

    return paginatedResponse(
      res,
      appointments,
      { page, limit, total },
      'Appointments retrieved successfully.'
    )
  } catch (error) {
    logger.error('List appointments error:', error)
    return errorResponse(res, 'Failed to retrieve appointments.', 500, error)
  }
}

