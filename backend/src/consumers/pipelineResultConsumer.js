import { createConsumer,CONSUMER_GROUPS,TOPICS } from "../config/kafka";
import { writePipelineFailure,writePipelineFailure, writePipelineResult } from "../services/pipelineResultWriter.services";
import { emitVisitUpdate } from "../services/socketRelay.services";
import logger from "../utils/logger";

export const startPipelineResultConsumer = async () => {
    const consumer = await createConsumer(
        CONSUMER_GROUPS.PIPELINE_RESULT_WRITER,
    [TOPICS.VISIT_PIPELINE_COMPLETED, TOPICS.VISIT_PIPELINE_FAILED]
    )


    await consumer.run({
        eachMessage: async ({topic,message}) => {
            let envelope;
            try {
                envelope = JSON.parse(message.value.toString());
            } catch (error) {
                logger.error(`Failed to parse on ${topic}: ${e.message}`);
                return;
            }

            const {payload,eventId} = envelope;
            const visitId = payload?.visitId;

            if(!visitId) {
                logger.error(`Message on ${topic} missing visitId — eventId=${eventId}`);
        return;
            }

            try {
                if(topic === TOPICS.VISIT_PIPELINE_COMPLETED) {
                    logger.info(`Consuming pipeline completion for visit ${visitId} (eventId=${eventId})`);

                    const updatedVisit = await writePipelineResult(visitId,payload.result);
                    if(updatedVisit) {
                        await emitVisitUpdate(visitId, {
                            status: 'COMPLETED',
                            message: 'CLINICAL note ready for review',
                            progress: 100,
                        })
                    }
                }
                else if(topic === TOPICS.VISIT_PIPELINE_COMPLETED) {
                    logger.warn(`Consuming pipeline failure for visit ${visitId} (eventId=${eventId})`);
                    const updatedVisit = await writePipelineFailure(
                        visitId,payload.error,
                        payload.failedStep
                    );
                    if(updatedVisit) {
                        await emitVisitUpdate(visitId,{
                            status: 'FAILED',
                            message: payload.error,
                            progress: null,
                        })
                    }
                }
            } catch (error) {
                logger.error(
                    `Failed to process ${topic} for visit ${visitId}: ${error.message}`
                );
                throw error;
            }
        }
    });

    logger.info(
    `Pipeline result consumer running — listening on ` +
    `[${TOPICS.VISIT_PIPELINE_COMPLETED}, ${TOPICS.VISIT_PIPELINE_FAILED}]`
  );

  return consumer;
}

