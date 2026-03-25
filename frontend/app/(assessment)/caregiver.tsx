import React, { useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Alert, Pressable, StyleSheet, Text, View } from 'react-native';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';

import Screen from '../../src/components/Screen';
import AssessmentQuestionnaire from '../../src/components/AssessmentQuestionnaire';
import { useAssessment } from '../../src/context/assessment';
import { useAuth } from '../../src/context/auth';
import {
    AssessmentAnswerPayload,
    AssessmentQuestionBundle,
    AssessmentSurveyEntry,
    QuestionSet,
    assessmentService,
} from '../../src/services/assessment';
import { colors, fonts, radius, spacing } from '../../src/theme';


//------This Function handles the Caregiver Assessment Screen---------
export default function CaregiverAssessmentScreen() {
    const router = useRouter();
    const { user } = useAuth();
    const { status, loading: statusLoading, refreshAssessmentStatus } = useAssessment();
    const [selectedSurvey, setSelectedSurvey] = useState<AssessmentSurveyEntry | null>(null);
    const [questionBundle, setQuestionBundle] = useState<AssessmentQuestionBundle | null>(null);
    const [responses, setResponses] = useState<Record<string, AssessmentAnswerPayload>>({});
    const [currentIndex, setCurrentIndex] = useState(0);
    const [loadingQuestions, setLoadingQuestions] = useState(false);
    const [submitting, setSubmitting] = useState(false);

    const availableSurveys = useMemo(() => {
        const pending = status?.pending_surveys.filter((survey) => survey.survey_type === 'caregiver') || [];
        if (pending.length > 0) {
            return pending;
        }
        return status?.recommended_surveys.filter((survey) => survey.survey_type === 'caregiver') || [];
    }, [status]);

    useEffect(() => {
        if (user?.role && user.role !== 'caregiver') {
            router.replace('/');
        }
    }, [user?.role]);

    useEffect(() => {
        if (availableSurveys.length === 0) {
            setSelectedSurvey(null);
            setQuestionBundle(null);
            return;
        }

        if (availableSurveys.length === 1) {
            handleSelectSurvey(availableSurveys[0]);
            return;
        }

        if (selectedSurvey && !availableSurveys.some((survey) => survey.patient_id === selectedSurvey.patient_id && survey.question_set === selectedSurvey.question_set)) {
            setSelectedSurvey(null);
            setQuestionBundle(null);
        }
    }, [availableSurveys.map((survey) => `${survey.patient_id}:${survey.question_set}`).join('|')]);

    //------This Function handles the Select Survey---------
    async function handleSelectSurvey(survey: AssessmentSurveyEntry) {
        setSelectedSurvey(survey);
        await loadQuestions(survey.question_set);
    }

    //------This Function handles the Load Questions---------
    async function loadQuestions(questionSet: QuestionSet) {
        try {
            setLoadingQuestions(true);
            const bundle = await assessmentService.getQuestions('caregiver', questionSet);
            setQuestionBundle(bundle);
            setResponses({});
            setCurrentIndex(0);
        } catch (error: any) {
            const message = error?.response?.data?.detail || 'Unable to load the caregiver assessment right now.';
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
        if (!questionBundle || !selectedSurvey) {
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
            const response = await assessmentService.submitCaregiverAssessment(
                selectedSurvey.patient_id,
                questionSet,
                answers,
            );

            if (response.requires_backup && response.next_question_set === 'backup') {
                Alert.alert('One More Step', 'A few follow-up questions will improve confidence for this patient.');
                const nextSurvey = { ...selectedSurvey, question_set: 'backup' as QuestionSet };
                setSelectedSurvey(nextSurvey);
                await loadQuestions('backup');
                return;
            }

            const nextStatus = await refreshAssessmentStatus();
            const nextPending = nextStatus?.pending_surveys.filter((survey) => survey.survey_type === 'caregiver') || [];

            if (nextPending.length === 1) {
                await handleSelectSurvey(nextPending[0]);
                return;
            }

            if (nextPending.length > 1) {
                setSelectedSurvey(null);
                setQuestionBundle(null);
                return;
            }

            router.replace('/');
        } catch (error: any) {
            const message = error?.response?.data?.detail || 'Unable to save the caregiver assessment right now.';
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
                    <Text style={s.stateText}>Preparing caregiver assessment…</Text>
                </View>
            </Screen>
        );
    }

    if (availableSurveys.length === 0) {
        return (
            <Screen padding="none">
                <View style={s.centerState}>
                    <Ionicons name="checkmark-circle-outline" size={44} color={colors.white} />
                    <Text style={s.stateTitle}>Nothing pending right now</Text>
                    <Text style={s.stateText}>All linked patients already have a caregiver assessment from you.</Text>
                    <Pressable style={s.primaryBtn} onPress={() => router.replace('/')} accessibilityRole="button">
                        <Text style={s.primaryBtnText}>Continue</Text>
                    </Pressable>
                </View>
            </Screen>
        );
    }

    if (!selectedSurvey || !questionBundle) {
        return (
            <Screen padding="none">
                <View style={s.selectionContainer}>
                    <View style={s.selectionHeader}>
                        <Text style={s.selectionTitle}>Choose a patient</Text>
                        <Text style={s.selectionSubtitle}>Each linked patient needs a caregiver assessment to improve accuracy.</Text>
                    </View>

                    <View style={s.selectionList}>
                        {availableSurveys.map((survey) => (
                            <Pressable
                                key={`${survey.patient_id}:${survey.question_set}`}
                                style={({ pressed }) => [s.patientCard, pressed && s.patientCardPressed]}
                                onPress={() => handleSelectSurvey(survey)}
                            >
                                <View style={s.patientIcon}>
                                    <Ionicons name="person-outline" size={20} color={colors.textPrimary} />
                                </View>
                                <View style={s.patientCopy}>
                                    <Text style={s.patientName}>{survey.patient_name}</Text>
                                    <Text style={s.patientMeta}>
                                        {survey.required ? 'Required now' : 'Recommended follow-up'}
                                    </Text>
                                </View>
                                <Ionicons name="chevron-forward" size={18} color={colors.textMuted} />
                            </Pressable>
                        ))}
                    </View>
                </View>
            </Screen>
        );
    }

    const currentQuestion = questionBundle.questions[currentIndex];
    const selectedAnswer = responses[currentQuestion.id];
    const badge = selectedSurvey.required
        ? `Caregiver Assessment • ${selectedSurvey.patient_name}`
        : `Follow-Up • ${selectedSurvey.patient_name}`;

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
    selectionContainer: {
        flex: 1,
        paddingHorizontal: spacing.lg,
        paddingTop: spacing.xl,
        paddingBottom: spacing.xxl,
        gap: spacing.lg,
    },
    selectionHeader: {
        gap: spacing.xs,
    },
    selectionTitle: {
        color: colors.textPrimary,
        fontSize: 26,
        fontWeight: '700',
    },
    selectionSubtitle: {
        color: colors.textSecondary,
        fontSize: fonts.sizes.sm,
        lineHeight: 20,
    },
    selectionList: {
        gap: spacing.sm,
    },
    patientCard: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: spacing.md,
        borderRadius: radius.xl,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
        padding: spacing.lg,
    },
    patientCardPressed: {
        opacity: 0.82,
    },
    patientIcon: {
        width: 42,
        height: 42,
        borderRadius: 21,
        backgroundColor: colors.bgTertiary,
        alignItems: 'center',
        justifyContent: 'center',
        borderWidth: 1,
        borderColor: colors.border,
    },
    patientCopy: {
        flex: 1,
        gap: 3,
    },
    patientName: {
        color: colors.textPrimary,
        fontSize: fonts.sizes.md,
        fontWeight: '700',
    },
    patientMeta: {
        color: colors.textSecondary,
        fontSize: fonts.sizes.xs,
    },
});
