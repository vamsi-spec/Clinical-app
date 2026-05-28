import { prisma } from "../config/db"
import logger from "../utils/logger"



const generateMRN = async () => {
  const year = new Date().getFullYear()
  const prefix = `MRN-${year}-`


  const lastPatient = await prisma.patient.findFirst({
    where: {
      mrn: {
        startsWith: prefix,
      },
    },
    orderBy: {
      mrn: 'desc',
    },
    select: {
      mrn: true,
    },
  })

  let nextNumber = 1

  if (lastPatient) {
    const lastNumber = parseInt(lastPatient.mrn.replace(prefix, ''), 10)
    if (!isNaN(lastNumber)) {
      nextNumber = lastNumber + 1
    }
  }

  const mrn = `${prefix}${String(nextNumber).padStart(5, '0')}`

  logger.info(`Generated MRN: ${mrn}`)
  return mrn
}


const isValidMRN = (mrn) => {
  // MRN-YYYY-NNNNN format
  const mrnRegex = /^MRN-\d{4}-\d{5}$/
  return mrnRegex.test(mrn)
}


const generateUniqueMRN = async (maxRetries = 3) => {
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    const mrn = await generateMRN()

    const existing = await prisma.patient.findUnique({
      where: { mrn },
      select: { id: true },
    })

    if (!existing) {
      return mrn 
    }

    logger.warn(`MRN collision detected: ${mrn} — retrying (attempt ${attempt})`)

    await new Promise((resolve) => setTimeout(resolve, 50 * attempt))
  }

  const fallbackMrn = `MRN-${new Date().getFullYear()}-${Date.now().toString().slice(-5)}`
  logger.error(`MRN generation failed after ${maxRetries} retries — using fallback: ${fallbackMrn}`)
  return fallbackMrn
}

