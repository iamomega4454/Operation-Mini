import React, { useEffect, useRef, useState } from 'react';
import { View, Text, StyleSheet, Animated, Dimensions } from 'react-native';
import { useRouter } from 'expo-router';
import { useAuth } from '../src/context/auth';
import { useAssessment } from '../src/context/assessment';
import { colors, fonts, spacing } from '../src/theme';

const { height } = Dimensions.get('window');

const LETTERS = [
    { letter: 'A', word: 'Assistive' },
    { letter: 'U', word: 'User' },
    { letter: 'R', word: 'Reminder' },
    { letter: 'A', word: 'App' },
];

//------This Function handles the Splash Screen---------
export default function SplashScreen() {
    const router = useRouter();
    const { user, loading } = useAuth();
    const { nextRequiredSurvey, loading: assessmentLoading } = useAssessment();
    const fadeAnims = useRef(LETTERS.map(() => new Animated.Value(0))).current;
    const wordAnims = useRef(LETTERS.map(() => new Animated.Value(0))).current;
    const containerFade = useRef(new Animated.Value(1)).current;
    const [phase, setPhase] = useState(0);
    const [isAnimationDone, setIsAnimationDone] = useState(false);

    useEffect(() => {
        const letterSequence = LETTERS.map((_, i) =>
            Animated.timing(fadeAnims[i], { toValue: 1, duration: 300, useNativeDriver: true })
        );
        Animated.stagger(200, letterSequence).start(() => {
            setPhase(1);
            const wordSequence = LETTERS.map((_, i) =>
                Animated.timing(wordAnims[i], { toValue: 1, duration: 400, useNativeDriver: true })
            );
            Animated.stagger(250, wordSequence).start(() => {
                setTimeout(() => {
                    setIsAnimationDone(true);
                }, 800);
            });
        });
    }, []);

    useEffect(() => {
        if (isAnimationDone && !loading && (!user || !assessmentLoading)) {
            Animated.timing(containerFade, { toValue: 0, duration: 500, useNativeDriver: true }).start(() => {
                navigate();
            });
        }
    }, [isAnimationDone, loading, assessmentLoading, user]);

    //------This Function handles the Navigate---------
    function navigate() {
        if (!user) {
            router.replace('/(auth)/login');
        } else if (nextRequiredSurvey) {
            router.replace((nextRequiredSurvey.survey_type === 'caregiver' ? '/(assessment)/caregiver' : '/(assessment)/patient') as any);
        } else if (!user.is_onboarded && user.role === 'patient') {
            router.replace('/(onboarding)/illness');
        } else if (!user.is_onboarded && user.role === 'caregiver') {
            router.replace('/(onboarding)/caregiver');
        } else if (user.role === 'caregiver') {
            router.replace('/(caregiver)/dashboard');
        } else if (user.role === 'admin') {
            router.replace('/(admin)/dashboard');
        } else {
            router.replace('/(patient)/dashboard');
        }
    }

    return (
        <Animated.View style={[s.container, { opacity: containerFade }]}>
            <View style={s.letterColumn}>
                {LETTERS.map((item, i) => (
                    <View key={i} style={s.row}>
                        <Animated.Text style={[s.letter, { opacity: fadeAnims[i] }]}>
                            {item.letter}
                        </Animated.Text>
                        {phase >= 1 && (
                            <Animated.Text style={[s.word, { opacity: wordAnims[i] }]}>
                                {item.word.slice(1)}
                            </Animated.Text>
                        )}
                    </View>
                ))}
            </View>
            <Text style={s.tagline}>your memory, amplified</Text>
        </Animated.View>
    );
}

const s = StyleSheet.create({
    container: {
        flex: 1,
        backgroundColor: colors.bg,
        alignItems: 'center',
        justifyContent: 'center',
    },
    letterColumn: { alignItems: 'flex-start' },
    row: { flexDirection: 'row', alignItems: 'baseline', marginVertical: 4 },
    letter: {
        color: colors.red,
        fontSize: 52,
        fontWeight: '900',
        letterSpacing: 2,
    },
    word: {
        color: colors.textPrimary,
        fontSize: 52,
        fontWeight: '300',
        letterSpacing: 1,
    },
    tagline: {
        color: colors.textMuted,
        fontSize: fonts.sizes.sm,
        marginTop: spacing.xl,
        letterSpacing: 3,
        textTransform: 'uppercase',
    },
});
