import React, { useEffect, useState, useRef } from 'react';
import {
    View,
    Text,
    StyleSheet,
    TouchableOpacity,
    Image,
    Alert,
    ActivityIndicator,
    Modal,
    Animated,
    Switch,
    ScrollView,
} from 'react-native';
import { useRouter } from 'expo-router';
import * as Haptics from 'expo-haptics';
import { useAuth } from '../../src/context/auth';
import { useAssessment } from '../../src/context/assessment';
import { useAura } from '../../src/context/aura';
import Screen from '../../src/components/Screen';
import Card from '../../src/components/Card';
import PatientHeader from '../../src/components/PatientHeader';
import { colors, fonts, spacing, radius } from '../../src/theme';
import { Ionicons } from '@expo/vector-icons';
import api from '../../src/services/api';
import {
    getTodayStats,
    ModuleStats,
    ModuleSettings,
    getModuleSettings,
} from '../../src/services/moduleStats';
import { pedometerService, StepData } from '../../src/services/pedometer';

interface Suggestion {
    id: string;
    type: string;
    title: string;
    description: string;
    status: string;
    priority: number;
    action_label?: string;
    context_data?: {
        source?: string;
        sender_name?: string;
        sent_at?: string;
    };
    created_at?: string;
}

//------This Function handles the Patient Dashboard---------
export default function PatientDashboard() {
    const router = useRouter();
    const { user, isVoiceSetup, loading: authLoading } = useAuth();
    const { recommendedSurveys } = useAssessment();
    const {
        isConnected,
        moduleIp,
        modulePort,
        disconnect,
        isAutoConnecting,
        autoConnectMessage,
        updateSettings,
        getSettings,
    } = useAura();
    const [suggestion, setSuggestion] = useState<Suggestion | null>(null);
    const [loadingSuggestion, setLoadingSuggestion] = useState(false);


    const [showNotConnectedModal, setShowNotConnectedModal] = useState(false);
    const [showSettingsModal, setShowSettingsModal] = useState(false);
    const [todayStats, setTodayStats] = useState<ModuleStats | null>(null);
    const [moduleSettings, setModuleSettings] = useState<ModuleSettings>({
        faceRecognitionEnabled: true,
        voiceResponseEnabled: true,
        autoConnectEnabled: false,
    });


    const [stepData, setStepData] = useState<StepData | null>(null);
    const [isPedometerAvailable, setIsPedometerAvailable] = useState(false);
    const [showStepPermissionModal, setShowStepPermissionModal] = useState(false);


    const pulseAnim = useRef(new Animated.Value(1)).current;
    const pulseScale = useRef(new Animated.Value(1)).current;
    const recommendedAssessment = recommendedSurveys.find((survey) => survey.survey_type === 'patient');

    useEffect(() => {
        if (!authLoading && user) {
            loadSuggestion();
            initializePedometer();
        }
    }, [authLoading, user]);


    //------This Function handles the Initialize Pedometer---------
    async function initializePedometer() {
        const available = await pedometerService.initialize();
        setIsPedometerAvailable(available);

        if (available) {
            const data = await pedometerService.getStepData();
            setStepData(data);


            pedometerService.startUpdates(async (steps) => {
                const data = await pedometerService.getStepData();
                setStepData(data);
            });
        } else if (pedometerService.isPermissionDenied()) {

            setShowStepPermissionModal(true);
        }
    }


    //------This Function handles the Request Step Permission---------
    async function requestStepPermission() {
        const available = await pedometerService.initialize();
        setIsPedometerAvailable(available);

        if (available) {
            setShowStepPermissionModal(false);
            const data = await pedometerService.getStepData();
            setStepData(data);

            pedometerService.startUpdates(async (steps) => {
                const data = await pedometerService.getStepData();
                setStepData(data);
            });
        }
    }


    useEffect(() => {
        if (isConnected) {
            const pulse = Animated.loop(
                Animated.sequence([
                    Animated.timing(pulseScale, {
                        toValue: 1.05,
                        duration: 1000,
                        useNativeDriver: true,
                    }),
                    Animated.timing(pulseScale, {
                        toValue: 1,
                        duration: 1000,
                        useNativeDriver: true,
                    }),
                ])
            );
            pulse.start();
            return () => pulse.stop();
        }
    }, [isConnected]);


    useEffect(() => {
        if (showSettingsModal) {
            loadStats();
            loadSettings();
        }
    }, [showSettingsModal]);


    useEffect(() => {
        if (!isConnected && showSettingsModal) {

            setShowSettingsModal(false);
        }
    }, [isConnected]);

    //------This Function handles the Load Stats---------
    async function loadStats() {
        const stats = await getTodayStats();
        setTodayStats(stats);
    }

    //------This Function handles the Load Settings---------
    async function loadSettings() {
        const settings = await getSettings();
        setModuleSettings(settings);
    }

    //------This Function handles the Load Suggestion---------
    async function loadSuggestion() {
        try {
            setLoadingSuggestion(true);
            const response = await api.get('/suggestions/active?limit=1');

            if (response.data && response.data.length > 0) {
                setSuggestion(response.data[0]);
            } else {
                setSuggestion(null);
            }
        } catch (e: any) {
            if (!e?.response || e.response.status !== 401) {
                console.error('[Dashboard] Failed to load suggestion:', e);
            }
            setSuggestion(null);
        } finally {
            setLoadingSuggestion(false);
        }
    }

    //------This Function handles the Handle Dismiss Suggestion---------
    async function handleDismissSuggestion() {
        if (!suggestion) return;

        try {
            await api.post(`/suggestions/${suggestion.id}/dismiss`);
            setSuggestion(null);
            loadSuggestion();
        } catch (e) {
            console.error('[Dashboard] Failed to dismiss suggestion:', e);
            Alert.alert('Error', 'Failed to dismiss suggestion');
        }
    }

    //------This Function handles the Handle Complete Suggestion---------
    async function handleCompleteSuggestion() {
        if (!suggestion) return;

        try {
            await api.post(`/suggestions/${suggestion.id}/complete`);
            Alert.alert('Great!', 'Suggestion marked as completed');
            setSuggestion(null);
            loadSuggestion();
        } catch (e) {
            console.error('[Dashboard] Failed to complete suggestion:', e);
            Alert.alert('Error', 'Failed to complete suggestion');
        }
    }

    //------This Function handles the Handle Main Button Press---------
    async function handleMainButtonPress() {
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);

        if (!isConnected) {
            setShowNotConnectedModal(true);
            return;
        }


        setShowSettingsModal(true);
    }

    //------This Function handles the Handle Connect Press---------
    function handleConnectPress() {
        setShowNotConnectedModal(false);
        router.push('/(patient)/connect-aura');
    }

    //------This Function handles the Handle Disconnect---------
    async function handleDisconnect() {
        disconnect();
        setShowSettingsModal(false);
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    }

    //------This Function handles the Handle Toggle Setting---------
    async function handleToggleSetting(key: keyof ModuleSettings, value: boolean) {
        setModuleSettings(prev => ({ ...prev, [key]: value }));
        await updateSettings({ [key]: value });
    }

    const isCaregiverMessage = suggestion?.context_data?.source === 'caregiver_encouragement';

    return (
        <Screen>
            { }
            <PatientHeader showRightIcon={false} />

            { }
            <TouchableOpacity
                style={[
                    s.connectionStatus,
                    isConnected ? s.connectionStatusConnected : s.connectionStatusDisconnected,
                ]}
                onPress={() => {
                    if (isConnected) {
                        setShowSettingsModal(true);
                    } else {
                        setShowNotConnectedModal(true);
                    }
                }}
            >
                <View style={[
                    s.statusIconWrap,
                    isConnected ? s.statusIconWrapConnected : s.statusIconWrapDisconnected,
                ]}>
                    <Ionicons
                        name={isConnected ? 'wifi' : 'wifi-outline'}
                        size={13}
                        color={isConnected ? colors.bg : colors.red}
                    />
                </View>
                <Text style={s.statusLabel}>Aura</Text>
                <Text style={[
                    s.statusValue,
                    isConnected ? s.statusValueConnected : s.statusValueDisconnected,
                ]}>
                    {isConnected ? 'Connected' : 'Disconnected'}
                </Text>
                <Ionicons name="chevron-forward" size={14} color={colors.textMuted} />
            </TouchableOpacity>

            { }
            {isAutoConnecting && (
                <View style={s.autoConnectToast}>
                    <ActivityIndicator size="small" color={colors.white} />
                    <Text style={s.autoConnectText}>{autoConnectMessage}</Text>
                </View>
            )}

            {recommendedAssessment && (
                <TouchableOpacity
                    style={s.assessmentCard}
                    onPress={() => router.push('/(assessment)/patient' as any)}
                    activeOpacity={0.85}
                >
                    <View style={s.assessmentIcon}>
                        <Ionicons name="pulse-outline" size={18} color={colors.bg} />
                    </View>
                    <View style={s.assessmentCopy}>
                        <Text style={s.assessmentTitle}>Refine Your Support Profile</Text>
                        <Text style={s.assessmentText}>A quick follow-up can improve confidence and personalization.</Text>
                    </View>
                    <Ionicons name="chevron-forward" size={16} color={colors.textMuted} />
                </TouchableOpacity>
            )}

            { }
            <View style={s.centerContent}>
                { }
                <Animated.View style={{ transform: [{ scale: pulseScale }] }}>
                    <TouchableOpacity
                        style={[
                            s.mainBtn,
                            isConnected ? s.mainBtnConnected : s.mainBtnDisconnected
                        ]}
                        onPress={handleMainButtonPress}
                    >
                        {isConnected ? (
                            <Ionicons name="camera" size={48} color={colors.bg} />
                        ) : (
                            <View style={s.disconnectedIcon}>
                                <Ionicons name="wifi" size={40} color={colors.white} />
                                <View style={s.crossLine} />
                            </View>
                        )}
                    </TouchableOpacity>
                </Animated.View>

                <TouchableOpacity
                    style={s.voiceBtn}
                    onPress={() => {
                        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
                        if (!isVoiceSetup) {
                            router.push('/(patient)/voice-setup');
                        } else {
                            router.push('/(patient)/chat?autoStart=true');
                        }
                    }}
                >
                    <Ionicons name="mic" size={24} color={colors.textPrimary} />
                </TouchableOpacity>
            </View>

            { }
            {loadingSuggestion ? (
                <Card style={s.insightCard}>
                    <ActivityIndicator size="small" color={colors.white} />
                    <Text style={[s.insightDesc, { textAlign: 'center', marginTop: spacing.sm }]}>Loading suggestion...</Text>
                </Card>
            ) : suggestion && (
                <Card style={s.insightCard}>
                    <View style={s.insightHeader}>
                        <Ionicons name={isCaregiverMessage ? 'heart' : 'sparkles'} size={16} color={colors.white} />
                        <Text style={s.insightLabel}>{isCaregiverMessage ? 'FROM YOUR CAREGIVER' : 'SUGGESTION FOR YOU'}</Text>
                        {suggestion.priority >= 4 && (
                            <View style={s.priorityBadge}>
                                <Text style={s.priorityText}>!</Text>
                            </View>
                        )}
                    </View>
                    <Text style={s.insightTitle}>{suggestion.title}</Text>
                    <Text style={s.insightDesc}>{suggestion.description}</Text>
                    {isCaregiverMessage && (
                        <Text style={s.encouragementMeta}>
                            {suggestion.context_data?.sender_name ? `Sent by ${suggestion.context_data.sender_name}` : 'Sent by caregiver'}
                        </Text>
                    )}
                    <View style={s.actionButtons}>
                        {(suggestion.action_label || isCaregiverMessage) && (
                            <TouchableOpacity style={s.insightBtnPrimary} onPress={handleCompleteSuggestion}>
                                <Ionicons name="checkmark-done-outline" size={16} color={colors.bg} />
                                <Text style={[s.insightBtnText, { color: colors.bg }]}>{suggestion.action_label || 'Mark as Read'}</Text>
                            </TouchableOpacity>
                        )}
                        <TouchableOpacity style={s.insightBtn} onPress={handleDismissSuggestion}>
                            <Ionicons name="close-outline" size={16} color={colors.white} />
                            <Text style={s.insightBtnText}>Dismiss</Text>
                        </TouchableOpacity>
                    </View>
                </Card>
            )}

            { }
            {stepData && (
                <Card style={s.stepCard}>
                    <View style={s.stepHeader}>
                        <Ionicons name="footsteps" size={20} color={colors.white} />
                        <Text style={s.stepLabel}>TODAY'S STEPS</Text>
                    </View>
                    <View style={s.stepContent}>
                        <Text style={s.stepCount}>{stepData.steps.toLocaleString()}</Text>
                        <Text style={s.stepGoal}>of {stepData.goal.toLocaleString()} goal</Text>
                    </View>
                    <View style={s.stepProgress}>
                        <View
                            style={[
                                s.stepProgressBar,
                                { width: `${Math.min((stepData.steps / stepData.goal) * 100, 100)}%` }
                            ]}
                        />
                    </View>
                    <Text style={s.stepPercent}>
                        {Math.round((stepData.steps / stepData.goal) * 100)}% complete
                    </Text>
                </Card>
            )}

            <View style={{ height: 100 }} />

            <Modal
                visible={showNotConnectedModal}
                transparent
                animationType="fade"
                onRequestClose={() => setShowNotConnectedModal(false)}
            >
                <TouchableOpacity
                    style={s.modalOverlay}
                    activeOpacity={1}
                    onPress={() => setShowNotConnectedModal(false)}
                >
                    <View style={s.modalContent} onStartShouldSetResponder={() => true}>
                        <Ionicons name="wifi-outline" size={48} color={colors.red} />
                        <Text style={s.modalTitle}>Aura Module Not Connected</Text>
                        <Text style={s.modalMessage}>
                            Would you like to connect to your Aura module?
                        </Text>
                        <TouchableOpacity style={s.modalConnectBtn} onPress={handleConnectPress}>
                            <Ionicons name="wifi-outline" size={18} color={colors.bg} />
                            <Text style={s.modalConnectBtnText}>Connect</Text>
                        </TouchableOpacity>
                        <TouchableOpacity
                            style={s.modalCancelBtn}
                            onPress={() => setShowNotConnectedModal(false)}
                        >
                            <Ionicons name="close-outline" size={18} color={colors.textSecondary} />
                            <Text style={s.modalCancelBtnText}>Cancel</Text>
                        </TouchableOpacity>
                        <TouchableOpacity
                            onPress={() => setShowNotConnectedModal(false)}
                            style={s.skipLink}
                        >
                            <Ionicons name="play-skip-forward-outline" size={16} color={colors.textMuted} />
                            <Text style={s.skipLinkText}>Skip for now</Text>
                        </TouchableOpacity>
                    </View>
                </TouchableOpacity>
            </Modal>

            <Modal
                visible={showSettingsModal}
                transparent
                animationType="slide"
                onRequestClose={() => setShowSettingsModal(false)}
            >
                <View style={s.settingsModalOverlay}>
                    <View style={s.settingsModalContent}>
                        <View style={s.settingsHeader}>
                            <Text style={s.settingsTitle}>Aura Module</Text>
                            <View style={s.connectionInfo}>
                                <View style={[s.statusDot, { backgroundColor: colors.white }]} />
                                <Text style={s.connectedText}>Connected</Text>
                            </View>
                            <Text style={s.moduleAddress}>{moduleIp}:{modulePort}</Text>
                        </View>

                        <ScrollView style={s.settingsScroll} showsVerticalScrollIndicator={false}>
                            <View style={s.statsSection}>
                                <Text style={s.sectionTitle}>Today's Activity</Text>
                                <View style={s.statsGrid}>
                                    <View style={s.statCard}>
                                        <Ionicons name="person" size={24} color={colors.white} />
                                        <Text style={s.statNumber}>{todayStats?.facesRecognized || 0}</Text>
                                        <Text style={s.statLabel}>Faces Recognized</Text>
                                    </View>
                                    <View style={s.statCard}>
                                        <Ionicons name="chatbubbles" size={24} color={colors.white} />
                                        <Text style={s.statNumber}>{todayStats?.conversations || 0}</Text>
                                        <Text style={s.statLabel}>Conversations</Text>
                                    </View>
                                    <View style={s.statCard}>
                                        <Ionicons name="mic" size={24} color={colors.white} />
                                        <Text style={s.statNumber}>{todayStats?.voiceCommands || 0}</Text>
                                        <Text style={s.statLabel}>Voice Commands</Text>
                                    </View>
                                </View>
                            </View>

                            <View style={s.settingsSection}>
                                <Text style={s.sectionTitle}>Settings</Text>

                                <View style={s.settingRow}>
                                    <View style={s.settingInfo}>
                                        <Ionicons name="eye-outline" size={20} color={colors.textSecondary} />
                                        <Text style={s.settingLabel}>Face Recognition</Text>
                                    </View>
                                    <Switch
                                        value={moduleSettings.faceRecognitionEnabled}
                                        onValueChange={(val) => handleToggleSetting('faceRecognitionEnabled', val)}
                                        trackColor={{ false: colors.border, true: colors.white }}
                                        thumbColor={moduleSettings.faceRecognitionEnabled ? colors.bg : colors.surfaceLight}
                                    />
                                </View>

                                <View style={s.settingRow}>
                                    <View style={s.settingInfo}>
                                        <Ionicons name="volume-high-outline" size={20} color={colors.textSecondary} />
                                        <Text style={s.settingLabel}>Voice Response</Text>
                                    </View>
                                    <Switch
                                        value={moduleSettings.voiceResponseEnabled}
                                        onValueChange={(val) => handleToggleSetting('voiceResponseEnabled', val)}
                                        trackColor={{ false: colors.border, true: colors.white }}
                                        thumbColor={moduleSettings.voiceResponseEnabled ? colors.bg : colors.surfaceLight}
                                    />
                                </View>

                                <View style={s.settingRow}>
                                    <View style={s.settingInfo}>
                                        <Ionicons name="repeat-outline" size={20} color={colors.textSecondary} />
                                        <Text style={s.settingLabel}>Auto-connect</Text>
                                    </View>
                                    <Switch
                                        value={moduleSettings.autoConnectEnabled}
                                        onValueChange={(val) => handleToggleSetting('autoConnectEnabled', val)}
                                        trackColor={{ false: colors.border, true: colors.white }}
                                        thumbColor={moduleSettings.autoConnectEnabled ? colors.bg : colors.surfaceLight}
                                    />
                                </View>

                                <TouchableOpacity
                                    style={s.cameraPreviewBtn}
                                    onPress={() => {
                                        setShowSettingsModal(false);
                                        router.push('/(patient)/camera-preview');
                                    }}
                                >
                                    <Ionicons name="videocam-outline" size={20} color={colors.white} />
                                    <Text style={s.cameraPreviewText}>Camera Preview</Text>
                                    <Ionicons name="chevron-forward" size={16} color={colors.textMuted} />
                                </TouchableOpacity>
                            </View>

                            <View style={s.actionsSection}>
                                <TouchableOpacity style={s.disconnectBtn} onPress={handleDisconnect}>
                                    <Ionicons name="unlink-outline" size={20} color={colors.red} />
                                    <Text style={s.disconnectBtnText}>Disconnect</Text>
                                </TouchableOpacity>
                            </View>
                        </ScrollView>

                        <TouchableOpacity
                            style={s.closeBtn}
                            onPress={() => setShowSettingsModal(false)}
                        >
                            <Ionicons name="close-outline" size={18} color={colors.textSecondary} />
                            <Text style={s.closeBtnText}>Close</Text>
                        </TouchableOpacity>
                    </View>
                </View>
            </Modal>

            <Modal
                visible={showStepPermissionModal}
                transparent
                animationType="fade"
                onRequestClose={() => setShowStepPermissionModal(false)}
            >
                <TouchableOpacity
                    style={s.modalOverlay}
                    activeOpacity={1}
                    onPress={() => setShowStepPermissionModal(false)}
                >
                    <View style={s.modalContent} onStartShouldSetResponder={() => true}>
                        <Ionicons name="footsteps-outline" size={48} color={colors.white} />
                        <Text style={s.modalTitle}>Enable Step Tracking</Text>
                        <Text style={s.modalMessage}>
                            Allow access to motion sensors to automatically track your daily steps.
                        </Text>
                        <TouchableOpacity style={s.modalConnectBtn} onPress={requestStepPermission}>
                            <Ionicons name="checkmark-done-outline" size={18} color={colors.bg} />
                            <Text style={s.modalConnectBtnText}>Allow</Text>
                        </TouchableOpacity>
                        <TouchableOpacity
                            style={s.modalCancelBtn}
                            onPress={() => setShowStepPermissionModal(false)}
                        >
                            <Ionicons name="close-circle-outline" size={18} color={colors.textSecondary} />
                            <Text style={s.modalCancelBtnText}>Not Now</Text>
                        </TouchableOpacity>
                    </View>
                </TouchableOpacity>
            </Modal>
        </Screen>
    );
}

const s = StyleSheet.create({
    header: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'center',
        paddingVertical: spacing.md,
        paddingHorizontal: spacing.sm,
    },
    connectionStatus: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        alignSelf: 'center',
        minHeight: 34,
        borderRadius: radius.full,
        borderWidth: 1,
        paddingLeft: spacing.sm,
        paddingRight: spacing.xs,
        gap: 6,
        marginBottom: spacing.sm,
    },
    connectionStatusConnected: {
        backgroundColor: 'rgba(255,255,255,0.08)',
        borderColor: colors.borderLight,
    },
    connectionStatusDisconnected: {
        backgroundColor: 'rgba(255,59,48,0.12)',
        borderColor: 'rgba(255,59,48,0.3)',
    },
    statusDot: {
        width: 6,
        height: 6,
        borderRadius: 3,
    },
    statusIconWrap: {
        width: 20,
        height: 20,
        borderRadius: 10,
        alignItems: 'center',
        justifyContent: 'center',
    },
    statusIconWrapConnected: {
        backgroundColor: colors.white,
    },
    statusIconWrapDisconnected: {
        backgroundColor: 'rgba(255,59,48,0.12)',
    },
    statusLabel: {
        color: colors.textSecondary,
        fontSize: 12,
        fontWeight: '500',
    },
    statusValue: {
        fontSize: fonts.sizes.sm,
        fontWeight: '600',
        letterSpacing: -0.1,
    },
    statusValueConnected: {
        color: colors.white,
    },
    statusValueDisconnected: {
        color: colors.red,
    },
    autoConnectToast: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: colors.surface,
        paddingVertical: spacing.sm,
        paddingHorizontal: spacing.md,
        borderRadius: radius.full,
        marginBottom: spacing.md,
        gap: spacing.sm,
    },
    autoConnectText: {
        color: colors.white,
        fontSize: fonts.sizes.sm,
    },
    assessmentCard: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: spacing.md,
        marginHorizontal: spacing.lg,
        marginBottom: spacing.md,
        padding: spacing.md,
        borderRadius: radius.xl,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
    },
    assessmentIcon: {
        width: 38,
        height: 38,
        borderRadius: 19,
        backgroundColor: colors.white,
        alignItems: 'center',
        justifyContent: 'center',
    },
    assessmentCopy: {
        flex: 1,
        gap: 2,
    },
    assessmentTitle: {
        color: colors.textPrimary,
        fontSize: fonts.sizes.sm,
        fontWeight: '700',
    },
    assessmentText: {
        color: colors.textSecondary,
        fontSize: fonts.sizes.xs,
        lineHeight: 18,
    },
    centerContent: {
        flex: 1,
        alignItems: 'center',
        justifyContent: 'center',
        gap: spacing.xl,
        paddingBottom: 20,
    },
    mainBtn: {
        width: 200,
        height: 200,
        borderRadius: 100,
        alignItems: 'center',
        justifyContent: 'center',
        shadowColor: "#FFF",
        shadowOffset: {
            width: 0,
            height: 0,
        },
        shadowOpacity: 0.15,
        shadowRadius: 20,
        elevation: 10,
        borderWidth: 1,
    },
    mainBtnConnected: {
        backgroundColor: colors.textPrimary,
        borderColor: 'rgba(255,255,255,0.5)',
    },
    mainBtnDisconnected: {
        backgroundColor: colors.bg,
        borderColor: colors.red,
        borderWidth: 2,
    },
    mainBtnActive: {
        opacity: 0.7,
    },
    disconnectedIcon: {
        alignItems: 'center',
        justifyContent: 'center',
    },
    crossLine: {
        position: 'absolute',
        width: 60,
        height: 3,
        backgroundColor: colors.red,
        transform: [{ rotate: '-45deg' }],
    },
    identifyingContent: {
        alignItems: 'center',
    },
    scanningText: {
        color: colors.bg,
        fontSize: fonts.sizes.xs,
        marginTop: spacing.xs,
        textAlign: 'center',
    },
    voiceBtn: {
        width: 64,
        height: 64,
        borderRadius: 32,
        backgroundColor: colors.surfaceLight,
        alignItems: 'center',
        justifyContent: 'center',
        borderWidth: 1,
        borderColor: colors.border,
    },
    insightCard: {
        position: 'absolute',
        bottom: 100,
        left: spacing.lg,
        right: spacing.lg,
        backgroundColor: colors.surface,
        borderRadius: radius.xl,
        padding: spacing.lg,
        borderWidth: 1,
        borderColor: colors.borderLight,
    },
    insightHeader: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: spacing.xs,
        marginBottom: spacing.xs,
    },
    insightLabel: {
        color: colors.white,
        fontSize: 10,
        fontWeight: '700',
        letterSpacing: 1,
    },
    insightTitle: {
        color: colors.white,
        fontSize: fonts.sizes.lg,
        fontWeight: '600',
        marginBottom: spacing.xs,
    },
    insightDesc: {
        color: colors.textSecondary,
        fontSize: fonts.sizes.sm,
        lineHeight: 20,
        marginBottom: spacing.md,
    },
    encouragementMeta: {
        color: colors.textMuted,
        fontSize: fonts.sizes.xs,
        marginTop: -8,
        marginBottom: spacing.md,
    },
    insightBtn: {
        backgroundColor: 'rgba(255,255,255,0.1)',
        paddingVertical: spacing.xs,
        paddingHorizontal: spacing.md,
        borderRadius: radius.full,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        gap: spacing.xs,
    },
    insightBtnPrimary: {
        backgroundColor: colors.white,
        paddingVertical: spacing.xs,
        paddingHorizontal: spacing.md,
        borderRadius: radius.full,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        gap: spacing.xs,
    },
    insightBtnText: {
        color: colors.white,
        fontSize: fonts.sizes.sm,
        fontWeight: '500',
    },
    actionButtons: {
        flexDirection: 'row',
        gap: spacing.sm,
        marginTop: spacing.xs,
    },
    priorityBadge: {
        width: 18,
        height: 18,
        borderRadius: 9,
        backgroundColor: colors.red,
        alignItems: 'center',
        justifyContent: 'center',
        marginLeft: 'auto',
    },
    priorityText: {
        color: colors.white,
        fontSize: 12,
        fontWeight: '700',
    },
    modalOverlay: {
        flex: 1,
        backgroundColor: 'rgba(0,0,0,0.8)',
        justifyContent: 'center',
        alignItems: 'center',
    },
    modalContent: {
        backgroundColor: colors.surface,
        borderRadius: radius.xl,
        padding: spacing.xl,
        alignItems: 'center',
        width: '85%',
        maxWidth: 320,
        borderWidth: 1,
        borderColor: colors.border,
    },
    modalTitle: {
        color: colors.white,
        fontSize: fonts.sizes.lg,
        fontWeight: '600',
        marginTop: spacing.md,
        textAlign: 'center',
    },
    modalMessage: {
        color: colors.textSecondary,
        fontSize: fonts.sizes.sm,
        marginTop: spacing.sm,
        textAlign: 'center',
        lineHeight: 20,
    },
    modalConnectBtn: {
        backgroundColor: colors.white,
        paddingVertical: spacing.md,
        paddingHorizontal: spacing.xl,
        borderRadius: radius.full,
        marginTop: spacing.lg,
        width: '100%',
        alignItems: 'center',
        justifyContent: 'center',
        flexDirection: 'row',
        gap: spacing.xs,
    },
    modalConnectBtnText: {
        color: colors.bg,
        fontSize: fonts.sizes.md,
        fontWeight: '600',
    },
    modalCancelBtn: {
        paddingVertical: spacing.md,
        paddingHorizontal: spacing.xl,
        marginTop: spacing.sm,
        width: '100%',
        alignItems: 'center',
        justifyContent: 'center',
        flexDirection: 'row',
        gap: spacing.xs,
    },
    modalCancelBtnText: {
        color: colors.textSecondary,
        fontSize: fonts.sizes.md,
    },
    skipLink: {
        marginTop: spacing.sm,
        flexDirection: 'row',
        alignItems: 'center',
        gap: spacing.xs,
    },
    skipLinkText: {
        color: colors.textMuted,
        fontSize: fonts.sizes.sm,
    },
    settingsModalOverlay: {
        flex: 1,
        backgroundColor: 'rgba(0,0,0,0.9)',
        justifyContent: 'flex-end',
    },
    settingsModalContent: {
        backgroundColor: colors.bg,
        borderTopLeftRadius: radius.xl,
        borderTopRightRadius: radius.xl,
        maxHeight: '85%',
        borderWidth: 1,
        borderColor: colors.border,
        borderBottomWidth: 0,
    },
    settingsHeader: {
        alignItems: 'center',
        paddingVertical: spacing.lg,
        borderBottomWidth: 1,
        borderBottomColor: colors.border,
    },
    settingsTitle: {
        color: colors.white,
        fontSize: fonts.sizes.xl,
        fontWeight: '600',
    },
    connectionInfo: {
        flexDirection: 'row',
        alignItems: 'center',
        marginTop: spacing.xs,
    },
    connectedText: {
        color: colors.white,
        fontSize: fonts.sizes.sm,
        marginLeft: spacing.xs,
    },
    moduleAddress: {
        color: colors.textMuted,
        fontSize: fonts.sizes.xs,
        marginTop: spacing.xs,
    },
    settingsScroll: {
        paddingHorizontal: spacing.lg,
    },
    statsSection: {
        paddingVertical: spacing.lg,
    },
    sectionTitle: {
        color: colors.textSecondary,
        fontSize: fonts.sizes.sm,
        fontWeight: '600',
        letterSpacing: 0.5,
        marginBottom: spacing.md,
    },
    statsGrid: {
        flexDirection: 'row',
        gap: spacing.sm,
    },
    statCard: {
        flex: 1,
        backgroundColor: colors.surface,
        borderRadius: radius.lg,
        padding: spacing.md,
        alignItems: 'center',
        borderWidth: 1,
        borderColor: colors.border,
    },
    statNumber: {
        color: colors.white,
        fontSize: fonts.sizes.xl,
        fontWeight: '700',
        marginTop: spacing.xs,
    },
    statLabel: {
        color: colors.textSecondary,
        fontSize: fonts.sizes.xs,
        marginTop: spacing.xs,
        textAlign: 'center',
    },
    settingsSection: {
        paddingVertical: spacing.lg,
        borderTopWidth: 1,
        borderTopColor: colors.border,
    },
    settingRow: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        paddingVertical: spacing.md,
        borderBottomWidth: 1,
        borderBottomColor: colors.border,
    },
    settingInfo: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: spacing.sm,
    },
    settingLabel: {
        color: colors.white,
        fontSize: fonts.sizes.md,
    },
    cameraPreviewBtn: {
        flexDirection: 'row',
        alignItems: 'center',
        paddingVertical: spacing.md,
        gap: spacing.sm,
    },
    cameraPreviewText: {
        color: colors.white,
        fontSize: fonts.sizes.md,
        flex: 1,
    },
    actionsSection: {
        paddingVertical: spacing.lg,
        borderTopWidth: 1,
        borderTopColor: colors.border,
        gap: spacing.sm,
    },
    identifyBtn: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: colors.white,
        paddingVertical: spacing.md,
        borderRadius: radius.full,
        gap: spacing.sm,
    },
    identifyBtnText: {
        color: colors.bg,
        fontSize: fonts.sizes.md,
        fontWeight: '600',
    },
    disconnectBtn: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: colors.redLight,
        paddingVertical: spacing.md,
        borderRadius: radius.full,
        gap: spacing.sm,
        borderWidth: 1,
        borderColor: colors.red,
    },
    disconnectBtnText: {
        color: colors.red,
        fontSize: fonts.sizes.md,
        fontWeight: '500',
    },
    closeBtn: {
        paddingVertical: spacing.lg,
        alignItems: 'center',
        justifyContent: 'center',
        flexDirection: 'row',
        gap: spacing.xs,
        borderTopWidth: 1,
        borderTopColor: colors.border,
    },
    closeBtnText: {
        color: colors.textSecondary,
        fontSize: fonts.sizes.md,
    },
    stepCard: {
        marginTop: spacing.md,
        marginHorizontal: spacing.lg,
    },
    stepHeader: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: spacing.xs,
        marginBottom: spacing.sm,
    },
    stepLabel: {
        color: colors.textSecondary,
        fontSize: fonts.sizes.xs,
        fontWeight: '600',
        letterSpacing: 1,
    },
    stepContent: {
        flexDirection: 'row',
        alignItems: 'baseline',
        gap: spacing.xs,
        marginBottom: spacing.sm,
    },
    stepCount: {
        color: colors.white,
        fontSize: fonts.sizes.hero,
        fontWeight: '700',
    },
    stepGoal: {
        color: colors.textSecondary,
        fontSize: fonts.sizes.md,
    },
    stepProgress: {
        height: 8,
        backgroundColor: colors.surface,
        borderRadius: radius.full,
        overflow: 'hidden',
        marginBottom: spacing.xs,
    },
    stepProgressBar: {
        height: '100%',
        backgroundColor: colors.white,
        borderRadius: radius.full,
    },
    stepPercent: {
        color: colors.textMuted,
        fontSize: fonts.sizes.xs,
        textAlign: 'right',
    },
});
