import prisma from "../config/db.js"
import logger from "../utils/logger.js"

//Build patient Context
//Gather everything the LLM need to know about the patients existing clinical picture.
//It will be sent as part as visit.audio.uploaded event payload - ML never queries Postgresql directly, i have done by keepting the two services loosely coupled and independently deployable

export const buildPatientContext = async (patientId) => {
    const patient = await prisma.patient.findUnique({
        where: {id: patientId},
        select: {
            dateOfBirth: true,
            gender: true,
            bloodType: true,
            chronicConditions: true,
            currentMedications: true,
            allergies: true,
        }
    })

    if(!patient) {
        logger.warn(`buildPatientContext: patient ${patientId} not found`)
        return null;
    }

    const age = patient.dateOfBirth ? Math.floor((Date.now() - new Date(patient.dateOfBirth).getTime()) /
          (1000 * 60 * 60 * 24 * 365.25)) : null;

    //Last visit summary
    //Pulls the most recent Finalized soap note's 
    //assesment section - gives the llm a sense of "what's the plan last time" without placing a entire visit history into the prompt

    const lastVisit = await prisma.visit.findFirst({
        where: {
            patientId,
            isArchived: false,
            soapNote: {isFinalized: true},
        },
        orderBy: {visitDate: 'desc'},
        include: {
            soapNote: {select: {assessment: true,plan: true}},
        }
    })

    let lastVisitSummary = null;
    if(lastVisit?.soapNote) {
        lastVisitSummary = `${lastVisit.soapNote.assessment} Plan was: ${lastVisit.soapNote.plan}`.slice(0,500)
    }
 
    //Longitudnal trends in future 

    const longitudinalTrends = [];

    return {
        age,
        gender: patient.gender,
        bloodType: patient.bloodType,
        chronicConditions: patient.chronicConditions || [],
        currentMedications: patient.currentMedications || [],
        allergies: patient.allergies || [],
        lastVisitSummary,
        longitudinalTrends,
    }
}

