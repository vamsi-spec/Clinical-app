/*
  Warnings:

  - The values [GENERATING_BILLING] on the enum `PipelineStatus` will be removed. If these variants are still used in the database, this will fail.
  - You are about to drop the column `emergencyContact` on the `Patient` table. All the data in the column will be lost.
  - You are about to drop the column `name` on the `Patient` table. All the data in the column will be lost.
  - You are about to drop the column `audioFileUrl` on the `Visit` table. All the data in the column will be lost.
  - You are about to drop the column `audoPublicId` on the `Visit` table. All the data in the column will be lost.
  - You are about to drop the column `duration` on the `Visit` table. All the data in the column will be lost.
  - A unique constraint covering the columns `[mrn]` on the table `Patient` will be added. If there are existing duplicate values, this will fail.
  - A unique constraint covering the columns `[appointmentId]` on the table `Visit` will be added. If there are existing duplicate values, this will fail.
  - Added the required column `endsAt` to the `Appointment` table without a default value. This is not possible if the table is not empty.
  - Added the required column `firstName` to the `Patient` table without a default value. This is not possible if the table is not empty.
  - Added the required column `lastName` to the `Patient` table without a default value. This is not possible if the table is not empty.
  - Added the required column `mrn` to the `Patient` table without a default value. This is not possible if the table is not empty.
  - Added the required column `specialty` to the `Visit` table without a default value. This is not possible if the table is not empty.

*/
-- CreateEnum
CREATE TYPE "AppointmentType" AS ENUM ('SCHEDULED', 'WALK_IN', 'FOLLOW_UP', 'REFERRAL', 'EMERGENCY');

-- CreateEnum
CREATE TYPE "TransferRequestStatus" AS ENUM ('PENDING', 'APPROVED', 'REJECTED', 'COMPLETED', 'CANCELLED');

-- AlterEnum
BEGIN;
CREATE TYPE "PipelineStatus_new" AS ENUM ('PENDING', 'AUDIO_UPLOADED', 'TRANSCRIBING', 'DIARIZING', 'CORRECTING', 'EXTRACTING_ENTITIES', 'GENERATING_SOAP', 'CHECKING_INCONSISTENCIES', 'MAPPING_EXPLAINABILITY', 'CHECKING_BILLING', 'CHECKING_DRUGS', 'COMPLETED', 'FAILED');
ALTER TABLE "Visit" ALTER COLUMN "pipelineStatus" DROP DEFAULT;
ALTER TABLE "Visit" ALTER COLUMN "pipelineStatus" TYPE "PipelineStatus_new" USING ("pipelineStatus"::text::"PipelineStatus_new");
ALTER TYPE "PipelineStatus" RENAME TO "PipelineStatus_old";
ALTER TYPE "PipelineStatus_new" RENAME TO "PipelineStatus";
DROP TYPE "PipelineStatus_old";
ALTER TABLE "Visit" ALTER COLUMN "pipelineStatus" SET DEFAULT 'PENDING';
COMMIT;

-- DropIndex
DROP INDEX "Patient_name_idx";

-- DropIndex
DROP INDEX "Visit_doctorId_idx";

-- DropIndex
DROP INDEX "Visit_patientId_idx";

-- DropIndex
DROP INDEX "Visit_visitDate_idx";

-- AlterTable
ALTER TABLE "Appointment" ADD COLUMN     "bookedBy" TEXT,
ADD COLUMN     "bufferMinutes" INTEGER NOT NULL DEFAULT 10,
ADD COLUMN     "cancelReason" TEXT,
ADD COLUMN     "cancelledAt" TIMESTAMP(3),
ADD COLUMN     "cancelledBy" TEXT,
ADD COLUMN     "chiefComplaint" TEXT,
ADD COLUMN     "completedAt" TIMESTAMP(3),
ADD COLUMN     "completedBy" TEXT,
ADD COLUMN     "endsAt" TIMESTAMP(3) NOT NULL,
ADD COLUMN     "followUpOf" TEXT,
ADD COLUMN     "isWalkIn" BOOLEAN NOT NULL DEFAULT false,
ADD COLUMN     "noShowAt" TIMESTAMP(3),
ADD COLUMN     "reminderSent" BOOLEAN NOT NULL DEFAULT false,
ADD COLUMN     "reminderSentAt" TIMESTAMP(3),
ADD COLUMN     "type" "AppointmentType" NOT NULL DEFAULT 'SCHEDULED';

-- AlterTable
ALTER TABLE "Patient" DROP COLUMN "emergencyContact",
DROP COLUMN "name",
ADD COLUMN     "chronicConditions" TEXT[],
ADD COLUMN     "city" TEXT,
ADD COLUMN     "consentDate" TIMESTAMP(3),
ADD COLUMN     "consentGiven" BOOLEAN NOT NULL DEFAULT false,
ADD COLUMN     "deleteReason" TEXT,
ADD COLUMN     "deletedAt" TIMESTAMP(3),
ADD COLUMN     "deletedBy" TEXT,
ADD COLUMN     "emergencyContactName" TEXT,
ADD COLUMN     "emergencyContactPhone" TEXT,
ADD COLUMN     "emergencyContactRel" TEXT,
ADD COLUMN     "familyHistory" TEXT,
ADD COLUMN     "firstName" TEXT NOT NULL,
ADD COLUMN     "insuranceNumber" TEXT,
ADD COLUMN     "lastName" TEXT NOT NULL,
ADD COLUMN     "mrn" TEXT NOT NULL,
ADD COLUMN     "nationality" TEXT,
ADD COLUMN     "pastSurgeries" TEXT[],
ADD COLUMN     "pincode" TEXT,
ADD COLUMN     "preferredLanguage" TEXT DEFAULT 'English',
ADD COLUMN     "primaryInsurance" TEXT,
ADD COLUMN     "referredBy" TEXT,
ADD COLUMN     "registeredBy" TEXT,
ADD COLUMN     "secondaryInsurance" TEXT,
ADD COLUMN     "state" TEXT;

-- AlterTable
ALTER TABLE "Visit" DROP COLUMN "audioFileUrl",
DROP COLUMN "audoPublicId",
DROP COLUMN "duration",
ADD COLUMN     "appointmentId" TEXT,
ADD COLUMN     "audioDuration" DOUBLE PRECISION,
ADD COLUMN     "audioPublicId" TEXT,
ADD COLUMN     "audioUrl" TEXT,
ADD COLUMN     "isArchived" BOOLEAN NOT NULL DEFAULT false,
ADD COLUMN     "lastKafkaEventId" TEXT,
ADD COLUMN     "pipelineCompletedAt" TIMESTAMP(3),
ADD COLUMN     "pipelineStartedAt" TIMESTAMP(3),
ADD COLUMN     "specialty" TEXT NOT NULL;

-- CreateTable
CREATE TABLE "TransferRequest" (
    "id" TEXT NOT NULL,
    "patientId" TEXT NOT NULL,
    "fromDoctorId" TEXT NOT NULL,
    "toDoctorId" TEXT NOT NULL,
    "requestedBy" TEXT NOT NULL,
    "reason" TEXT NOT NULL,
    "status" "TransferRequestStatus" NOT NULL DEFAULT 'PENDING',
    "adminNote" TEXT,
    "reviewedBy" TEXT,
    "reviewedAt" TIMESTAMP(3),
    "executedBy" TEXT,
    "executedAt" TIMESTAMP(3),
    "cancelledBy" TEXT,
    "cancelledAt" TIMESTAMP(3),
    "cancelNote" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "TransferRequest_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "TransferRequest_patientId_idx" ON "TransferRequest"("patientId");

-- CreateIndex
CREATE INDEX "TransferRequest_status_idx" ON "TransferRequest"("status");

-- CreateIndex
CREATE INDEX "TransferRequest_fromDoctorId_idx" ON "TransferRequest"("fromDoctorId");

-- CreateIndex
CREATE INDEX "TransferRequest_toDoctorId_idx" ON "TransferRequest"("toDoctorId");

-- CreateIndex
CREATE INDEX "TransferRequest_requestedBy_idx" ON "TransferRequest"("requestedBy");

-- CreateIndex
CREATE INDEX "Appointment_status_idx" ON "Appointment"("status");

-- CreateIndex
CREATE INDEX "Appointment_doctorId_status_scheduledAt_idx" ON "Appointment"("doctorId", "status", "scheduledAt");

-- CreateIndex
CREATE UNIQUE INDEX "Patient_mrn_key" ON "Patient"("mrn");

-- CreateIndex
CREATE INDEX "Patient_mrn_idx" ON "Patient"("mrn");

-- CreateIndex
CREATE INDEX "Patient_firstName_lastName_idx" ON "Patient"("firstName", "lastName");

-- CreateIndex
CREATE INDEX "Patient_isActive_idx" ON "Patient"("isActive");

-- CreateIndex
CREATE INDEX "Patient_doctorId_isActive_idx" ON "Patient"("doctorId", "isActive");

-- CreateIndex
CREATE UNIQUE INDEX "Visit_appointmentId_key" ON "Visit"("appointmentId");

-- CreateIndex
CREATE INDEX "Visit_pipelineStatus_idx" ON "Visit"("pipelineStatus");

-- CreateIndex
CREATE INDEX "Visit_doctorId_isArchived_idx" ON "Visit"("doctorId", "isArchived");

-- AddForeignKey
ALTER TABLE "TransferRequest" ADD CONSTRAINT "TransferRequest_patientId_fkey" FOREIGN KEY ("patientId") REFERENCES "Patient"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "TransferRequest" ADD CONSTRAINT "TransferRequest_fromDoctorId_fkey" FOREIGN KEY ("fromDoctorId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "TransferRequest" ADD CONSTRAINT "TransferRequest_toDoctorId_fkey" FOREIGN KEY ("toDoctorId") REFERENCES "User"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Visit" ADD CONSTRAINT "Visit_appointmentId_fkey" FOREIGN KEY ("appointmentId") REFERENCES "Appointment"("id") ON DELETE SET NULL ON UPDATE CASCADE;
