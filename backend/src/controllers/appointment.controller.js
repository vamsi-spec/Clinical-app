import {prisma} from "../config/db.js";

import logger from "../utils/logger.js";
import { errorResponse, successResponse, paginatedResponse } from "../utils/apiResponse.js";


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
              speciality: true,
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


export const getAppointment = async (req,res) => {
    try {
        const {id} = req.params

        const scopeFilter = buildScopeFilter(req.user)

        const appointment = await prisma.appointment.findFirst({
            where: {id,...scopeFilter},
            select: {
                id: true,
                scheduledAt: true,
                endsAt: true,
                duration: true,
                bufferMinutes: true,
                status: true,
                type: true,
                chiefComplaint: true,
                notes: true,
                isWalkIn: true,
                followUpOf: true,
                cancelReason: true,
                cancelledAt: true,
                completedAt: true,
                completedBy: true,
                bookedBy: true,
                createdAt: true,
                updatedAt: true,
                patient: {
                    select: {
                        id: true,
                        mrn: true,
                        firstName: true,
                        lastName: true,
                        phone: true,
                        email: true,
                        ...(req.user.role !== 'RECEPTIONIST' && {
                            allergies: true,
                            currentMedications: true,
                            chronicConditions: true,
                            bloodType: true,
                        }),
                    },
                },
                doctor: {
                    select: {
                        id: true,
                        firstName: true,
                        lastName: true,
                        speciality: true
                    }
                }
            }

        })

        if(!appointment) {
            return errorResponse(res,'Apponitment not found or access denied.',404)
        }

        return successResponse(res, appointment, 'Appointment retrieved.')
  } catch (error) {
    logger.error('Get appointment error:', error)
    return errorResponse(res, 'Failed to retrieve appointment.', 500, error)
  }
}

//Create Appointment
export const createAppointment = async (req,res) => {
    try {
        const {patientId,doctorId: bodyDoctorId,scheduledAt,duration,bufferMinutes,type,chiefComplaint,notes,isWalkIn,followUpOf} = req.body

        const doctorId = req.user.role === 'DOCTOR' ? req.user.id : bodyDoctorId

        if (req.user.role !== 'DOCTOR' && !doctorId) {
            return errorResponse(res, 'doctorId is required when booking as Receptionist or admin.', 400)
        }

        const doctor = await prisma.user.findUnique({
            where: {id: doctorId},
            select: {
                id: true,
                role: true,
                isActive: true,
                firstName: true,
                lastName: true
            }
        })

        if(!doctor || doctor.role !== 'DOCTOR') {
            return errorResponse(res,'Doctor not found',404)
        }

        if(!doctor.isActive) {
            return errorResponse(res,'Doctor account is inactive.',400)
        }

        const patient = await prisma.patient.findFirst({
            where: {id: patientId,isActive: true,deletedAt: null},
            select: {id: true,mrn: true,firstName: true,lastName: true}
        })

        if(!patient) {
            return errorResponse(res,'Patient not found.',404)
        }

        if(followUpOf) {
            const original = await prisma.appointment.findUnique({
                where: {id: followUpOf},
                select: {id: true,patientId: true}
            })

            if(!original) {
                return errorResponse(res,'Original appointment not found.',404)
            }

            if(original.patientId !== patientId) {
                return errorResponse(res,'Follow-up appointment must belong to the same patient',400)
            }
        }

        const apptDuration = duration || 30
        const apptBuffer = bufferMinutes !== undefined ? bufferMinutes : 10

        const conflict = await checkConflict(
            doctorId,
            scheduledAt,
            apptDuration,apptBuffer
        )


        if (conflict) {
      const conflictStart = new Date(conflict.scheduledAt).toLocaleTimeString(
        'en-IN',
        { hour: '2-digit', minute: '2-digit', hour12: true }
      )
      const conflictEnd = new Date(conflict.endsAt).toLocaleTimeString(
        'en-IN',
        { hour: '2-digit', minute: '2-digit', hour12: true }
      )
      return errorResponse(
        res,
        `Dr. ${doctor.firstName} ${doctor.lastName} is already booked from ${conflictStart} to ${conflictEnd} for patient ${conflict.patient.firstName} ${conflict.patient.lastName} (${conflict.patient.mrn}). Please choose a different time.`,
        409
      )
    }

    const endsAt = calculateEndsAt(scheduledAt,apptDuration)

    const appointment = await prisma.appointment.create({
      data: {
        patientId,
        doctorId,
        scheduledAt: new Date(scheduledAt),
        endsAt,
        duration: apptDuration,
        bufferMinutes: apptBuffer,
        type: type || 'SCHEDULED',
        chiefComplaint,
        notes,
        isWalkIn: isWalkIn || false,
        followUpOf,
        bookedBy: req.user.id,
        status: 'SCHEDULED',
      },
      select: {
        id: true,
        scheduledAt: true,
        endsAt: true,
        duration: true,
        type: true,
        status: true,
        chiefComplaint: true,
        patient: {
          select: { id: true, mrn: true, firstName: true, lastName: true },
        },
        doctor: {
          select: { id: true, firstName: true, lastName: true, speciality: true },
        },
      },
    })

    logger.info(
      `Appointment booked: ${appointment.id} for patient ${patient.mrn} with Dr. ${doctor.firstName} ${doctor.lastName} at ${scheduledAt} by ${req.user.role} ${req.user.email}`
    )

    return successResponse(
      res,
      appointment,
      `Appointment booked for ${patient.firstName} ${patient.lastName} on ${new Date(scheduledAt).toLocaleString('en-IN')}.`,
      201
    )
  } catch (error) {
    logger.error('Create appointment error:', error)
    return errorResponse(res, 'Failed to create appointment.', 500, error)
  }
}



//Update appointment
export const updateAppointment = async (req,res) => {
  try {
    const {id} = req.params
    const scopeFilter = buildScopeFilter(req.user)

    const existing = await prisma.appointment.findFirst({
        where: {id,...scopeFilter},
        select: {
            id: true,
            scheduledAt: true,
            endsAt: true,
            duration: true,
            bufferMinutes: true,
            status: true,
            doctorId: true,
            notes: true,
            patient: {
                select: {mrn: true,firstName: true,lastName: true},
            },
        },
    })

    if(!existing) {
        return errorResponse(res,'Appointment not found or access denied.',404)
    }

    

    if(existing.status !== 'SCHEDULED') {
        return errorResponse(res,`Cannot update ${existing.status} appointment. Only scheduled appointments can be modified.`,400)
    }

    const {scheduledAt,duration,bufferMinutes,chiefComplaint,notes,type} = req.body

    const newSheduledAt = scheduledAt ? new Date(scheduledAt) : existing.scheduledAt

    const newDuration = duration || existing.duration

    const newBuffer = bufferMinutes !== undefined ? bufferMinutes : existing.bufferMinutes

    if(scheduledAt || duration !== undefined || bufferMinutes !== undefined) {
        const conflict = await checkConflict(
            existing.doctorId,
            newSheduledAt,
            newDuration,
            newBuffer,
            id
        )

        if(conflict) {
            const conflictTime = new Date(conflict.scheduledAt).toLocaleTimeString('en-IN',{hour: '2-digit',minute: '2-digit',hour12:true})

            return errorResponse(
                res,
                `Booking conflict for ${existing.patient.firstName} ${existing.patient.lastName} (${existing.patient.mrn}) with Dr. ${existing.doctor.firstName} ${existing.doctor.lastName} at ${conflictTime}. Please select a different time slot.`,
                409
            )
        }
    }

    const updateData = {}
    if(scheduledAt) {
        updateData.scheduledAt = newSheduledAt
        updateData.endsAt = calculateEndsAt(newSheduledAt,newDuration)
    }

    if (duration) updateData.duration = duration
    if (bufferMinutes !== undefined) updateData.bufferMinutes = bufferMinutes
    if (chiefComplaint) updateData.chiefComplaint = chiefComplaint
    if (notes) updateData.notes = notes
    if (type) updateData.type = type

    const updated = await prisma.appointment.update({
        where: {id},
        data: updateData,
        select: {
            id: true,
            scheduledAt: true,
            endsAt: true,
            duration: true,
            status: true,
            type: true,
            chiefComplaint: true,
            patient: {
                select: {mrn: true,firstName: true,lastName: true},
            },
            doctor: {select: {firstName: true,lastName: true}}
        }
    })
    
logger.info(
      `Appointment updated: ${id} by ${req.user.role} ${req.user.email}`
    )

    return successResponse(res, updated, 'Appointment updated successfully.')
  } catch (error) {
    logger.error('Update appointment error:', error)
    return errorResponse(res, 'Failed to update appointment.', 500, error)
  }
}



//Cancel appointment
//Receptionist -> cancel on behalf of patient
//doctor -> cancels their own scheduled appontments

export const cancelAppointment = async (req,res) => {
    try {
       const {id} = req.params
       const {cancelReason} = req.body
       const scopeFilter = buildScopeFilter(req.user)
       
       const appointment = await prisma.appointment.findFirst({
        where: {id,...scopeFilter},
        select: {
            id: true,
            status: true,
            scheduledAt: true,
            patient: {select: {mrn: true,firstName: true,lastName: true}}
        }
       })

       if(!appointment) {
        return errorResponse(res,'Appointment not found or access denied.',404)
       }

       if(appointment.status === 'CANCELLED') {
        return errorResponse(res,'Appointment is already cancelled.',400)
       }

       if(appointment.status === 'COMPLETED') {
        return errorResponse(res,'Cannot cancel completed appointment.',400)
       }

       const hoursLeft = (new Date(appointment.scheduledAt) - new Date()) / (1000 * 60 * 60)

       if(hoursLeft > 0 && hoursLeft < 2) {
            logger.warn(`Late cancellation: ${id} — only ${hoursLeft.toFixed(1)} hours before appointment`)
       }

       await prisma.appointment.update({
        where: {id},
        data: {
            status: 'CANCELLED',
            cancelReason,
            cancelledAt: new Date(),
            cancelledBy: req.user.id
        }
       })

       logger.info(`Appointment cancelled: ${id} for patient ${appointment.patient.mrn} ${appointment.patient.firstName} ${appointment.patient.lastName} by ${req.user.role}`)

       return successResponse(
      res,
      null,
      `Appointment for ${appointment.patient.firstName} ${appointment.patient.lastName} cancelled successfully.`
    )
    } catch (error) {
        logger.error('Cancel appointment error:', error)
        return errorResponse(res, 'Failed to cancel appointment.', 500, error)
    }
}


//Mark no show
//Patient may didn't show up
//doctor is busy handles by receptionist and cancels 

export const markNoShow = async (req,res) => {
    try {
        const {id} = req.params
        const {notes} = req.body || {}
        const scopeFilter = buildScopeFilter(req.user)

        const appointment = await prisma.appointment.findFirst({
            where: {id,...scopeFilter},
            select: {
                id: true,
                status: true,
                scheduledAt: true,
                patient: {
                    select: {mrn: true,firstName: true,lastName: true},
                },
            }
        })

        if(!appointment) {
            return errorResponse(res,'Appointment not found or access denied.',404)
        }

        if(appointment.status !== 'SCHEDULED') {
            return errorResponse(res,'Can only mark scheduled appointments as no show.',400)
        }

        if(new Date(appointment.scheduledAt) > new Date()) {
            return errorResponse(res,"Cannot mark future appointments as no-show. Please mark as cancelled.",400)
        }

        await prisma.appointment.update({
            where: {id},
            data: {
                status: 'NO_SHOW',
                noShowAt: new Date(),
                notes: notes ? `No-show note: ${notes}` : undefined,
            }
        })

        logger.info(`No-show marked: ${id} for ${appointment.patient.mrn} ${appointment.patient.firstName} ${appointment.patient.lastName} by ${req.user.role} `)
        
        return successResponse(
            res,
            null,
            `No-show recorded for ${appointment.patient.firstName} ${appointment.patient.lastName}.`
        )
    } catch (error) {
    logger.error('Mark no-show error:', error)
    return errorResponse(res, 'Failed to record no-show.', 500, error)
  }
}


//Complete appointment
//doctor only

export const completeAppointment = async (req,res) => {
    try {
        const {id} = req.params
        const {notes,visitId} = req.body || {}

        const appointment = await prisma.appointment.findFirst({
            where: {
                id,
                doctorId: req.user.role === 'ADMIN' ? undefined: req.user.id,
            },
            select: {
                id: true,
                status: true,
                scheduledAt: true,
                patient: {select: {mrn:true,firstName:true,lastName:true}},
            }
        })

        if(!appointment) {
            return errorResponse(res,'Appointment not found or access denied.',404)
        }

        if (appointment.status !== 'SCHEDULED') {
      return errorResponse(
        res,
        `Cannot complete a ${appointment.status.toLowerCase()} appointment.`,
        400
      )
    }

    await prisma.appointment.update({
      where: { id },
      data: {
        status: 'COMPLETED',
        completedAt: new Date(),
        completedBy: req.user.id,
        notes: notes
          ? `${appointment.notes || ''}\nCompletion note: ${notes}`.trim()
          : undefined,
      },
    })

    logger.info(
      `Appointment completed: ${id} for patient ${appointment.patient.mrn} by Dr. ${req.user.email}`
    )

    return successResponse(
      res,
      null,
      `Appointment for ${appointment.patient.firstName} ${appointment.patient.lastName} marked as completed.`
    )
  } catch (error) {
    logger.error('Complete appointment error:', error)
    return errorResponse(res, 'Failed to complete appointment.', 500, error)
  }
}


export const getTodaySchedule = async (req,res) => {
  try {
    const scopeFilter = buildScopeFilter(req.user)

    const todayStart = new Date()
    todayStart.setHours(0,0,0,0)

    const todayEnd = new Date()
    todayEnd.setHours(23,59,59,999)

    const appointments = await prisma.appointment.findMany({
      where: {
        ...scopeFilter,
        scheduledAt: { gte: todayStart, lte: todayEnd },
      },
      orderBy: { scheduledAt: 'asc' },
      select: {
        id: true,
        scheduledAt: true,
        endsAt: true,
        duration: true,
        status: true,
        type: true,
        chiefComplaint: true,
        isWalkIn: true,
        patient: {
          select: {
            id: true,
            mrn: true,
            firstName: true,
            lastName: true,
            phone: true,
            ...(req.user.role !== 'RECEPTIONIST' && {
              allergies: true,
              currentMedications: true,
              chronicConditions: true,
            }),
          },
        },
        doctor: {
          select: {
            firstName: true,
            lastName: true,
            speciality: true,
          },
        },
      },
    })

    const summary = {
      total: appointments.length,
      scheduled: appointments.filter((a) => a.status === 'SCHEDULED').length,
      completed: appointments.filter((a) => a.status === 'COMPLETED').length,
      cancelled: appointments.filter((a) => a.status === 'CANCELLED').length,
      noShow: appointments.filter((a) => a.status === 'NO_SHOW').length,
    }

    return successResponse(
      res,
      { summary, appointments },
      "Today's schedule retrieved."
    )
  } catch (error) {
    logger.error('Get today schedule error:', error)
    return errorResponse(res, "Failed to retrieve today's schedule.", 500, error)
  }
}


export const checkAvailability = async (req,res) => {
  try {
    const {doctorId,date,duration} = req.query

    const slotDuration = parseInt(duration, 10) || 30

    const dayStart = new Date(date)
    dayStart.setHours(8,0,0,0)

    const dayEnd = new Date(date)
    dayEnd.setHours(20,0,0,0)

    const bookedSlots = await prisma.appointment.findMany({
      where: {
        doctorId,
        status: 'SCHEDULED',
        scheduledAt: {
          gte: dayStart,
          lt: dayEnd
        }
      },
      select: {
        scheduledAt: true,
        endsAt: true,
        patient: { select: { firstName: true, lastName: true } },
      },
      orderBy: { scheduledAt: 'asc' },
    })

    const slots = []
    const cursor = new Date(dayStart)

    while(cursor <= new Date(dayEnd.getTime() - slotDuration * 60 * 1000)) {
      const slotStart = new Date(cursor)

      const slotEnd = new Date(cursor.getTime() + slotDuration * 60 * 1000)

      const isBooked = bookedSlots.some((b) => {
        const bStart = new Date(b.scheduledAt)
        const bEnd = new Date(b.endsAt)
        return slotStart < bEnd && slotEnd > bStart
      })
slots.push({
        time: slotStart.toISOString(),
        timeFormatted: slotStart.toLocaleTimeString('en-IN', {
          hour: '2-digit',
          minute: '2-digit',
          hour12: true,
        }),
        available: !isBooked,
      })

      cursor.setMinutes(cursor.getMinutes() + 30)
    }

    return successResponse(
      res,
      {
        date,
        doctorId,
        totalSlots: slots.length,
        availableSlots: slots.filter((s) => s.available).length,
        bookedSlots: slots.filter((s) => !s.available).length,
        slots,
      },
      'Availability retrieved.'
    )
  } catch (error) {
    logger.error('Check availability error:', error)
    return errorResponse(res, 'Failed to check availability.', 500, error)
  }
}