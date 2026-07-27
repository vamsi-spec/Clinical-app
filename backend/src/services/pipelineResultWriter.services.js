import { prisma } from "../config/db.js";
import logger from "../utils/logger.js";

//Called by kafka consumer when a visit.pipeline.completed event arrives.

export const writePipelineResult = async (visitId,result) => {
    const {transcription,ner,soap,cds,inconsistencies,explainable_note,billing,drug_interactions,generation_metadata} = result;

    return prisma.$transaction(async (tx) => {
        const visit = await tx.visit.findUnique({where: {id: visitId}});
        if(!visit) {
            logger.warn(`writePipelineResult: visit ${visitId} no longer exists — discarding result`);
            return null;
        }

        await tx.soapNote.upsert({
            where: {visitId},
            create: {
                visitId,
                subjective: soap.subjective,
                objective: soap.objective,
                assessment: soap.assessment,
                plan: soap.plan,
                differentials: cds.differentials || [],
                redFlags: cds.red_flags || [],
                missedFollowups: cds.missed_followups || [],
                inconsistencies: inconsistencies || {},
                explainableNote: explainable_note || {},
                versions: [],
                isFinalized: false,
            },
            update: {
                subjective: soap.subjective,
                objective: soap.objective,
                assessment: soap.assessment,
                plan: soap.plan,
                differentials: cds.differentials || [],
                redFlags: cds.red_flags || [],
                missedFollowups: cds.missed_followups || [],
                inconsistencies: inconsistencies || {},
                explainableNote: explainable_note || {},
            }
        });
        await tx.nERResult.upsert({
            where: {visitId},
            create: {
                visitId,
                medications: ner.medications || [],
                symptoms: ner.symptoms || [],
                diagnoses: ner.diagnoses || [],
                rawSegments: transcription.segments || []
            },
            update: {
                medications: ner.medications || [],
                symptoms: ner.symptoms || [],
                diagnoses: ner.diagnoses || [],
                rawSegments: transcription.segments || []
            }
        });

        await tx.billingCode.upsert({
            where: {visitId},
            create: {
                visitId,
                icd10Codes: billing.icd10_codes || [],
                cptCode: billing.cpt_code || {},
                codingGaps: billing.coding_gaps || [],
                confirmedCodes: [],
                isConfirmed: false,
            },
            update: {
        icd10Codes: billing.icd10_codes || [],
        cptCode: billing.cpt_code || {},
        codingGaps: billing.coding_gaps || [],
      },
        });

        await tx.drugInteraction.deleteMany({ where: { visitId } });

    const interactions = drug_interactions?.interactions || [];
    if (interactions.length > 0) {
      await tx.drugInteraction.createMany({
        data: interactions.map((interaction) => ({
          visitId,
          drug1: interaction.drug1,
          drug2: interaction.drug2,
          severity: interaction.severity,
          description: interaction.description,
          source: interaction.source,
        })),
      });
    }
    const updatedVisit = await tx.visit.update({
      where: { id: visitId },
      data: {
        pipelineStatus: 'COMPLETED',
        pipelineCompletedAt: new Date(),
        audioDuration: transcription.duration || visit.audioDuration,
      },
    });
    logger.info(
      `Pipeline result persisted for visit ${visitId}: ` +
      `${interactions.length} drug interactions, ` +
      `${(billing.icd10_codes || []).length} billing codes, ` +
      `duration=${generation_metadata?.total_pipeline_duration_seconds}s`
    );
    return updatedVisit;
    })
}

export const writePipelineFailure = async (visitId,error,failedStep) => {
    const visit = await prisma.visit.findUnique({where: {id:visitId}});
    if(!visit) {
        logger.warn(`writePipelineFailure: visit ${visitId} no longer exists`);
        return null;
    }

    const updatedVisit = await prisma.visit.update({
        where: {id: visitId},
        data: {
            pipelineStatus: 'FAILED',
            pipelineError: `${failedStep ? `[${failedStep}] ` : ''}${error}`,
            pipelineCompletedAt: new Date(),
        }
    });

    logger.warn(`Visit ${visitId} marked FAILED: ${error}`);
    return updatedVisit;
}


