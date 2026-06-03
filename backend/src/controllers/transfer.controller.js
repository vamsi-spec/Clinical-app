






//List Transfer requests
//For each role sees their relevant requests

import { prisma } from "../config/db"
import { errorResponse, successResponse } from "../utils/apiResponse"

export const listTransfers = async (req,res) => {
    try {
        const {status,patientId,fromDoctorId,toDoctorId,page,limit,sortBy,sortOrder} = req.query
        const skip = (page - 1) * limit

        const where = {}

        if(status) where.status = status
        switch (req.user.role) {
            case 'DOCTOR':
                where.requestBy = req.user.id
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