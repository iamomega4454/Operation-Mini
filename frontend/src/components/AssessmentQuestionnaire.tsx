import React from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';

import { AssessmentAnswerPayload, AssessmentQuestion, QuestionSet } from '../services/assessment';
import { colors, fonts, radius, spacing } from '../theme';


interface Props {
    badge: string;
    title: string;
    subtitle: string;
    questionSet: QuestionSet;
    question: AssessmentQuestion;
    currentIndex: number;
    totalQuestions: number;
    selectedAnswer?: AssessmentAnswerPayload;
    canGoBack: boolean;
    submitting: boolean;
    onSelectAnswer: (value: string) => void;
    onSkip: () => void;
    onPrevious: () => void;
    onNext: () => void;
}


//------This Function handles the Assessment Questionnaire---------
export default function AssessmentQuestionnaire({
    badge,
    title,
    subtitle,
    questionSet,
    question,
    currentIndex,
    totalQuestions,
    selectedAnswer,
    canGoBack,
    submitting,
    onSelectAnswer,
    onSkip,
    onPrevious,
    onNext,
}: Props) {
    const progress = ((currentIndex + 1) / totalQuestions) * 100;
    const isSkipped = Boolean(selectedAnswer?.skipped);
    const hasSelection = isSkipped || Boolean(selectedAnswer?.answer);

    return (
        <View style={s.container}>
            <View style={s.progressWrap}>
                <View style={s.progressBar}>
                    <View style={[s.progressFill, { width: `${progress}%` }]} />
                </View>
                <Text style={s.progressLabel}>{currentIndex + 1} of {totalQuestions}</Text>
            </View>

            <View style={s.headerBlock}>
                <View style={s.badge}>
                    <Ionicons name={questionSet === 'backup' ? 'sparkles-outline' : 'checkmark-circle-outline'} size={14} color={colors.textMuted} />
                    <Text style={s.badgeText}>{badge}</Text>
                </View>
                <Text style={s.title}>{title}</Text>
                <Text style={s.subtitle}>{subtitle}</Text>
            </View>

            <View style={s.questionCard}>
                <Text style={s.questionEyebrow}>Question {currentIndex + 1}</Text>
                <Text style={s.questionText}>{question.prompt}</Text>
                <View style={s.optionList}>
                    {question.options.map((option) => {
                        const selected = selectedAnswer?.answer === option.value && !selectedAnswer?.skipped;
                        return (
                            <Pressable
                                key={option.value}
                                style={({ pressed }) => [
                                    s.optionCard,
                                    selected && s.optionCardSelected,
                                    pressed && s.optionCardPressed,
                                ]}
                                onPress={() => onSelectAnswer(option.value)}
                            >
                                <View style={[s.radioOuter, selected && s.radioOuterSelected]}>
                                    {selected && <View style={s.radioInner} />}
                                </View>
                                <View style={s.optionCopy}>
                                    <Text style={[s.optionLabel, selected && s.optionLabelSelected]}>{option.label}</Text>
                                    <Text style={[s.optionDescription, selected && s.optionDescriptionSelected]}>{option.description}</Text>
                                </View>
                            </Pressable>
                        );
                    })}
                </View>
            </View>

            <View style={s.footer}>
                <View style={s.footerRow}>
                    <TouchableOpacity
                        style={[s.secondaryBtn, !canGoBack && s.secondaryBtnDisabled]}
                        onPress={onPrevious}
                        disabled={!canGoBack || submitting}
                        activeOpacity={0.8}
                    >
                        <Ionicons name="arrow-back" size={16} color={canGoBack ? colors.textPrimary : colors.textMuted} />
                        <Text style={[s.secondaryBtnText, !canGoBack && s.secondaryBtnTextDisabled]}>Back</Text>
                    </TouchableOpacity>

                    <TouchableOpacity
                        style={[s.secondaryBtn, isSkipped && s.secondaryBtnSelected]}
                        onPress={onSkip}
                        disabled={submitting}
                        activeOpacity={0.8}
                    >
                        <Ionicons name="play-skip-forward-outline" size={16} color={isSkipped ? colors.bg : colors.textPrimary} />
                        <Text style={[s.secondaryBtnText, isSkipped && s.secondaryBtnTextSelected]}>Skip</Text>
                    </TouchableOpacity>
                </View>

                <TouchableOpacity
                    style={[s.primaryBtn, (!hasSelection || submitting) && s.primaryBtnDisabled]}
                    onPress={onNext}
                    disabled={!hasSelection || submitting}
                    activeOpacity={0.85}
                >
                    {submitting ? (
                        <ActivityIndicator size="small" color={colors.bg} />
                    ) : (
                        <>
                            <Text style={s.primaryBtnText}>{currentIndex === totalQuestions - 1 ? 'Finish' : 'Continue'}</Text>
                            <Ionicons name="arrow-forward" size={18} color={colors.bg} />
                        </>
                    )}
                </TouchableOpacity>
            </View>
        </View>
    );
}


const s = StyleSheet.create({
    container: {
        flex: 1,
        paddingHorizontal: spacing.lg,
        paddingTop: spacing.md,
        paddingBottom: spacing.xxl,
    },
    progressWrap: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: spacing.sm,
        marginBottom: spacing.md,
    },
    progressBar: {
        flex: 1,
        height: 4,
        backgroundColor: colors.border,
        borderRadius: radius.full,
        overflow: 'hidden',
    },
    progressFill: {
        height: '100%',
        backgroundColor: colors.white,
        borderRadius: radius.full,
    },
    progressLabel: {
        color: colors.textMuted,
        fontSize: 11,
        fontWeight: '600',
        letterSpacing: 0.6,
    },
    headerBlock: {
        gap: spacing.xs,
        marginBottom: spacing.lg,
    },
    badge: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 5,
        alignSelf: 'flex-start',
        paddingHorizontal: spacing.sm,
        paddingVertical: 4,
        borderRadius: radius.full,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
    },
    badgeText: {
        color: colors.textMuted,
        fontSize: 11,
        fontWeight: '600',
        letterSpacing: 0.5,
    },
    title: {
        color: colors.textPrimary,
        fontSize: 26,
        fontWeight: '700',
        lineHeight: 32,
    },
    subtitle: {
        color: colors.textSecondary,
        fontSize: fonts.sizes.sm,
        lineHeight: 20,
    },
    questionCard: {
        flex: 1,
        backgroundColor: colors.surface,
        borderRadius: radius.xl,
        borderWidth: 1,
        borderColor: colors.border,
        padding: spacing.lg,
        gap: spacing.md,
    },
    questionEyebrow: {
        color: colors.textMuted,
        fontSize: 10,
        fontWeight: '700',
        letterSpacing: 1.2,
        textTransform: 'uppercase',
    },
    questionText: {
        color: colors.textPrimary,
        fontSize: fonts.sizes.xl,
        fontWeight: '700',
        lineHeight: 30,
    },
    optionList: {
        gap: spacing.sm,
    },
    optionCard: {
        flexDirection: 'row',
        alignItems: 'flex-start',
        gap: spacing.md,
        borderRadius: radius.lg,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.bgTertiary,
        padding: spacing.md,
    },
    optionCardSelected: {
        borderColor: colors.white,
        backgroundColor: 'rgba(255,255,255,0.08)',
    },
    optionCardPressed: {
        opacity: 0.8,
    },
    radioOuter: {
        width: 22,
        height: 22,
        borderRadius: 11,
        borderWidth: 1,
        borderColor: colors.textMuted,
        alignItems: 'center',
        justifyContent: 'center',
        marginTop: 2,
    },
    radioOuterSelected: {
        borderColor: colors.white,
        backgroundColor: colors.white,
    },
    radioInner: {
        width: 8,
        height: 8,
        borderRadius: 4,
        backgroundColor: colors.bg,
    },
    optionCopy: {
        flex: 1,
        gap: 3,
    },
    optionLabel: {
        color: colors.textPrimary,
        fontSize: fonts.sizes.md,
        fontWeight: '700',
    },
    optionLabelSelected: {
        color: colors.white,
    },
    optionDescription: {
        color: colors.textSecondary,
        fontSize: fonts.sizes.xs,
        lineHeight: 18,
    },
    optionDescriptionSelected: {
        color: colors.textPrimary,
    },
    footer: {
        marginTop: spacing.lg,
        gap: spacing.sm,
    },
    footerRow: {
        flexDirection: 'row',
        gap: spacing.sm,
    },
    secondaryBtn: {
        flex: 1,
        height: 48,
        borderRadius: radius.full,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        gap: spacing.xs,
    },
    secondaryBtnDisabled: {
        opacity: 0.4,
    },
    secondaryBtnSelected: {
        backgroundColor: colors.white,
        borderColor: colors.white,
    },
    secondaryBtnText: {
        color: colors.textPrimary,
        fontSize: fonts.sizes.sm,
        fontWeight: '600',
    },
    secondaryBtnTextDisabled: {
        color: colors.textMuted,
    },
    secondaryBtnTextSelected: {
        color: colors.bg,
    },
    primaryBtn: {
        height: 56,
        borderRadius: radius.full,
        backgroundColor: colors.white,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        gap: spacing.sm,
    },
    primaryBtnDisabled: {
        opacity: 0.45,
    },
    primaryBtnText: {
        color: colors.bg,
        fontSize: fonts.sizes.md,
        fontWeight: '700',
    },
});
