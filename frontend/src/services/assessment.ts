import api from './api';

export type SurveyType = 'patient' | 'caregiver';
export type QuestionSet = 'primary' | 'backup';

export interface AssessmentOption {
    value: string;
    label: string;
    description: string;
}

export interface AssessmentQuestion {
    id: string;
    prompt: string;
    options: AssessmentOption[];
}

export interface AssessmentQuestionBundle {
    survey_type: SurveyType;
    question_set: QuestionSet;
    threshold: number;
    title: string;
    subtitle: string;
    questions: AssessmentQuestion[];
}

export interface AssessmentAnswerPayload {
    question_id: string;
    answer?: string | null;
    skipped: boolean;
}

export interface AssessmentSurveyEntry {
    survey_type: SurveyType;
    patient_id: string;
    patient_name: string;
    question_set: QuestionSet;
    reason: string;
    required: boolean;
    confidence: number;
}

export interface AssessmentProfileSummary {
    patient_id: string;
    condition_level: 'low' | 'mild' | 'moderate' | 'high';
    confidence_score: number;
    final_score: number;
    caregiver_count: number;
    last_updated: string;
}

export interface AssessmentStatus {
    role: 'patient' | 'caregiver' | 'admin';
    threshold: number;
    pending_surveys: AssessmentSurveyEntry[];
    recommended_surveys: AssessmentSurveyEntry[];
    profile: AssessmentProfileSummary | null;
}

export interface AssessmentSubmissionResponse {
    status: string;
    assessment_id: string;
    score?: number;
    severity_score?: number;
    confidence: number;
    condition_level: 'low' | 'mild' | 'moderate' | 'high';
    requires_backup: boolean;
    next_question_set: QuestionSet | null;
    profile: AssessmentProfileSummary | null;
    patient_id?: string;
    patient_name?: string;
}


//------This Function handles the Assessment Service---------
class AssessmentService {
    //------This Function handles the Get Status---------
    async getStatus(): Promise<AssessmentStatus> {
        const response = await api.get('/assessment/status');
        return response.data as AssessmentStatus;
    }

    //------This Function handles the Get Questions---------
    async getQuestions(surveyType: SurveyType, questionSet: QuestionSet): Promise<AssessmentQuestionBundle> {
        const response = await api.get('/assessment/questions', {
            params: {
                survey_type: surveyType,
                question_set: questionSet,
            },
        });
        return response.data as AssessmentQuestionBundle;
    }

    //------This Function handles the Submit Patient Assessment---------
    async submitPatientAssessment(
        questionSet: QuestionSet,
        answers: AssessmentAnswerPayload[],
    ): Promise<AssessmentSubmissionResponse> {
        const response = await api.post('/assessment/patient', {
            question_set: questionSet,
            answers,
        });
        return response.data as AssessmentSubmissionResponse;
    }

    //------This Function handles the Submit Caregiver Assessment---------
    async submitCaregiverAssessment(
        patientId: string,
        questionSet: QuestionSet,
        answers: AssessmentAnswerPayload[],
    ): Promise<AssessmentSubmissionResponse> {
        const response = await api.post('/caregiver/assessment', {
            patient_id: patientId,
            question_set: questionSet,
            answers,
        });
        return response.data as AssessmentSubmissionResponse;
    }
}


export const assessmentService = new AssessmentService();
