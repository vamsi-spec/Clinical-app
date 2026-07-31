import axios from 'axios';
import logger from "../utils/logger.js";

const ML_SERVICE_URL = process.env.ML_SERVICE_URL || 'http://ml-service:8000';

// REQUEST AUDIT HASH FROM ML SERVICE
//it is a synchronnus http call to ML service all other ml interaction goes through kafka

export const requestAuditHash = async (soapNote,visitId,finalizedAt) => {
    try {
        const response = await axios.post(`${ML_SERVICE_URL}/soap/hash`,
            {
                visit_id: visitId,
                soap_note: soapNote,
                finalized_at: finalizedAt
            },
            {
                timeout: 10000,
            }
        );

        return response.data.audit_hash;
    } catch (error) {
        logger.error(
      `Failed to generate audit hash for visit ${visitId}: ` +
      `${error.response?.data?.detail || error.message}`
    );
    throw new Error('Audit hash generation failed — ML service unavailable');
    }
}
