import axios from 'axios';
import Constants from 'expo-constants';
import { clearAuthToken, getAuthToken, isDevToken } from './authToken';

const manifestExtra =
    (Constants as any)?.manifest2?.extra?.expoClient?.extra ||
    (Constants as any)?.manifest?.extra ||
    Constants.expoConfig?.extra;

const API_BASE = (
    process.env.EXPO_PUBLIC_BACKEND_URL ||
    manifestExtra?.backendUrl ||
    'http://10.0.2.2:8001'
).replace(/\/+$/, '');

const api = axios.create({
    baseURL: API_BASE,
    timeout: 15000,
    headers: { 'Content-Type': 'application/json' },
});

//------This Function builds the current dev auth response---------
function buildDevAuthResponse(token: string) {
    const role = token.replace('dev-token-', '') as 'patient' | 'caregiver' | 'admin';
    const linkedPatients = role === 'caregiver' ? ['dev_patient_uid'] : [];

    return {
        id: `dev-${role}-001`,
        firebase_uid: role === 'caregiver' ? 'dev_caregiver_uid' : role === 'admin' ? 'dev_admin_uid' : 'dev_patient_uid',
        email: `${role}@aura.dev`,
        display_name: role === 'caregiver' ? 'Dr. Sarah Chen' : role === 'admin' ? 'System Admin' : 'Alex Rivera',
        photo_url: '',
        role,
        linked_patients: linkedPatients,
        is_onboarded: true,
        is_banned: false,
    };
}


//------This Function builds the current dev assessment status---------
function buildDevAssessmentStatus(token: string) {
    const role = token.replace('dev-token-', '') as 'patient' | 'caregiver' | 'admin';

    return {
        role,
        threshold: 0.65,
        pending_surveys: [],
        recommended_surveys: [],
        profile: role === 'patient'
            ? {
                patient_id: 'dev_patient_uid',
                condition_level: 'low',
                confidence_score: 1,
                final_score: 2,
                caregiver_count: 0,
                last_updated: new Date().toISOString(),
            }
            : null,
    };
}


//------This Function builds the current dev question bundle---------
function buildDevQuestionBundle(url: string | undefined) {
    const isCaregiver = url?.includes('survey_type=caregiver');
    return {
        survey_type: isCaregiver ? 'caregiver' : 'patient',
        question_set: 'primary',
        threshold: 0.65,
        title: isCaregiver ? 'Caregiver Assessment' : 'Quick Support Check',
        subtitle: 'Dev question bundle',
        questions: [
            {
                id: 'demo_question',
                prompt: 'How much support is needed right now?',
                options: [
                    { value: 'low', label: 'Low', description: 'Mostly independent' },
                    { value: 'medium', label: 'Medium', description: 'Needs some support' },
                    { value: 'high', label: 'High', description: 'Needs close support' },
                ],
            },
        ],
    };
}

const DEV_MOCK_RESPONSES: Record<string, any> = {
    '/assessment/status': { role: 'patient', threshold: 0.65, pending_surveys: [], recommended_surveys: [], profile: null },
    '/assessment/questions': buildDevQuestionBundle('/assessment/questions'),
    '/suggestions/active': [],
    '/medications/': [],
    '/journal/': [],
    '/relatives/': [],
    '/reports/daily-summary': { mood: [], events: [], summary: '' },
    '/sos/active': [],
    '/location/latest': null,
    '/notifications/register': { ok: true },
};

api.interceptors.request.use(async (config) => {
    const token = await getAuthToken();
    if (token) {
        if (isDevToken(token) && config.url !== '/health') {
            const mockKey = Object.keys(DEV_MOCK_RESPONSES).find(key =>
                config.url?.startsWith(key)
            );
            const mockData = config.url?.startsWith('/auth/me')
                ? buildDevAuthResponse(token)
                : config.url?.startsWith('/assessment/status')
                    ? buildDevAssessmentStatus(token)
                    : config.url?.startsWith('/assessment/questions')
                        ? buildDevQuestionBundle(config.url)
                        : config.url?.startsWith('/assessment/patient')
                            ? { status: 'ok', assessment_id: 'dev-patient-assessment', score: 2, confidence: 1, condition_level: 'low', requires_backup: false, next_question_set: null, profile: buildDevAssessmentStatus('dev-token-patient').profile }
                            : config.url?.startsWith('/caregiver/assessment')
                                ? { status: 'ok', assessment_id: 'dev-caregiver-assessment', severity_score: 3, confidence: 1, condition_level: 'low', patient_id: 'dev_patient_uid', patient_name: 'Alex Rivera', requires_backup: false, next_question_set: null, profile: null }
                : (
                    mockKey !== undefined
                        ? DEV_MOCK_RESPONSES[mockKey]
                        : (config.method === 'get' ? [] : { ok: true })
                );

            //------This Function handles the Mock Key---------
            const error: any = new axios.Cancel('dev-mock');
            error.response = { data: mockData, status: 200, headers: {} };
            config.adapter = () => Promise.resolve({
                data: mockData,
                status: 200,
                statusText: 'OK',
                headers: {},
                config,
            });
            return config;
        }

        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});

api.interceptors.response.use(
    (res) => res,
    async (err) => {
        if (err.response?.status === 401) {
            const token = await getAuthToken();
            if (token && isDevToken(token)) {
                return Promise.reject(err);
            }
            await clearAuthToken();
            const { authEvents } = require('./authEvents');
            authEvents.emit('unauthorized');
        }
        return Promise.reject(err);
    }
);

export default api;
