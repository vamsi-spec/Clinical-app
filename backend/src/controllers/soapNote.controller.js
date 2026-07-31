import prisma from "../config/db.js";
import logger from "../utils/logger.js";
import { successResponse,errorResponse } from "../utils/apiResponse.js";
import {requestAuditHash} from "../services/mlServiceClient.services.js";

export const getSoapNote = async (req,res) => {
    try {
        const {visitId} = req.params

        const visit = await prisma.visit.findUnique({where: {id: visitId}});

        if(!visit) return errorResponse(res,404,'Visit not found')
        
        if(req.user.role === 'DOCTOR' && visit.doctorId !== req.user.id) {
            return errorResponse(res,403,'You do not have access to this visit');
        }

        const soapNote = await prisma.SOAPNote.findUnique({where: {visitId}});

        if(!soapNote) {
            return errorResponse(res,404,'SOAP note not yet generated for this visit');
        }

        return successResponse(res,200,'SOAP note retrieved', {soapNote});
    } catch (error) {
        logger.error(`getSoapNote error: ${error.message}`);
        return errorResponse(res, 500, 'Failed to retrieve SOAP note', error);
    }
}

//Edit soap note
export const editSoapNote = async (req,res) => {
    try {
        const {visitId} = req.params;
        const {subjective,objective,assessment,plan,editReason} = req.body;

        const visit = await prisma.visit.findUnique({where: {id: visitId}});

        if(!visit) return errorResponse(res,404,'Visit not found');

        if(req.user.role === 'DOCTOR' && visit.doctorId !== req.user.id) {
            return errorResponse(res,403,'You do not have access to this visit');
        }

        const currentNote = await prisma.SOAPNote.findUnique({where: {visitId}})

        if(!currentNote) {
            return errorResponse(res,404,'SOAP note not yet generated for this visit');
        }

        if(currentNote.isFinalized) {
            return errorResponse(
                res, 409,
                'This note has already been finalized and signed. ' +
                'Finalized notes are immutable — contact an administrator ' +
                'if a formal amendment is required.'
            );
        }

        const versionSnapshot = {
            soap: {
                subjective: currentNote.subjective,
                objective: currentNote.objective,
                assessment: currentNote.assessment,
                plan: currentNote.plan,
            },
            editedBy: req.user.id,
            editedAt: new Date().toISOString(),
            editReason: editReason || null,
        }

        const existingVersions = Array.isArray(currentNote.versions) ? currentNote.versions: [];

        const updatedNote = await prisma.SOAPNote.update({
            where: {visitId},
            data: {
                subjective: subjective ?? currentNote.subjective,
                objective: objective ?? currentNote.objective,
                assessment: assessment ?? currentNote.assessment,
                plan: plan ?? currentNote.plan,
                versions: [...existingVersions, versionSnapshot],
            }
        });

        logger.info(`SOAP note edited for visit ${visitId} by user ${req.user.id}`)

        return successResponse(res,200,'SOAP note updated',{soapNote: updatedNote});
        
    } catch (error) {
        logger.error(`editSoapNote error: ${error.message}`);
        return errorResponse(res, 500, 'Failed to update SOAP note', error);
    }
}


//Finalize soap note
export const finalizeSoapNote = async (req,res) => {
    try {
        const {visitId} = req.params;
        const {subjective,objective,assessment,plan} = req.body || {}
        const visit = await prisma.visit.findUnique({where: {id: visitId}});

        if(!visit) {
            return errorResponse(res,404,'Visit not found');
        }

        //Only doctors and admins finalize notes
        if(req.user.role === 'DOCTOR' && visit.doctorId !== req.user.id) {
            return errorResponse(res,403,'You do not have access to this visit');
        }
        const currentNote = await prisma.SOAPNote.findUnique({
            where: {visitId}
        })

        if(!currentNote) {
            return errorResponse(res,404,'SOAP note not found for this visit')
        }

        if(currentNote.isFinalized) {
            return errorResponse(res,409,'SOAP note already finalized')
        }

        //If the pipeline flagges CRITICAL red flags, requires doctor acknowledgment before signing
        const redFlags = Array.isArray(currentNote.redFlags) ? currentNote.redFlags: [];
        const hasCriticalFlags = redFlags.some((f) => typeof f === 'string' && f.toUpperCase().includes('ALLERGY VIOLATION'))

        if (hasCriticalFlags && !req.body?.acknowledgeCriticalFlags) {
            return errorResponse(
                res, 422,
                'This note has unacknowledged critical safety flags (allergy violations). ' +
                'Review them and resubmit with acknowledgeCriticalFlags: true to proceed.'
            );
        }

        const hasInlineEdit = [subjective, objective, assessment, plan].some((v) => v !== undefined);
        let versions = Array.isArray(currentNote.versions) ? currentNote.versions : [];

        if (hasInlineEdit) {
            versions = [
                ...versions,
                {
                soap: {
                    subjective: currentNote.subjective,
                    objective: currentNote.objective,
            assessment: currentNote.assessment,
            plan: currentNote.plan,
          },
          editedBy: req.user.id,
          editedAt: new Date().toISOString(),
          editReason: 'Final edit prior to signing',
        },
      ];
    }

    const finalSoap = {
      subjective: subjective ?? currentNote.subjective,
      objective: objective ?? currentNote.objective,
      assessment: assessment ?? currentNote.assessment,
      plan: plan ?? currentNote.plan,
    };

    const finalizedAt = new Date().toISOString();

    const auditHash = await requestAuditHash(finalSoap, visitId, finalizedAt);

    const finalizedNote = await prisma.sOAPNote.update({
      where: { visitId },
      data: {
        ...finalSoap,
        versions,
        isFinalized: true,
        finalizedAt: new Date(finalizedAt),
        finalizedBy: req.user.id,
        auditHash,
      },
    });

    logger.info(
      `SOAP note finalized for visit ${visitId} by user ${req.user.id} — hash=${auditHash.slice(0, 16)}...`
    );

    return successResponse(res, 200, 'SOAP note finalized and signed', {
      soapNote: finalizedNote,
    });

    } catch (error) {
        logger.error(`finalizeSoapNote error: ${error.message}`);
        return errorResponse(res, 500, 'Failed to finalize SOAP note', error);
    }
}
