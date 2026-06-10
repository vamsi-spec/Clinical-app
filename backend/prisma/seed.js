import { PrismaClient } from '@prisma/client'
import bcrypt from 'bcryptjs'

const prisma = new PrismaClient()

async function main() {
    console.log('🌱 Seeding database...')

    const saltRounds = 12
    const defaultPassword = 'Password123!'

    // ============================================
    // ADMIN
    // ============================================
    const adminHash = await bcrypt.hash(defaultPassword, saltRounds)
    const admin = await prisma.user.upsert({
        where: { email: 'admin@clinic.com' },
        update: {},
        create: {
            email: 'admin@clinic.com',
            passwordHash: adminHash,
            firstName: 'System',
            lastName: 'Admin',
            role: 'ADMIN',
        },
    })
    console.log('✅ Admin created:', admin.email)

    // ============================================
    // DOCTOR
    // ============================================
    const doctorHash = await bcrypt.hash(defaultPassword, saltRounds)
    const doctor = await prisma.user.upsert({
        where: { email: 'doctor@clinic.com' },
        update: {},
        create: {
            email: 'doctor@clinic.com',
            passwordHash: doctorHash,
            firstName: 'Priya',
            lastName: 'Sharma',
            role: 'DOCTOR',
            speciality: 'General Medicine',
        },
    })
    console.log('✅ Doctor created:', doctor.email)

    // ============================================
    // NURSE — assigned to doctor above
    // ============================================
    const nurseHash = await bcrypt.hash(defaultPassword, saltRounds)
    const nurse = await prisma.user.upsert({
        where: { email: 'nurse@clinic.com' },
        update: {},
        create: {
            email: 'nurse@clinic.com',
            passwordHash: nurseHash,
            firstName: 'Ravi',
            lastName: 'Kumar',
            role: 'NURSE',
            assignedDoctorId: doctor.id,
        },
    })
    console.log('✅ Nurse created:', nurse.email)

    // ============================================
    // RECEPTIONIST
    // ============================================
    const receptionistHash = await bcrypt.hash(defaultPassword, saltRounds)
    const receptionist = await prisma.user.upsert({
        where: { email: 'receptionist@clinic.com' },
        update: {},
        create: {
            email: 'receptionist@clinic.com',
            passwordHash: receptionistHash,
            firstName: 'Anita',
            lastName: 'Patel',
            role: 'RECEPTIONIST',
        },
    })
    console.log('✅ Receptionist created:', receptionist.email)

    // ============================================
    // SAMPLE PATIENTS
    // ============================================
    const patients = [
        {
            firstName: 'Rajesh',
            lastName: 'Verma',
            mrn: 'MRN-2026-00001',
            dob: new Date('1975-04-12'),
            gender: 'Male',
            bloodType: 'O+',
            allergies: ['Penicillin'],
            currentMedications: ['Metformin 500mg', 'Atorvastatin 40mg'],
            phone: '+91-9876543210',
        },
        {
            firstName: 'Sunita',
            lastName: 'Devi',
            mrn: 'MRN-2026-00002',
            dob: new Date('1988-09-23'),
            gender: 'Female',
            bloodType: 'B+',
            allergies: [],
            currentMedications: ['Lisinopril 10mg'],
            phone: '+91-9876543211',
        },
        {
            firstName: 'Mohammed',
            lastName: 'Iqbal',
            mrn: 'MRN-2026-00003',
            dob: new Date('1962-01-07'),
            gender: 'Male',
            bloodType: 'A-',
            allergies: ['Sulfa drugs', 'Aspirin'],
            currentMedications: ['Amlodipine 5mg', 'Metoprolol 50mg', 'Losartan 50mg'],
            phone: '+91-9876543212',
        },
    ]

    for (const patientData of patients) {
        const patientId = `seed-${patientData.firstName.toLowerCase()}-${patientData.lastName.toLowerCase()}`
        const patient = await prisma.patient.upsert({
            where: {
                id: patientId,
            },
            update: {},
            create: {
                id: patientId,
                doctorId: doctor.id,
                ...patientData,
            },
        })
        console.log('✅ Patient created:', patient.firstName + ' ' + patient.lastName)
    }

    // ============================================
    // SAMPLE APPOINTMENT
    // ============================================
    const tomorrow = new Date()
    tomorrow.setDate(tomorrow.getDate() + 1)
    tomorrow.setHours(10, 0, 0, 0)

    const endsAt = new Date(tomorrow.getTime() + 30 * 60 * 1000)

    await prisma.appointment.upsert({
        where: { id: 'seed-appointment-1' },
        update: {},
        create: {
            id: 'seed-appointment-1',
            patientId: 'seed-rajesh-verma',
            doctorId: doctor.id,
            scheduledAt: tomorrow,
            endsAt,
            duration: 30,
            status: 'SCHEDULED',
            notes: 'Regular diabetes follow-up',
        },
    })
    console.log('✅ Sample appointment created')

    console.log('\n🎉 Seeding complete!')
    console.log('\n📋 Login credentials (all use password: Password123!)')
    console.log('   Admin:         admin@clinic.com')
    console.log('   Doctor:        doctor@clinic.com')
    console.log('   Nurse:         nurse@clinic.com')
    console.log('   Receptionist:  receptionist@clinic.com')
}

main()
    .catch((e) => {
        console.error('❌ Seed failed:', e)
        process.exit(1)
    })
    .finally(async () => {
        await prisma.$disconnect()
    })