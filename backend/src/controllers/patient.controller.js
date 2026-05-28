



import { prisma } from "../config/db.js"
import { generateUniqueMRN } from "../services/mrn.services.js"
import { errorResponse, paginatedResponse, successResponse } from "../utils/apiResponse.js"
import logger from "../utils/logger.js"






const getSelectByRole = (role) => {
  // Fields every role can see — demographics only
  const demographicFields = {
    id: true,
    mrn: true,
    firstName: true,
    lastName: true,
    dob: true,
    gender: true,
    phone: true,
    email: true,
    address: true,
    city: true,
    state: true,
    pincode: true,
    nationality: true,
    preferredLanguage: true,
    emergencyContactName: true,
    emergencyContactPhone: true,
    emergencyContactRel: true,
    primaryInsurance: true,
    insuranceNumber: true,
    secondaryInsurance: true,
    consentGiven: true,
    consentDate: true,
    isActive: true,
    registeredBy: true,
    createdAt: true,
    updatedAt: true,
    doctor: {
      select: {
        id: true,
        firstName: true,
        lastName: true,
        specialty: true,
      },
    },
}

    if (role === 'RECEPTIONIST') {
        return demographicFields
    }

    return {
        ...demographicFields,
        bloodType: true,
        allergies: true,
        currentMedications: true,
        pastSurgeries: true,
        chronicConditions: true,
        familyHistory: true,
        referredBy: true,
        deleteReason: true,
        deletedAt: true,
        deletedBy: true,
    }
}

//building scope filter bu role
//Doctors sees only their patients
//Nurses see assigned doctors's patient
//Receptionist see all active patients
//Admin sees everything

const buildScopeFilter = (user) => {
    switch (user.role){
        case 'ADMIN':
            return {}
        
        case 'DOCTOR':
            return {doctorId: user.id}
        
        case 'NURSE':
            if(!user.assignedDoctorId) return {id: 'no-access'}
            return {doctorId: user.assignedDoctorId}

        case 'RECEPTIONIST':
            return {}
        
        default: 
        return {id: 'no-access'}
    }
}


//List patients
//GET /api/patients
//All roles - scoped + field projected

export const listPatients = async (req,res) => {
    try {
        const {
            search,mrn,gender,bloodType,isActive,chronicCondition,doctorId,page,limit,sortBy,sortOrder
        } = req.query

        const skip = (page - 1)*limit
        const scopeFilter = buildScopeFilter(req.user)

        const where = {
            ...scopeFilter,
            deletedAt: null,
        }

        //Active filter-default show active only

        where.isActive = isActive !== undefined ? isActive : true

        //Admin can filter by specific doctor
        if(doctorId && req.user.role === 'ADMIN'){
            where.doctorId = doctorId
        }

        if(gender) where.gender = gender

        if(bloodType && req.user.role !== 'RECEPTIONIST') {
            where.bloodType = bloodType
        }

        if(chronicCondition && req.user.role !== 'RECEPTIONIST') {
            where.chronicConditions = {has: chronicCondition}
        }

        if (mrn) {
            where.mrn = { equals: mrn.toUpperCase(), mode: 'insensitive' }
        }

    //search by name

    if (search) {
      where.OR = [
        { firstName: { contains: search, mode: 'insensitive' } },
        { lastName: { contains: search, mode: 'insensitive' } },
        { mrn: { contains: search, mode: 'insensitive' } },
        { phone: { contains: search, mode: 'insensitive' } },
        { email: { contains: search, mode: 'insensitive' } },
      ]
    }

    const [total,patients] = await Promise.all([
        prisma.patient.count({where}),
        prisma.patient.findMany({
            where,
            select: getSelectByRole(req.user.role),
            orderBy: {
                [sortBy]: sortOrder
            },
            take: limit,
            skip,
        })
    ])

    return paginatedResponse(
      res,
      patients,
      { page, limit, total },
      'Patients retrieved successfully.'
    )

    } catch (error) {
        logger.error('List patients error:', error)
        return errorResponse(res, 'Failed to retrieve patients.', 500, error)
    }
}





//Get single patient
//Get /api/patients/:id
//All roles - scoped + projected

export const getPatient = async (req,res) => {
    try {
        const {id} = req.params
        const scopeFilter = buildScopeFilter(req.user)

        const patient = await prisma.patient.findFirst({
            where: {
                id,
                deletedAt: null,
                ...scopeFilter,
            },
            select: {
                ...getSelectByRole(req.user.role),
                _count: {
                    select: {visits: true, appointments: true}
                }
            }
        })
        if(!patient) {
            return errorResponse(res,'Patient not found or you do not have access.',404)
        }

        let context = {}

        if(req.user.role === 'RECEPTIONIST') {
            const upcomingAppointments = await prisma.appointment.findMany({
                where: {
                    patientId: id,
                    sheduledAt: {gte: new Date()},
                    status: 'SCHEDULED'
                },
                orderBy: {sheduledAt: 'asc'},
                take: 5,
                select: {
                    id: true,
                    sheduledAt: true,
                    endsAt: true,
                    duration: true,
                    type: true,
                    status: true,
                    chiefComplaint: true,
                    doctor: {
                        select: {
                            firstName: true,
                            lastName: true,
                            specialty: true,
                        }
                    }
                }
            })

            context = {upcomingAppointments}
        }
        else{
            const [
                recentVisits,
                upcomingAppointments,
                criticalInteractions,
                pendingTransfers,
                latestVitals,
            ] = await Promise.all([
                prisma.visit.findMany({
                    where: {patientId: id},
                    orderBy: {visitDate: 'desc'},
                    take: 5,
                    select: {
                        id: true,
                        visitDate: true,
                        pipelineStatus: true,
                        duration: true,
                        doctor: {
                        select: { firstName: true, lastName: true, specialty: true },
                        },
            soapNote: {
              select: {
                assessment: true,
                isFinalized: true,
                finalizedAt: true,
              },
            },
          },
        }),

        prisma.appointment.findMany({
            where: {
                patientId: id,
                scheduledAt: {gte: new Date()},
                status: 'SCHEDULED'
            },
            orderBy: {sheduledAt: 'asc'},
            take: 3,
            select: {
                id: true,
                sheduledAt: true,
                duration: true,
                type: true,
                chiefComplaint: true,
                doctor: {
                    select: {
                        firstName: true,
                        lastName: true,
                        specialty: true,
                    }
                }
            }
        }),

        //Critical drug interactions 

            prisma.drugInteraction.findMany({
                where: {
                    visit: { patientId: id},
                    severity: {in: ['HIGH','CRITICAL']},
                },
                orderBy: {createdAt: 'desc'},
                take: 5,
                select: {
                    drug1: true,
                    drug2: true,
                    severity: true,
                    description: true
                }
            }),

            prisma.patientTrend.findMany({
                where: {patientId: id},
                orderBy: {recordedAt: 'desc'},
                distinct:['metricType'],
                select: {
                    metricType: true,
                    value: true,
                    unit: true,
                    recordedAt: true,
                }
            })
            ])
            context = {
        recentVisits,
        upcomingAppointments,
        criticalInteractions,
        pendingTransfers,
        latestVitals,
      }
        }

        return successResponse(
      res,
      { ...patient, ...context },
      'Patient retrieved successfully.'
    )
  } catch (error) {
    logger.error('Get patient error:', error)
    return errorResponse(res, 'Failed to retrieve patient.', 500, error)
  }
}



//Register patient
//POST /api/patients
//creates demographic shell
export const registerPatient = async (req,res) => {
    try {
    const {firstName,lastName,dob,gender,doctorId,phone,email,address,city,state,pincode,nationality,preferredLanguage,emergencyContactName,emergencyContactPhone,emergencyContactRel,primaryInsurance,insuranceNumber,secondaryInsurance,consentGiven} = req.body

    const doctor = await prisma.user.findUnique({
        where: {id: doctorId},
        select: {
            id: true,
            role: true,
            isActive: true,
            firstName: true,
            lastName: true
        }
    })

    if(!doctor) {
        return errorResponse(res, 'Doctor not found.', 404)
    }

    if(doctor.role !== 'DOCTOR') {
        return errorResponse(res, 'The provided ID does not belong to a doctor.', 400)
    }

    if(!doctor.isActive) {
        return errorResponse(res, 'Inactive doctor.', 400)
    }

    const duplicate = await prisma.patient.findFirst({
      where: {
        doctorId,
        firstName: { equals: firstName, mode: 'insensitive' },
        lastName: { equals: lastName, mode: 'insensitive' },
        dob: new Date(dob),
        deletedAt: null,
      },
      select: { id: true, mrn: true },
    })

    if(duplicate){
        return errorResponse(res,'Duplicate patient record found.',409)
    }

    if (email) {
        const emailDuplicate = await prisma.patient.findFirst({
            where: {
                email: {equals: email,mode: 'insensitive'},
                deletedAt: null,
            },
            select: {id: true,mrn: true,firstName: true,lastName: true}
        })

        if(emailDuplicate) {
            return errorResponse(res, `Email already in use by existing patient.`, 409)
        }

        const mrn = await generateUniqueMRN()

        const patient = await prisma.patient.create({
      data: {
        mrn,
        doctorId,
        firstName,
        lastName,
        dob: new Date(dob),
        gender,
        phone,
        email,
        address,
        city,
        state,
        pincode,
        nationality,
        preferredLanguage: preferredLanguage || 'English',
        emergencyContactName,
        emergencyContactPhone,
        emergencyContactRel,
        primaryInsurance,
        insuranceNumber,
        secondaryInsurance,
        consentGiven,
        consentDate: consentGiven ? new Date() : null,
        registeredBy: req.user.id,
        // Clinical fields start empty — doctor fills later
        allergies: [],
        currentMedications: [],
        pastSurgeries: [],
        chronicConditions: [],
      },
      select: getSelectByRole(req.user.role),
    })

    logger.info(
      `Patient registered: ${mrn} by receptionist ${req.user.email} under Dr. ${doctor.firstName} ${doctor.lastName}`
    )

    return successResponse(
      res,
      patient,
      `Patient registered successfully. MRN: ${mrn}. Dr. ${doctor.firstName} ${doctor.lastName} has been assigned.`,
      201
    )
    }

    } catch (error) {
        logger.error("Register patient error:", error);
    return errorResponse(res, "Failed to register patient.", 500, error);
    }
}