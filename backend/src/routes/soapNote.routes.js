import { Router } from "express";
import { protect } from "../middleware/auth.middleware";
import { auditLog } from "../middleware/audit.middleware";
import { adminOnly, doctorAndAdmin } from "../middleware/role.middleware";
import { validate, validateParams } from "../middleware/validate.middleware";
import { getSoapNote,editSoapNote, getSoapNoteHistory, verifySoapNoteIntegrity } from "../controllers/soapNote.controller";
import { finalizeSoapNoteSchema } from "../validators/soapNote.validators";


const visitIdParamSchema = z.object({
  visitId: z.string().uuid('Invalid visit ID'),
});
const soapRouter = Router();

soapRouter.use(protect);
soapRouter.use(auditLog)

soapRouter.get('/',doctorAndAdmin,validateParams(visitIdParamSchema),getSoapNote);
soapRouter.put('/',doctorAndAdmin,validateParams(visitIdParamSchema),validate(editSoapNote),editSoapNote);
soapRouter.post('/finalize',doctorAndAdmin,validateParams(visitIdParamSchema),validate(finalizeSoapNoteSchema))
soapRouter.get('/history',doctorAndAdmin,validateParams(visitIdParamSchema),getSoapNoteHistory);
soapRouter.get('/verify',adminOnly,validateParams(visitIdParamSchema),verifySoapNoteIntegrity);
