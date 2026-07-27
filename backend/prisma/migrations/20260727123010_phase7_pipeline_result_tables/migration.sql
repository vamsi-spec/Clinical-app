/*
  Warnings:

  - Added the required column `updatedAt` to the `NERResult` table without a default value. This is not possible if the table is not empty.

*/
-- AlterTable
ALTER TABLE "NERResult" ADD COLUMN     "updatedAt" TIMESTAMP(3) NOT NULL;

-- AlterTable
ALTER TABLE "SOAPNote" ADD COLUMN     "differentials" JSONB NOT NULL DEFAULT '[]',
ADD COLUMN     "inconsistencies" JSONB NOT NULL DEFAULT '{}',
ADD COLUMN     "missedFollowups" JSONB NOT NULL DEFAULT '[]',
ADD COLUMN     "redFlags" JSONB NOT NULL DEFAULT '[]';

-- CreateIndex
CREATE INDEX "DrugInteraction_severity_idx" ON "DrugInteraction"("severity");
