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