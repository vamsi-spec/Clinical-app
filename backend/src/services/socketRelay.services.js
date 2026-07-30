
import logger from "../utils/logger";

let io = null;

export const setIO = (socketIOInstance) => {
  io = socketIOInstance;
  logger.info('Socket IO instance registered with socketRelay service')
}


//One room per visit: "visit:<visitId>"


export const visitRoom = (visitId) => {
  return `visit:${visitId}`
}


//Emit visit update
//Called by both kafka consumers(progress consumer and completion failure)

export const emitVisitUpdate = async (visitId,update) => {
  if(!io) {
    logger.warn(`emitVisitUpdate called before Socket.IO was initialized — visit ${visitId} update dropped`)
    return;
  }

  const room = visitRoom(visitId)
const eventPayload = {
  visitId,
  ...update,
  emittedAt: new Date().toISOString(),
};

io.to(room).emit('visit:update',eventPayload);

logger.debug(`Emitted visit:update to room ${room}: ` +
    `status=${update.status}, progress=${update.progress}`)
}









