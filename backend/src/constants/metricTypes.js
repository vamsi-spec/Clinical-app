// backend/src/constants/metricTypes.js
const METRIC_TYPES = {
    // General
    BLOOD_PRESSURE: { label: 'Blood Pressure', unit: 'mmHg' },
    HEART_RATE: { label: 'Heart Rate', unit: 'bpm' },
    WEIGHT: { label: 'Weight', unit: 'kg' },
    HEIGHT: { label: 'Height', unit: 'cm' },
    BMI: { label: 'BMI', unit: 'kg/m²' },
    TEMPERATURE: { label: 'Temperature', unit: '°C' },
    OXYGEN_SATURATION: { label: 'SpO2', unit: '%' },
    RESPIRATORY_RATE: { label: 'Respiratory Rate', unit: 'breaths/min' },

    // Endocrinology / Diabetes
    GLUCOSE: { label: 'Blood Glucose', unit: 'mg/dL' },
    HBA1C: { label: 'HbA1c', unit: '%' },
    INSULIN_DOSE: { label: 'Insulin Dose', unit: 'units' },

    // Cardiology
    EJECTION_FRACTION: { label: 'Ejection Fraction', unit: '%' },
    BNP: { label: 'BNP', unit: 'pg/mL' },
    CHOLESTEROL_TOTAL: { label: 'Total Cholesterol', unit: 'mg/dL' },
    CHOLESTEROL_LDL: { label: 'LDL', unit: 'mg/dL' },
    CHOLESTEROL_HDL: { label: 'HDL', unit: 'mg/dL' },
    TRIGLYCERIDES: { label: 'Triglycerides', unit: 'mg/dL' },

    // Nephrology
    CREATININE: { label: 'Creatinine', unit: 'mg/dL' },
    EGFR: { label: 'eGFR', unit: 'mL/min/1.73m²' },
    UREA: { label: 'Blood Urea', unit: 'mg/dL' },

    // Pulmonology
    FEV1: { label: 'FEV1', unit: 'L' },
    PEAK_FLOW: { label: 'Peak Flow', unit: 'L/min' },

    // Psychiatry
    PHQ9_SCORE: { label: 'PHQ-9 Score', unit: 'score' },
    GAD7_SCORE: { label: 'GAD-7 Score', unit: 'score' },

    // Haematology
    HEMOGLOBIN: { label: 'Hemoglobin', unit: 'g/dL' },
    WBC: { label: 'WBC Count', unit: 'cells/μL' },
    PLATELET: { label: 'Platelet Count', unit: 'cells/μL' },

    // Liver
    ALT: { label: 'ALT', unit: 'U/L' },
    AST: { label: 'AST', unit: 'U/L' },
    BILIRUBIN: { label: 'Bilirubin', unit: 'mg/dL' },

    // Thyroid
    TSH: { label: 'TSH', unit: 'mIU/L' },
    T3: { label: 'T3', unit: 'ng/dL' },
    T4: { label: 'T4', unit: 'μg/dL' },
}

module.exports = METRIC_TYPES