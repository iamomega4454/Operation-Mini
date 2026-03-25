import React, { useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Alert, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';

import Screen from '../../src/components/Screen';
import AssessmentQuestionnaire from '../../src/components/AssessmentQuestionnaire';
import { useAssessment } from '../../src/context/assessment';
import { useAuth } from '../../src/context/auth';
import {
    AssessmentAnswerPayload,
    AssessmentQuestionBundle,
    QuestionSet,
    assessmentService,
} from '../../src/services/assessment';
import { colors, fonts, radius, spacing } from '../../src/theme';


//------This Function handles the Patient Assessment Screen---------
export default function PatientAssessmentScreen() {
    const router = useRouter();
    const { user } = useAuth();
    const { status, loading: statusLoading, refreshAssessmentStatus } = useAssessment();
    const [questionBundle, setQuestionBundle] = useState<AssessmentQuestionBundle | null>(null);
    const [responses, setResponses] = useState<Record<string, AssessmentAnswerPayload>>({});
    const [currentIndex, setCurrentIndex] = useState(0);
    const [loadingQuestions, setLoadingQuestions] = useState(false);
    const [submitting, setSubmitting] = useState(false);

    const activeSurvey = useMemo(() => {
        const pendingSurvey = status?.pending_surveys.find((survey) => survey.survey_type === 'patient');
        if (pendingSurvey) {
            return pendingSurvey;
        }
        return status?.recommended_surveys.find((survey) => survey.survey_type === 'patient') || null;
    }, [status]);

    useEffect(() => {
        if (user?.role && user.role !== 'patient') {
            router.replace('/');
        }
    }, [user?.role]);

    useEffect(() => {
        if (!activeSurvey) {
            setQuestionBundle(null);
            setResponses({});
            setCurrentIndex(0);
            return;
        }

        loadQuestions(activeSurvey.question_set);
    }, [activeSurvey?.question_set]);

    //------This Function handles the Load Questions---------
    async function loadQuestions(questionSet: QuestionSet) {
        try {
            setLoadingQuestions(true);
            const bundle = await assessmentService.getQuestions('patient', questionSet);
            setQuestionBundle(bundle);
            setResponses({});
            setCurrentIndex(0);
        } catch (error: any) {
            const message = error?.response?.data?.detail || 'Unable to load the assessment right now.';
            Alert.alert('Assessment Unavailable', message, [
                { text: 'Back', onPress: () => router.replace('/') },
            ]);
        } finally {
            setLoadingQuestions(false);
        }
    }

    //------This Function handles the Select Answer---------
    function selectAnswer(value: string) {
        if (!questionBundle) {
            return;
        }

        const question = questionBundle.questions[currentIndex];
        setResponses((prev) => ({
            ...prev,
            [question.id]: {
                question_id: question.id,
                answer: value,
                skipped: false,
            },
        }));
    }

    //------This Function handles the Skip Question---------
    function skipQuestion() {
        if (!questionBundle) {
            return;
        }

        const question = questionBundle.questions[currentIndex];
        setResponses((prev) => ({
            ...prev,
            [question.id]: {
                question_id: question.id,
                answer: null,
                skipped: true,
            },
        }));
    }

    //------This Function handles the Next---------
    async function goNext() {
        if (!questionBundle) {
            return;
        }

        if (currentIndex < questionBundle.questions.length - 1) {
            setCurrentIndex((prev) => prev + 1);
            return;
        }

        await submitAssessment(questionBundle.question_set);
    }

    //------This Function handles the Previous---------
    function goPrevious() {
        if (currentIndex === 0) {
            return;
        }
        setCurrentIndex((prev) => prev - 1);
    }

    //------This Function handles the Submit Assessment---------
    async function submitAssessment(questionSet: QuestionSet) {
        if (!questionBundle) {
            return;
        }

        try {
            setSubmitting(true);
            const answers = questionBundle.questions.map((question) => (
                responses[question.id] || {
                    question_id: question.id,
                    answer: null,
                    skipped: true,
                }
            ));
            const response = await assessmentService.submitPatientAssessment(questionSet, answers);

            if (response.requires_backup && response.next_question_set === 'backup') {
                Alert.alert('One More Step', 'A few backup questions will improve confidence.');
                await loadQuestions('backup');
                return;
            }

            await refreshAssessmentStatus();
            router.replace('/');
        } catch (error: any) {
            const message = error?.response?.data?.detail || 'Unable to save your assessment right now.';
            Alert.alert('Save Failed', message);
        } finally {
            setSubmitting(false);
        }
    }

    if (statusLoading || loadingQuestions) {
        return (
            <Screen padding="none">
                <View style={s.centerState}>
                    <ActivityIndicator size="large" color={colors.white} />
                    <Text style={s.stateText}>Preparing your assessment…</Text>
                </View>
            </Screen>
        );
    }

    if (!activeSurvey || !questionBundle) {
        return (
            <Screen padding="none">
                <View style={s.centerState}>
                    <Ionicons name="checkmark-circle-outline" size={44} color={colors.white} />
                    <Text style={s.stateTitle}>Nothing pending right now</Text>
                    <Text style={s.stateText}>Your patient assessment is already on file.</Text>
                    <TouchableOpacity style={s.primaryBtn} onPress={() => router.replace('/')} activeOpacity={0.85}>
                        <Text style={s.primaryBtnText}>Continue</Text>
                    </TouchableOpacity>
                </View>
            </Screen>
        );
    }

    const currentQuestion = questionBundle.questions[currentIndex];
    const selectedAnswer = responses[currentQuestion.id];
    const badge = activeSurvey.required
        ? 'Patient Assessment'
        : 'Recommended Refresh';

    return (
        <Screen padding="none">
            <AssessmentQuestionnaire
                badge={badge}
                title={questionBundle.title}
                subtitle={questionBundle.subtitle}
                questionSet={questionBundle.question_set}
                question={currentQuestion}
                currentIndex={currentIndex}
                totalQuestions={questionBundle.questions.length}
                selectedAnswer={selectedAnswer}
                canGoBack={currentIndex > 0}
                submitting={submitting}
                onSelectAnswer={selectAnswer}
                onSkip={skipQuestion}
                onPrevious={goPrevious}
                onNext={goNext}
            />
        </Screen>
    );
}


const s = StyleSheet.create({
    centerState: {
        flex: 1,
        alignItems: 'center',
        justifyContent: 'center',
        paddingHorizontal: spacing.xl,
        gap: spacing.md,
    },
    stateTitle: {
        color: colors.textPrimary,
        fontSize: fonts.sizes.xl,
        fontWeight: '700',
    },
    stateText: {
        color: colors.textSecondary,
        fontSize: fonts.sizes.sm,
        textAlign: 'center',
        lineHeight: 20,
    },
    primaryBtn: {
        marginTop: spacing.sm,
        height: 52,
        minWidth: 160,
        borderRadius: radius.full,
        backgroundColor: colors.white,
        alignItems: 'center',
        justifyContent: 'center',
        paddingHorizontal: spacing.lg,
    },
    primaryBtnText: {
        color: colors.bg,
        fontSize: fonts.sizes.md,
        fontWeight: '700',
    },
});
