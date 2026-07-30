import { createConsumer,CONSUMER_GROUPS,TOPICS } from "../config/kafka";
import { emitVisitUpdate } from "../services/socketRelay.services";
import prisma from "../config/db.js";
import logger from "../utils/logger.js";
import { PipelineStatus } from "@prisma/client";

//Pipeline status mapping

const VALID_STATUSES = new Set([
  'TRANSCRIBING', 'DIARIZING', 'CORRECTING', 'EXTRACTING_ENTITIES',
  'GENERATING_SOAP', 'CHECKING_INCONSISTENCIES', 'MAPPING_EXPLAINABILITY',
  'CHECKING_BILLING', 'CHECKING_DRUGS', 'COMPLETED', 'FAILED',
]);

export const startPipelineProgressConsumer = async() => {
    const consumer = await createConsumer(CONSUMER_GROUPS.PIPELINE_PROGRESS_RELAY,[TOPICS.VISIT_PIPELINE_PROGRESS])

    await consumer.run({
        eachMessage: async ({message}) => {
            let envelope;
            try {
                envelope = JSON.parse(message.value.toString());
            } catch (error) {
                logger.error(`Failed to parse progress message: ${e.message}`);
                return;
            }

            const {payload} = envelope;
            const {visitId,status,message: progressMessage,progress} = payload;

            if(!visitId) return;

            if(VALID_STATUSES.has(status)) {
                try {
                    await prisma.visit.update({
                        where: {id: visitId},
                        data: {PipelineStatus: status},
                    });
                } catch (error) {
                    logger.warn(`Could not update Visit status for ${visitId}: ${error.message}`);
                }
            }

            await emitVisitUpdate(visitId, {
                status,message: progressMessage,progress
            });
        }
    });

    logger.info(
    `✅ Pipeline progress consumer running — listening on [${TOPICS.VISIT_PIPELINE_PROGRESS}]`
  );

  return consumer;
}





