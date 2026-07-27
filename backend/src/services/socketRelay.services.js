
import logger from "../utils/logger";
async function emitVisitUpdate(visitId, update) {
  logger.debug(`[stub] Would emit to visit ${visitId}: ${JSON.stringify(update)}`);
}

module.exports = { emitVisitUpdate };
