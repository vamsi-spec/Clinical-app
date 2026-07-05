import { Kafka,logLevel } from "kafkajs";
import logger from "../utils/logger.js";

export const TOPICS = {
    VISIT_AUDIO_UPLOADED:      'visit.audio.uploaded',
    VISIT_TRANSCRIPTION_DONE:  'visit.transcription.done',
    VISIT_PIPELINE_PROGRESS:   'visit.pipeline.progress',
    VISIT_PIPELINE_COMPLETED:  'visit.pipeline.completed',
    VISIT_PIPELINE_FAILED:     'visit.pipeline.failed',
    DRUG_INTERACTION_DETECTED: 'drug.interaction.detected',

    PATIENT_VITALS_RECORDED:   'patient.vitals.recorded',
    AUDIT_EVENTS:              'audit.events',

}

export const CONSUMER_GROUPS = {
  PIPELINE_RESULT_WRITER: 'backend-pipeline-result-writer',
  PIPELINE_PROGRESS_RELAY: 'backend-pipeline-progress-relay',
  DRUG_ALERT_NOTIFIER: 'backend-drug-alert-notifier',
};

//KAFKA CLIENT , single shared client instance - kafkajs recommends one cilent per application with multiple producers/consumers from it

export const kafka = new Kafka({
  clientId: 'clinical-note-backend',
  brokers:(process.env.KAFKA_BROKERS || 'localhost:9092').split(','),
  logLevel: logLevel.WARN,
  retry: {
    initialRetryTime: 300,
    retries: 8
  }
})


//PRODUCER - SINGLETON
//One producer instance is reused accross the app.
//creating a new producer per publish call adds unnecessary connection overhead - kafkajs producers

let producer = null;
let producerConnected = false;

export const getProducer = async()=>{
  if(!producer) {
    producer = kafka.producer({
      allowAutoTopicCreation: true,
      transactionTimeout: 30000,
    })
  }

  if(!producerConnected) {
    await producer.connect();
    producerConnected =true;
    logger.info(`Kafka producer connected`)
  }

  return producer;
}

export const publishEvent = async (topic,key,payload) => {
  try {
    const prod = await getProducer();

    const envelope = {
      eventId: require('crypto').randomUUID(),
      publishedAt: new Date().toISOString(),
      source: 'backend',
      payload,
    }

    await prod.send({
      topic,
      messages: [
        {
          key,   // typically visitId — ensures ordering per visit
                 // (Kafka guarantees order within a partition,
                 // and same key always goes to the same partition)
          value: JSON.stringify(envelope),
        },
      ]
    });
    
    logger.info(`Published event ${topic},key=${key} eventId=${envelope.eventId}`);
    return envelope.eventId;
  } 
  catch(error) {
    logger.error('Failed to publish event', {topic,key,error});
    throw error;
  }
};


// CONSUMER FACTORY
// Creates a consumer for a given group + topics. 
// Returns the consumer so the caller controls its lifecycle (run/disconnect) 
// this keeps this config file free of business logic.

export const createConsumer = async (groupId,topics) => {
  const consumer = kafka.consumer({
    groupId,
    sessionTimeout: 30000,
    heartbeatInterval: 3000
  });
  await consumer.connect();

  for(const topic of topics) {
    await consumer.subscribe({topic,fromBeginning: false});
  }

  logger.info(`Consumer created for group ${groupId} for topics ${topics.join(',')}`);

  return consumer
}

// ============================================
// GRACEFUL SHUTDOWN
// Called from server.js on SIGTERM/SIGINT.
// Kafka connections must be closed cleanly or
// the consumer group rebalance takes longer
// on next startup (stale member detection timeout).
// ============================================

export const disconnectKafka = async () => {
  if(producer && producerConnected) {
    await producer.disconnect();
    producerConnected = false;
    logger.info(`Kafka producer disconnected`);
  }

  
}
