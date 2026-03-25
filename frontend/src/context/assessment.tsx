import React, { createContext, ReactNode, useContext, useEffect, useState } from 'react';

import { useAuth } from './auth';
import {
    AssessmentStatus,
    AssessmentSurveyEntry,
    assessmentService,
} from '../services/assessment';


interface AssessmentState {
    status: AssessmentStatus | null;
    loading: boolean;
    refreshAssessmentStatus: () => Promise<AssessmentStatus | null>;
    nextRequiredSurvey: AssessmentSurveyEntry | null;
    recommendedSurveys: AssessmentSurveyEntry[];
}


const AssessmentContext = createContext<AssessmentState>({
    status: null,
    loading: true,
    refreshAssessmentStatus: async () => null,
    nextRequiredSurvey: null,
    recommendedSurveys: [],
});


//------This Function handles the Assessment Provider---------
export function AssessmentProvider({ children }: { children: ReactNode }) {
    const { user, loading: authLoading, initialLoadDone, connectionError } = useAuth();
    const [status, setStatus] = useState<AssessmentStatus | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        if (authLoading || !initialLoadDone) {
            setLoading(true);
            return;
        }

        if (!user || connectionError || user.role === 'admin') {
            setStatus(null);
            setLoading(false);
            return;
        }

        refreshAssessmentStatus();
    }, [user?.firebase_uid, user?.role, authLoading, initialLoadDone, connectionError]);

    //------This Function handles the Refresh Assessment Status---------
    async function refreshAssessmentStatus(): Promise<AssessmentStatus | null> {
        if (!user || user.role === 'admin') {
            setStatus(null);
            setLoading(false);
            return null;
        }

        try {
            setLoading(true);
            const nextStatus = await assessmentService.getStatus();
            setStatus(nextStatus);
            return nextStatus;
        } catch (error) {
            console.error('[Assessment] Failed to load status:', error);
            setStatus(null);
            return null;
        } finally {
            setLoading(false);
        }
    }

    const nextRequiredSurvey = status?.pending_surveys.find((survey) => survey.required) || null;
    const recommendedSurveys = status?.recommended_surveys || [];

    return (
        <AssessmentContext.Provider
            value={{
                status,
                loading,
                refreshAssessmentStatus,
                nextRequiredSurvey,
                recommendedSurveys,
            }}
        >
            {children}
        </AssessmentContext.Provider>
    );
}


//------This Function handles the Use Assessment---------
export const useAssessment = () => useContext(AssessmentContext);
