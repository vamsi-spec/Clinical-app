import prisma from "../config/db.js"
import logger from "../utils/logger.js"
import { uploadAudio } from "../middleware/upload.middleware.js"
import { buildPatientContext } from "../services/patientContext.services.js"
import { publishAudioUploaded } from "../services/pipelineEvents.services.js"
import { cleanupTempFile } from "../middleware/upload.middleware.js"
import { successResponse,errorResponse,paginatedResponse,validationErrorResponse } from "../utils/apiResponse.js"

import fs from 'fs';




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


export const getVisitStatus = async (req,res) => {
    try {
        const {id} = req.params;

        const visit = await prisma.visit.findUnique({
            where: {id},
            select: {
                id: true,
                pipelineStatus: true,
                pipelineError: true,
                pipelineStartedAt: true,
                pipelineCompletedAt: true,
                doctorId: true
            }
        });
        if(!visit) {
            return errorResponse(res,404,'Visit not found')
        }

        if (req.user.role === 'DOCTOR' && visit.doctorId !== req.user.id) {
      return errorResponse(res, 403, 'You do not have access to this visit');
    }

    return successResponse(res, 200, 'Visit status retrieved', {
      visitId: visit.id,
      status: visit.pipelineStatus,
      error: visit.pipelineError,
      startedAt: visit.pipelineStartedAt,
      completedAt: visit.pipelineCompletedAt,
    });
  } catch (error) {
    logger.error(`getVisitStatus error: ${error.message}`);
    return errorResponse(res, 500, 'Failed to retrieve visit status', error);
  }
}


//Update visit
//Narrow field set - visitDate and specialty only
//Everything else is pipeline-managed

export const updateVisit = async (req,res) => {
    try {
        const {id} = req.params;
        const updates = req.body;

        const visit = await prisma.visit.findUnique({where: {id}});
        if(!visit) {
            return errorResponse(res,404,'Visit not found');
        }

        if (req.user.role === 'DOCTOR' && visit.doctorId !== req.user.id) {
      return errorResponse(res, 403, 'You do not have access to this visit');
    }

    const data = {};
    if (updates.visitDate) data.visitDate = new Date(updates.visitDate);
    if (updates.specialty) data.specialty = updates.specialty;

    const updatedVisit = await prisma.visit.update({
      where: { id },
      data,
    })

    logger.info(`Visit updated: ${id} by user ${req.user.id}`);
    return successResponse(res, 200, 'Visit updated successfully', { visit: updatedVisit });
  } catch (error) {
    logger.error(`updateVisit error: ${error.message}`);
    return errorResponse(res, 500, 'Failed to update visit', error);
  }
}

//ARCHIVE visit
//Admin only . soft delete - sets isArchived = true
//visits are never hard-deleted; stored in DB with isArchived = true.
//can be re-activated using unarchive call.

export const archiveVisit = async (req,res) => {
    try {
        const {id} = req.params;

        const visit = await prisma.visit.findUnique({where: {id}});
        if(!visit) {
            return errorResponse(res,404,'Visit not found');
        }

        if (visit.isArchived) {
            return errorResponse(res,400,'Visit is already archived');
        }

        const archivedVisit = await prisma.visit.update({
            where: {id},
            data: {isArchived: true},
        });


        logger.info(`Visit archived: ${id} by admin ${req.user.id}`);

    return successResponse(res, 200, 'Visit archived', { visit: archivedVisit });
  } catch (error) {
    logger.error(`archiveVisit error: ${error.message}`);
    return errorResponse(res, 500, 'Failed to archive visit', error);
  }
}


//Restore visit
export const restoreVisit = async (req,res) => {
    try {
        const {id} = req.params;

        const visit = await prisma.visit.findUnique({where: {id}});

        if(!visit) {
            return errorResponse(res,404,'Visit not found')
        }

        if(!visit.isArchived) {
            return errorResponse(res,400,'Visit is not archived')
        }

        const restoredVisit = await prisma.visit.update({
            where: {id},
            data: {isArchived: false},
        });

logger.info(`Visit restored: ${id} by admin ${req.user.id}`);

    return successResponse(res, 200, 'Visit restored', { visit: restoredVisit });
  } catch (error) {
    logger.error(`restoreVisit error: ${error.message}`);
    return errorResponse(res, 500, 'Failed to restore visit', error);
  }
}

//Retry Failed pipeline 

export const retryPipeline = async (req,res) => {
    try {
    const { id } = req.params;

    const visit = await prisma.visit.findUnique({ where: { id } });
    if (!visit) {
      return errorResponse(res, 404, 'Visit not found');
    }

    if (visit.pipelineStatus !== 'FAILED') {
      return errorResponse(res, 400, 'Only failed visits can be retried');
    }

    if (!visit.audioUrl) {
      return errorResponse(res, 400, 'No audio attached to this visit — re-upload required');
    }

    if (req.user.role === 'DOCTOR' && visit.doctorId !== req.user.id) {
      return errorResponse(res, 403, 'You do not have access to this visit');
    }

    const patientContext = await buildPatientContext(visit.patientId);

    await prisma.visit.update({
      where: { id },
      data: {
        pipelineStatus: 'AUDIO_UPLOADED',
        pipelineError: null,
        pipelineStartedAt: null,
        pipelineCompletedAt: null,
      },
    });

    const eventId = await publishAudioUploaded({
      visitId: id,
      audioUrl: visit.audioUrl,
      audioPublicId: visit.audioPublicId,
      patientContext,
      specialty: visit.specialty,
      numSpeakers: null
    });

    logger.info(`Pipeline retry requested for visit: ${id}`);

    return successResponse(res, 200, 'Pipeline retry initiated', { visitId: id });
  } catch (error) {
    logger.error(`retryPipeline error: ${error.message}`);
    return errorResponse(res, 500, 'Failed to retry pipeline', error);
  }
}


//UPLOAD visit audio
//This trigger point for entire ML pipeline

// --- FLOW ---
//1.Validate visit exists,belongs to requster, is in state that accepts audio
//2.Upload the temp file to cloudinary
//3.Gather patient context
//4.Update visit: audioUrl,audioPublicId,status=AUDIO_UPLOADED
//5.Publish visit.audio.uploaded to kafka
//6.Clean up local temp file
//7.Respond 202 Accepted immediately - the doctor does not wait for entire pipeline-> Real time arrive via SOCKET.io

export const uploadVisitAudio = async (req,res) => {
  let tempFilePath = null;
  try {
    const {id} = req.params
    const {numSpeakers} = req.body

    if(!req.file) {
      return errorResponse(res,400,'No audio file provided');
    }
    tempFilePath = req.file.path;

    const visit = await prisma.visit.findUnique({where: {id}});
    if(!visit) {
      await cleanupTempFile(tempFilePath)
      return errorResponse(res,404,'Visit not found');
    }

    if(req.user.role === 'DOCTOR' && visit.doctorId !== req.user.id) {
      await cleanupTempFile(tempFilePath)
      return errorResponse(res,403,'You do not have access to this visit');
    }

    const acceptableStatuses = ['PENDING','FAILED'];
    if(!acceptableStatuses.includes(visit.pipelineStatus)) {
      await cleanupTempFile(tempFilePath);
      return errorResponse(res,409,'Visit is already processing or completed');
    }

    if(visit.isArchived) {
      await cleanupTempFile(tempFilePath);
      return errorResponse(res,400,'Cannot upload audio to an archived visit');
    }

    //STEP - 1 Upload to Cloudinary
    const uploadResult = await uploadAudio(tempFilePath, {
      folder: `clinical-audio/${visit.patientId}`,
      publicIdPrefix: `visit-${visit.id}`,
    });

    logger.info(
      `Audio uploaded to Cloudinary for visit ${id}: ` +
      `${uploadResult.duration}s, ${(uploadResult.bytes / 1024 / 1024).toFixed(1)}MB`
    );

    const patientContext = await buildPatientContext(visit.patientId)

    const updatedVisit = await prisma.visit.update({
      where: {id},
      data: {
        audioUrl: uploadResult.url,
        audioPublicId: uploadResult.publicId,
        audioDuration: uploadResult.duration,
        pipelineStatus: 'AUDIO_UPLOADED',
        pipelineError: null,
        pipelineStartedAt: new Date(),
        pipelineCompletedAt: null,
      }
    });

    const eventId = await publishAudioUploaded({
      visitId: id,
      audioUrl: uploadResult.url,
      audioPublicId: uploadResult.publicId,
      specialty: visit.specialty,
      patientContext,
      numSpeakers: numSpeakers ? parseInt(numSpeakers,10) : null,
    });

    await prisma.visit.update({
      where: {id},
      data: { lastKafkaEventId: eventId },
    })

    logger.info(`Visit ${id} pipeline triggered — eventId=${eventId}`);

    return successResponse(res,202,'Audio uploaded - pipeline processing started',{
      visitId: updatedVisit.id,
      pipelineStatus: updatedVisit.pipelineStatus,
      audioUrl: updatedVisit.audioUrl,
      audioDuration: updatedVisit.audioDuration,
    })

  } catch (error) {
    logger.error(`uploadVisitAudio error: ${error.message}`);
    return errorResponse(res, 500, 'Failed to upload audio', error);
  } finally {
    if(tempFilePath) {
      await cleanupTempFile(tempFilePath)
    }
  }
}




