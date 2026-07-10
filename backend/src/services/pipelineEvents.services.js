import { publishEvent,TOPICS } from "../config/kafka";
import logger from "../utils/logger";

//PUBLISH: visit.audio.uploaded
//This is the event that kicks off entire ML pipeline.
//Payload contains everything the ML worker needs to run without any callback to node


export const publishAudioUploaded = async ({visitId,audioUrl,audioPublicId,specialty,patientContext,numSpeakers=null}) => {
    const eventId = await publishEvent(TOPICS.VISIT_AUDIO_UPLOADED,visitId,{
        visitId,audioUrl,audioPublicId,specialty,patientContext,numSpeakers
    });

    logger.info(`Published visit.audio.uploaded for visit ${visitId} (eventId=${eventId})`);
    return eventId;
}



