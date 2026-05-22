const { PrismaClient } = require('@prisma/client')
const bcrypt = require('bcryptjs')

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
            specialty: 'General Medicine',
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
            name: 'Rajesh Verma',
            dob: new Date('1975-04-12'),
            gender: 'Male',
            bloodType: 'O+',
            allergies: ['Penicillin'],
            currentMedications: ['Metformin 500mg', 'Atorvastatin 40mg'],
            phone: '+91-9876543210',
        },
        {
            name: 'Sunita Devi',
            dob: new Date('1988-09-23'),
            gender: 'Female',
            bloodType: 'B+',
            allergies: [],
            currentMedications: ['Lisinopril 10mg'],
            phone: '+91-9876543211',
        },
        {
            name: 'Mohammed Iqbal',
            dob: new Date('1962-01-07'),
            gender: 'Male',
            bloodType: 'A-',
            allergies: ['Sulfa drugs', 'Aspirin'],
            currentMedications: ['Amlodipine 5mg', 'Metoprolol 50mg', 'Losartan 50mg'],
            phone: '+91-9876543212',
        },
    ]

    for (const patientData of patients) {
        const patient = await prisma.patient.upsert({
            where: {
                // upsert by name + doctorId combination
                // Since there's no unique constraint on name alone,
                // we use findFirst + create pattern
                id: 'seed-' + patientData.name.replace(/\s+/g, '-').toLowerCase(),
            },
            update: {},
            create: {
                id: 'seed-' + patientData.name.replace(/\s+/g, '-').toLowerCase(),
                doctorId: doctor.id,
                ...patientData,
            },
        })
        console.log('✅ Patient created:', patient.name)
    }

    // ============================================
    // SAMPLE APPOINTMENT
    // ============================================
    const tomorrow = new Date()
    tomorrow.setDate(tomorrow.getDate() + 1)
    tomorrow.setHours(10, 0, 0, 0)

    await prisma.appointment.upsert({
        where: { id: 'seed-appointment-1' },
        update: {},
        create: {
            id: 'seed-appointment-1',
            patientId: 'seed-rajesh-verma',
            doctorId: doctor.id,
            scheduledAt: tomorrow,
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