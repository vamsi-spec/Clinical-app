#!/bin/bash
# Run manually or as a one-off container in CI/CD before
# the backend/ml-service containers start, in environments
# where KAFKA_AUTO_CREATE_TOPICS_ENABLE is false (production).

set -e

KAFKA_BROKER="${KAFKA_BROKER:-localhost:9092}"
PARTITIONS="${PARTITIONS:-3}"
REPLICATION="${REPLICATION:-1}"  # set to 3 in production multi-broker setup

TOPICS=(
  "visit.audio.uploaded"
  "visit.transcription.done"
  "visit.pipeline.progress"
  "visit.pipeline.completed"
  "visit.pipeline.failed"
  "drug.interaction.detected"
  "patient.vitals.recorded"
  "audit.events"
)

echo "Creating Kafka topics on $KAFKA_BROKER..."

for topic in "${TOPICS[@]}"; do
  kafka-topics --bootstrap-server "$KAFKA_BROKER" \
    --create --if-not-exists \
    --topic "$topic" \
    --partitions "$PARTITIONS" \
    --replication-factor "$REPLICATION"
  echo "  ✅ $topic"
done

echo "All topics created."
kafka-topics --bootstrap-server "$KAFKA_BROKER" --list
