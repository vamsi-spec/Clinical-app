






//List Transfer requests
//For each role sees their relevant requests

import {prisma} from "../config/db.js";
import { errorResponse, successResponse } from "../utils/apiResponse"
import logger from "../utils/logger"

export const listTransfers = async (req,res) => {
    try {
        const {status,patientId,fromDoctorId,toDoctorId,page,limit,sortBy,sortOrder} = req.query
        const skip = (page - 1) * limit

        const where = {}

        if(status) where.status = status
        switch (req.user.role) {
            case 'DOCTOR':
                where.requestedBy = req.user.id
                break
            case 'RECEPTIONIST':
                where.status = status || 'APPROVED'
                break
            case 'ADMIN':
                if(fromDoctorId) where.fromDoctorId = fromDoctorId
                if(toDoctorId) where.toDoctorId = toDoctorId
                break
            case 'NURSE':
                where.fromDoctorId = req.user.assignedDoctorId
                break
            
            default:
                return errorResponse(res,'Access denied.',403)
        }

        if(patientId) where.patientId = patientId

        const [total,transfers] = await Promise.all([
            prisma.transferRequest.count({where}),
            prisma.transferRequest.findMany({
                where,
                orderBy: {[sortBy]: sortOrder},
                skip,
                take: limit,
                select: {
                    id: true,
                    status: true,
                    reason: true,
                    adminNote: true,
                    cancelNote: true,
                    createdAt: true,
                    updatedAt: true,
                    reviewedAt: true,
                    executedAt: true,
                    patient: {
                        select: {
                            id: true,
                            mrn: true,
                            firstName: true,
                            lastName: true,
                        },
                    },
                    fromDoctor: {
                        select: {
                            id: true,
                            firstName: true,
                            lastName: true,
                            speciality: true,
                        }
                    }
                }
            })
        ])
        paginatedResponse(
      res,
      transfers,
      { page, limit, total },
      'Transfer requests retrieved.'
    ) 
    } catch (error) {
        logger.error('List transfers error:', error)
    return errorResponse(res, 'Failed to retrieve transfer requests.', 500, error)
    }
}



//Get single transfer request

export const getTransfer = async (req,res) => {
    try {
        const {id} = req.params

        const transfer = await prisma.transferRequest.findUnique({
      where: { id },
      select: {
        id: true,
        status: true,
        reason: true,
        adminNote: true,
        cancelNote: true,
        createdAt: true,
        updatedAt: true,
        reviewedAt: true,
        executedAt: true,
        cancelledAt: true,
        requestedBy: true,
        reviewedBy: true,
        executedBy: true,
        patient: {
          select: {
            id: true,
            mrn: true,
            firstName: true,
            lastName: true,
            phone: true,
            chronicConditions: true,
            currentMedications: true,
          },
        },
        fromDoctor: {
          select: {
            id: true,
            firstName: true,
            lastName: true,
            specialty: true,
          },
        },
        toDoctor: {
          select: {
            id: true,
            firstName: true,
            lastName: true,
            specialty: true,
          },
        },
      },
    })

    if(!transfer) {
        return errorResponse(res,'Transfer request not found.',404)
    }

    if(req.user.role === 'DOCTOR' && transfer.requestedBy !== req.user.id) {
        return errorResponse(res,'Access denied.', 403)
    }

    if(req.user.role === 'RECEPTIONIST' && transfer.status !== 'APPROVED') {
        return errorResponse(res,'This transfer request is not yet approved.',403)
    }
    return successResponse(res,transfer,'Transfer request found.',200)
    } catch (error) {
        logger.error('Get transfer error:', error)
    return errorResponse(res, 'Failed to retrieve transfer request.', 500, error)
    }
}


//Request  Transfer
//Doctor only -> Raises a request for transfer

export const requestTransfer = async (req,res) => {
    try {
        const {patientId, toDoctorId,reason} = req.body;

        const patient = await prisma.patient.findFirst({
            where: {
                id: patientId,
                doctorId: req.user.id,
                isActive: true,
                deletedAt: null,
            },
            select: {
                id: true,
                mrn: true,
                firstName: true,
                lastName: true,
                doctorId: true,
            },
        })

        if(!patient){
            return errorResponse(res,'Patient not found.',404)
        }

        if(toDoctorId === req.user.id){
            return errorResponse(res,'Cannot transfer patient to yourself.',400)
        }

        const toDoctor = await prisma.user.findUnique({
            where: {id: toDoctorId},
            select: {
                id: true,
                role: true,
                isActive: true,
                firstName: true,
                lastName: true,
                speciality: true,
            },
        })

        if(!toDoctor) {
            return errorResponse(res,'Target doctor not found.',404)
        }

        if(toDoctor.role !== 'DOCTOR') {
            return errorResponse(res,'Target user is not a doctor.',400)
        }

        if(!toDoctor.isActive) {
            return errorResponse(res,'Target doctor is inactive',400)
        }

        //check if this request is present or not
        const existingRequest = await prisma.transferRequest.findFirst({
            where: {
                patientId,
                status: {in: ['PENDING','APPROVED']},
            },
            select: {id: true,status: true},
        })

        if (existingRequest) {
      return errorResponse(
        res,
        `A transfer request for this patient is already ${existingRequest.status.toLowerCase()}. Please wait for it to be resolved before raising a new one.`,
        409
      )
    }

    const transfer = await prisma.transferRequest.create({
      data: {
        patientId,
        fromDoctorId: req.user.id,
        toDoctorId,
        requestedBy: req.user.id,
        reason,
        status: 'PENDING',
      },
      select: {
        id: true,
        status: true,
        reason: true,
        createdAt: true,
        patient: {
          select: { mrn: true, firstName: true, lastName: true },
        },
        fromDoctor: {
          select: { firstName: true, lastName: true },
        },
        fromDoctor: {
          select: { firstName: true, lastName: true },
        },
        toDoctor: {
          select: { firstName: true, lastName: true, specialty: true },
        },
      },
    })

    logger.info(
      `Transfer requested: patient ${patient.mrn} from Dr. ${req.user.email} to Dr. ${toDoctor.firstName} ${toDoctor.lastName}. Reason: ${reason}`
    )

    if(req.io) {
        req.io.emit('transfer:new',{
            transferId: transfer.id,
            patientMrn: patient.mrn,
            romDoctor: `Dr. ${req.user.firstName} ${req.user.lastName}`,
        toDoctor: `Dr. ${toDoctor.firstName} ${toDoctor.lastName}`,
        })
    }

    return successResponse(
      res,
      transfer,
      `Transfer request submitted for patient ${patient.mrn}. Awaiting admin approval.`,
      201
    )
  } catch (error) {
    logger.error('Request transfer error:', error)
    return errorResponse(res, 'Failed to submit transfer request.', 500, error)
  }
}


//Review Transfer - Approve or Reject
//Admin only
export const reviewTransfer = async (req,res) => {
  try {
    const {id} = req.params
    const {decision,adminNote} = req.body

    const transfer = await prisma.transferRequest.findUnique({
      where: {id},
      select: {
        id: true,
        status: true,
        patientId: true,
        fromDoctorId: true,
        toDoctorId: true,
        patient: {
          select: {mrn: true,firstName: true,lastName: true},
        },
        fromDoctor: {
          select: {firstName: true,lastName: true},
        },
        toDoctor: {
          select: {firstName: true,lastName: true},
        },
      }
    })

    if(!transfer) {
      return errorResponse(res,'Transfer request not found.',404)
    }

    if(transfer.status !== 'PENDING') {
      return errorResponse(res,`Cannot review a transfer request that is already ${transfer.status.toLowerCase()}.`,400)
    }
    const toDoctor = await prisma.user.findUnique({
      where: {id: transfer.toDoctorId},
      select: {isActive: true},
    })

    if(decision === 'APPROVED' && !toDoctor?.isActive) {
      return errorResponse(res,'Cannot approve - target doctor account is currently inactive.',400)
    }

    await prisma.transferRequest.update({
      where: {id},
      data: {
        status: decision,
        adminNote,
        reviewedBy: req.user.id,
        reviewedBy: new Date()
      },
    })

    logger.info(`Transfer ${decision} by admin ${req.user.email}: patient ${transfer.patient.mrn}. Note: ${adminNote}`)

    if(req.io) {
      req.io.emit('transfer:reviewed',{
        transferId: id,
        decision,
        patientMrn: transfer.patient.mrn,
      })
    }

    const message = decision === 'APPROVED' ? `Transfer approved for patient ${transfer.patient.mrn}. Receptionist can now execute the transfer.`
        : `Transfer rejected for patient ${transfer.patient.mrn}. Doctor has been notified.`
    
    return successResponse(res,null,message)

  } catch (error) {
    logger.error('Review transfer error:', error)
    return errorResponse(res,'Failed to review transfer request.',500,error)
  }
}

//Excecute Transfer
//Receptionist only
//Executes an admin approved transfer

export const executeTransfer = async (req,res) => {
  try {
    const {id} = req.params
    const {confirmationNote} = req.body

    const transfer = await prisma.transferRequest.findUnique({
      where: {id},
      select: {
        id: true,
        status: true,
        patientId: true,
        fromDoctorId: true,
        toDoctorId: true,
        patient: {
          select: {
            mrn: true,
            firstName: true,
            lastName: true,
            doctorId: true,
          },
        },
        fromDoctor: {
          select: {firstName: true,lastName: true},
        },
        toDoctor: {
          select: {firstName: true,lastName: true,speciality: true},
        },
      },
    })

    if(!transfer) {
      return errorResponse(res,'Transfer request not found.',404)
    }

    if(transfer.status !== 'APPROVED') {
      return errorResponse(res,`Cannot exexute a transfer that is not approved.${transfer.status.toLowerCase()}`,400)
    }

    if(transfer.patient.doctorId !== transfer.fromDoctorId) {
      return errorResponse(res,'Patient is no longer under the original doctor.This transfer may be outdated. Contact admin.',409)
    }

    const toDoctor = await prisma.user.findUnique({
      where: {id: transfer.toDoctorId},
      select: {isActive: true},
    })

    if(!toDoctor?.isActive) {
      return errorResponse(res,'Cannot execute - target doctor account is inactive. Please contact admin.',400)
    }

    await prisma.$transaction([
      prisma.patient.update({
        where: {id: transfer.patientId},
        data: {doctorId: transfer.toDoctorId},
      }),

      prisma.transferRequest.update({
        where: {id},
        data: {
          status:'COMPLETED',
          executedBy: req.user.id,
          executedAt: new Date(),
          adminNote: confirmationNote ? `${transfer.adminNote || ''}\nExecution note: ${confirmationNote}`.trim()
            : transfer.adminNote,
        }
      })
    ])

    logger.info(
      `Transfer executed by receptionist ${req.user.email}: patient ${transfer.patient.mrn} moved from Dr. ${transfer.fromDoctor.firstName} ${transfer.fromDoctor.lastName} to Dr. ${transfer.toDoctor.firstName} ${transfer.toDoctor.lastName}`
    )

    if(req.io) {
      req.io.emit('transfer:completed',{
        transferId: id,
        patientMrn: transfer.patient.mrn,
        newDoctorId: transfer.toDoctorId,
      })

      req.io.emit('patient:assigned',{patientMrn})
    }

    return successResponse(res,null,`Transfer executed for patient ${transfer.patient.mrn}. The patient is now under the care of Dr. ${transfer.toDoctor.firstName} ${transfer.toDoctor.lastName}`)

  } catch (error) {
    logger.error('Execute transfer error:',error)
    return errorResponse(res,'Failed to execute transfer.',500,error)
  }
}

//Cancel transfer request
//doctor - can cancel their own pending req  ,Admin - can cancel any pending or approved req

export const cancelTransfer = async (req,res) => {
  try {
    const {id} = req.params
    const {cancelNote} = req.body

    const transfer = await prisma.transferRequest.findUnique({
      where: {id},
      select: {
        id: true,
        status: true,
        requestedBy: true,
        patient: {
          select: {mrn: true,firstName: true,lastName: true},
        }
      }
    })

    if(!transfer) {
      return errorResponse(res,'Transfer request not found.',404)
    }

    if(req.user.role === 'DOCTOR' && transfer.requestedBy !== req.user.id) {
      return errorResponse(res,'You can only cancel your own transfer request.',403)
    }

    if(req.user.role === 'DOCTOR' && transfer.status !== 'PENDING') {
      return errorResponse(
        res,
        `Cannot cancel a request that is already ${transfer.status.toLowerCase()}. Contact admin if needed.`,
        400
      )
    }

     if (['COMPLETED', 'CANCELLED', 'REJECTED'].includes(transfer.status)) {
      return errorResponse(
        res,
        `Transfer request is already ${transfer.status.toLowerCase()}.`,
        400
      )
    }

    await prisma.transferRequest.update({
      where: {id},
      data: {
        status: 'CANCELLED',
        cancelledBy: req.user.id,
        cancelledAt: new Date(),
        cancelNote,
      },
    })

    logger.info(
      `Transfer cancelled by ${req.user.role} ${req.user.email}: patient ${transfer.patient.mrn}. Note: ${cancelNote}`
    )

    return successResponse(
      res,
      null,
      `Transfer request for patient ${transfer.patient.mrn} has been cancelled.`
    )
  } catch (error) {
    logger.error('Cancel transfer error:', error)
    return errorResponse(res, 'Failed to cancel transfer request.', 500, error)
  }
}