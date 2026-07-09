import prisma from "../config/db.js"
import logger from "../utils/logger.js"

import { successResponse,errorResponse,paginatedResponse,validationErrorResponse } from "../utils/apiResponse.js"



//CREATE VISIT
//Doctor or admin only. Creates the visit shell with pending status - no audio,no pipeline output yet.
//Audio upload attaches to this VISIT ID and moves status to AUDIO_UPLOADED - trigger pipeline

export const createVisit = async (req,res)=>{
    try{
        const {patientId, doctorId, appointmentId, visitDate, specialty} = req.body

        //Doctors can only create visits for themselves
        //Admin can create on behalf of any doctor
        let resolvedDoctorId = doctorId
        if(req.user.role === 'DOCTOR') {
            resolvedDoctorId = req.user.id;
        }
        else if (req.user.role === 'ADMIN' && !doctorId) {
            return errorResponse(res,400,'doctorId is required when creating a visit as admin')
        }

        const patient = await prisma.patient.findUnique({
            where: {id: patientId}
        });
        if(!patient) {
            return errorResponse(res,404,'Patient not found');
        }
        if(patient.isArchived) {
            return errorResponse(res,400,'Cannot create a visit for an archived patient');
        }

        const doctor = await prisma.user.findUnique({
            where: {id: resolvedDoctorId}
        });

        if(!doctor || doctor.role !== 'DOCTOR') {
            return errorResponse(res,404,'Doctor not found or not authorized');
        }

        if(!doctor.isActive) {
            return errorResponse(res,400,'Doctor account is deactivated');
        }

        if(appointmentId) {
            const appointment = await prisma.appointment.findUnique({
                where: {id: appointmentId}
            });
            if(!appointment) {
                return errorResponse(res,404,'Appointment not found');
            }

            const existingVisit = await prisma.visit.findUnique({
                where: {appointmentId}
            });
            if(existingVisit) {
                return errorResponse(res,409,'This appoinment already has a visit linked to it');
            }
        }

        const visit = await prisma.visit.create({
            data: {
                patientId,
                doctorId: resolvedDoctorId,
                appointmentId: appointmentId || null,
                visitDate: visitDate ? new Date(visitDate) : new Date(),
                specialty: specialty || doctor.specialty || 'general',
                pipelineStatus: 'PENDING',
            },
            include: {
        patient: { select: { id: true, firstName: true, lastName: true, mrn: true } },
        doctor: { select: { id: true, name: true, specialty: true } },
      },
        })
        logger.info(`Visit created: ${visit.id} for patient ${patientId} by doctor ${resolvedDoctorId}`);

    return successResponse(res, 201, 'Visit created successfully', { visit });
  } catch (error) {
    logger.error(`createVisit error: ${error.message}`);
    return errorResponse(res, 500, 'Failed to create visit', error);
  }
}


//List Visits
//ADMIN -> All visits
//Doctor-> own vists only
//Nurse -> visits of assigned doctor only
//Receptionist -> no clinical visits access (work with appointments only, not visits)

export const listVisits = async (req,res) => {
    try {
        const {patientId,doctorId,status,dateFrom,dateTo,includeArchived,page,limit} = req.query;

        if(req.user.role === 'RECEPTIONIST') {
            return errorResponse(res,403,'Receptionist does not have access to visits')
        }

        const pageNum = parseInt(page,10);
        const limitNum = parseInt(limit,10);
        const skip = (pageNum - 1) * limitNum;

        const where = {};
        if(req.user.role === 'DOCTOR') {
            where.doctorId = req.user.id;
        }
        else if(req.user.role === 'NURSE') {
            if(!req.user.assignedDoctorId) {
                return successResponse(res,200,'Nurse has no assigned doctor',{
                    visits: [],
                    pagination: {total: 0,page: pageNum,limit: limitNum,pages: 0}
                })
            }
            where.doctorId = req.user.assignedDoctorId;
        }

        if(patientId) where.patientId = patientId;
        if(doctorId && req.user.role === 'ADMIN') where.doctorId = doctorId;
        if(status) where.pipelineStatus = status
        if(includeArchived !== 'true') where.isArchived = false

        if(dateFrom || dateTo) {
            where.visitDate = {};
            if(dateFrom) where.visitDate.gte = new Date(dateFrom);
            if(dateTo) where.visitDate.lte = new Date(dateTo);
        }

        const [visits,total] = await Promise.all([
            prisma.visit.findMany({
                where,
                skip,
                take: limitNum,
                orderBy: {visitDate: 'desc'},
                include: {
                    patient: {select: {id: true,firstName: true,lastName: true,mrn:true}},
                    doctor: {select: {id: true,name: true,specialty: true}},
                    soapNote: {select: {id: true,isFinalized: true}},
                },
            }),
            prisma.visit.count({where})
        ])

        return paginatedResponse(res, 200, 'Visits retrieved', visits, {
      total, page: pageNum, limit: limitNum, pages: Math.ceil(total / limitNum),
    });
  } catch (error) {
    logger.error(`listVisits error: ${error.message}`);
    return errorResponse(res, 500, 'Failed to list visits', error);
  }
}


//Get a particular visit detail
//Full record including all pipeline output -> SOAP note,NER results,billing codes,drug interaction. this is what VISIT page shows

export const getVisit = async (req,res) => {
    try {
        const {id} = req.params;

        const {visit} = await prisma.visit.findUnique({
            where: {id},
            include: {
                patient: true,
                doctor: {select: {id: true,name: true,specialty: true,email:true}},
                appointment: true,
                soapNote: true,
                nerResult: true,
                billingCode: true,
                drugInteractions: true,
            }
        })

        if(!visit) {
            return errorResponse(res,404,'Visit not found');
        }

        if (req.user.role === 'DOCTOR' && visit.doctorId !== req.user.id) {
      return errorResponse(res, 403, 'You do not have access to this visit');
    }
    if (req.user.role === 'NURSE' && visit.doctorId !== req.user.assignedDoctorId) {
      return errorResponse(res, 403, 'You do not have access to this visit');
    }
    if (req.user.role === 'RECEPTIONIST') {
      return errorResponse(res, 403, 'Receptionists do not have access to clinical visit records');
    }

    return successResponse(res, 200, 'Visit retrieved', { visit });
    } catch (error) {
        logger.error(`getVisit error: ${error.message}`);
    return errorResponse(res, 500, 'Failed to retrieve visit', error);
    }
}
