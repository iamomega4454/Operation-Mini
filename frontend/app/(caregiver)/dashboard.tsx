import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, RefreshControl, TouchableOpacity } from 'react-native';
import { useRouter } from 'expo-router';
import { useAuth } from '../../src/context/auth';
import { useAssessment } from '../../src/context/assessment';
import api from '../../src/services/api';
import ConnectionIndicator from '../../src/components/ConnectionIndicator';
import AuraCard from '../../src/components/AuraCard';
import { colors, fonts, spacing, radius } from '../../src/theme';
import { Ionicons } from '@expo/vector-icons';

//------This Function handles the Caregiver Dashboard---------
export default function CaregiverDashboard() {
    const router = useRouter();
    const { user, signOut } = useAuth();
    const { recommendedSurveys } = useAssessment();
    const [refreshing, setRefreshing] = useState(false);
    const [sosAlerts, setSosAlerts] = useState<any[]>([]);
    const [dailyStats, setDailyStats] = useState({ meds_taken: 0, total_meds: 0, conversations: 0 });
    const [locationInfo, setLocationInfo] = useState<{ location: any; displayName: string } | null>(null);
    const recommendedAssessment = recommendedSurveys.find((survey) => survey.survey_type === 'caregiver');

    useEffect(() => { load(); }, []);

    //------This Function handles the Load---------
    async function load() {
        try {
            const linkedPatients = user?.linked_patients;
            const patientUid = user?.role === 'caregiver' && linkedPatients?.length
                ? linkedPatients[0]
                : undefined;
            const query = patientUid ? `?patient_uid=${encodeURIComponent(patientUid)}` : '';
            const [alertsRes, statsRes, locationRes] = await Promise.all([
                api.get(`/sos/active${query}`).catch(() => ({ data: [] })),
                api.get(`/reports/daily-summary${query}`).catch(() => ({ data: { meds_taken: 0, total_meds: 0, conversations: 0 } })),
                patientUid
                    ? api.get(`/location/${patientUid}`).catch(() => ({ data: null }))
                    : Promise.resolve({ data: null }),
            ]);
            setSosAlerts(alertsRes.data || []);
            setDailyStats(statsRes.data || { meds_taken: 0, total_meds: 0, conversations: 0 });
            if (locationRes?.data?.location) {
                setLocationInfo({
                    location: locationRes.data.location,
                    displayName: locationRes.data.display_name || 'Patient',
                });
            } else {
                setLocationInfo(null);
            }
        } catch { }
    }

    //------This Function handles the On Refresh---------
    async function onRefresh() {
        setRefreshing(true);
        await load();
        setRefreshing(false);
    }

    return (
        <View style={s.container}>
            <View style={s.header}>
                <View>
                    <Text style={s.greeting}>Good {new Date().getHours() < 12 ? 'Morning' : new Date().getHours() < 18 ? 'Afternoon' : 'Evening'}</Text>
                    <Text style={s.name}>{user?.display_name || 'Caregiver'}</Text>
                </View>
                <View style={s.headerRight}>
                    <ConnectionIndicator />
                    <TouchableOpacity onPress={signOut} style={s.logoutBtn} activeOpacity={0.7}>
                        <Ionicons name="log-out-outline" size={20} color={colors.textMuted} />
                    </TouchableOpacity>
                </View>
            </View>

            <ScrollView
                style={s.scroll}
                contentContainerStyle={s.scrollContent}
                showsVerticalScrollIndicator={false}
                refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.white} />}
            >
                {sosAlerts.length > 0 && (
                    <View style={s.section}>
                        <Text style={s.sectionLabel}>ACTIVE ALERTS</Text>
                        {sosAlerts.map((alert: any, i: number) => (
                            <View key={i} style={s.sosCard}>
                                <View style={s.sosIcon}>
                                    <Ionicons name="alert-circle" size={20} color={colors.red} />
                                </View>
                                <View style={{ flex: 1 }}>
                                    <Text style={s.sosTitle}>SOS Alert</Text>
                                    <Text style={s.sosTime}>{new Date(alert.created_at).toLocaleString()}</Text>
                                </View>
                            </View>
                        ))}
                    </View>
                )}

                {recommendedAssessment && (
                    <View style={s.section}>
                        <Text style={s.sectionLabel}>ASSESSMENT</Text>
                        <TouchableOpacity
                            style={s.assessmentCard}
                            onPress={() => router.push('/(assessment)/caregiver' as any)}
                            activeOpacity={0.8}
                        >
                            <View style={s.assessmentIcon}>
                                <Ionicons name="analytics-outline" size={18} color={colors.bg} />
                            </View>
                            <View style={s.assessmentCopy}>
                                <Text style={s.assessmentTitle}>Improve Confidence</Text>
                                <Text style={s.assessmentSub}>Answer a short follow-up for {recommendedAssessment.patient_name}.</Text>
                            </View>
                            <Ionicons name="chevron-forward" size={16} color={colors.textMuted} />
                        </TouchableOpacity>
                    </View>
                )}

                <View style={s.section}>
                    <Text style={s.sectionLabel}>TODAY'S SUMMARY</Text>
                    <View style={s.summaryRow}>
                        <View style={s.summaryCard}>
                            <Text style={s.summaryValue}>{dailyStats.meds_taken}/{dailyStats.total_meds}</Text>
                            <Text style={s.summaryLabel}>Medications</Text>
                        </View>
                        <View style={s.summaryCard}>
                            <Text style={s.summaryValue}>{dailyStats.conversations}</Text>
                            <Text style={s.summaryLabel}>Conversations</Text>
                        </View>
                    </View>
                    <TouchableOpacity
                        style={s.locationStatusCard}
                        activeOpacity={0.8}
                        onPress={() => router.push('/(caregiver)/location')}
                    >
                        <View style={s.locationStatusLeft}>
                            <View style={s.locationStatusIcon}>
                                <Ionicons name="location" size={16} color={colors.bg} />
                            </View>
                            <View>
                                <Text style={s.locationStatusTitle}>Live Location</Text>
                                <Text style={s.locationStatusSub}>
                                    {locationInfo?.location
                                        ? `${locationInfo.displayName}: ${new Date(locationInfo.location.timestamp || Date.now()).toLocaleTimeString()}`
                                        : 'No recent location yet'}
                                </Text>
                            </View>
                        </View>
                        <Ionicons name="chevron-forward" size={16} color={colors.textMuted} />
                    </TouchableOpacity>
                </View>

                <View style={s.section}>
                    <Text style={s.sectionLabel}>QUICK ACTIONS</Text>
                    <AuraCard
                        title="Activity Reports"
                        subtitle="View patient activity & behavior reports"
                        icon={<Ionicons name="bar-chart" size={20} color={colors.textPrimary} />}
                        onPress={() => router.push('/(caregiver)/reports')}
                    />
                    <AuraCard
                        title="Live Location"
                        subtitle="View patient's current location"
                        icon={<Ionicons name="location" size={20} color={colors.textPrimary} />}
                        onPress={() => router.push('/(caregiver)/location')}
                    />
                    <AuraCard
                        title="Medications"
                        subtitle="Manage & monitor medications"
                        icon={<Ionicons name="medical" size={20} color={colors.textPrimary} />}
                        onPress={() => router.push('/(caregiver)/medications')}
                    />
                    <AuraCard
                        title="SOS History"
                        subtitle="View past emergency alerts"
                        icon={<Ionicons name="alert-circle" size={20} color={colors.red} />}
                        variant="danger"
                        onPress={() => router.push('/(caregiver)/alerts')}
                    />
                </View>

                <View style={{ height: spacing.xxl }} />
            </ScrollView>
        </View>
    );
}

const s = StyleSheet.create({
    container: {
        flex: 1,
        backgroundColor: colors.bg,
    },
    header: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'center',
        paddingHorizontal: spacing.xl,
        paddingTop: spacing.xxl,
        paddingBottom: spacing.md,
    },
    greeting: {
        color: colors.textMuted,
        fontSize: fonts.sizes.sm,
        letterSpacing: 0.3,
    },
    name: {
        color: colors.textPrimary,
        fontSize: fonts.sizes.xxl,
        fontWeight: '300',
        letterSpacing: -0.5,
        marginTop: 2,
    },
    headerRight: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: spacing.sm,
    },
    logoutBtn: {
        width: 36,
        height: 36,
        borderRadius: 18,
        backgroundColor: colors.surface,
        alignItems: 'center',
        justifyContent: 'center',
        borderWidth: 1,
        borderColor: colors.border,
    },
    scroll: {
        flex: 1,
    },
    scrollContent: {
        paddingHorizontal: spacing.xl,
    },
    section: {
        marginBottom: spacing.xl,
    },
    sectionLabel: {
        color: colors.textMuted,
        fontSize: 10,
        fontWeight: '600',
        letterSpacing: 1.5,
        marginBottom: spacing.md,
    },
    sosCard: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: spacing.md,
        padding: spacing.md,
        backgroundColor: 'rgba(255, 59, 48, 0.06)',
        borderRadius: radius.lg,
        borderWidth: 1,
        borderColor: 'rgba(255, 59, 48, 0.2)',
        marginBottom: spacing.sm,
    },
    sosIcon: {
        width: 40,
        height: 40,
        borderRadius: 10,
        backgroundColor: 'rgba(255, 59, 48, 0.1)',
        alignItems: 'center',
        justifyContent: 'center',
    },
    sosTitle: {
        color: colors.red,
        fontSize: fonts.sizes.md,
        fontWeight: '600',
    },
    sosTime: {
        color: 'rgba(255, 59, 48, 0.6)',
        fontSize: fonts.sizes.xs,
        marginTop: 2,
    },
    assessmentCard: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: spacing.md,
        padding: spacing.md,
        backgroundColor: colors.surface,
        borderRadius: radius.xl,
        borderWidth: 1,
        borderColor: colors.border,
    },
    assessmentIcon: {
        width: 40,
        height: 40,
        borderRadius: 20,
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
        fontSize: fonts.sizes.md,
        fontWeight: '700',
    },
    assessmentSub: {
        color: colors.textSecondary,
        fontSize: fonts.sizes.xs,
        lineHeight: 18,
    },
    summaryRow: {
        flexDirection: 'row',
        gap: spacing.sm,
    },
    summaryCard: {
        flex: 1,
        backgroundColor: colors.surface,
        borderRadius: radius.xl,
        padding: spacing.lg,
        borderWidth: 1,
        borderColor: colors.border,
    },
    summaryValue: {
        color: colors.textPrimary,
        fontSize: fonts.sizes.xxl,
        fontWeight: '300',
        letterSpacing: -0.5,
    },
    summaryLabel: {
        color: colors.textSecondary,
        fontSize: fonts.sizes.xs,
        marginTop: spacing.xs,
    },
    locationStatusCard: {
        marginTop: spacing.sm,
        backgroundColor: colors.surface,
        borderRadius: radius.xl,
        borderWidth: 1,
        borderColor: colors.border,
        padding: spacing.md,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
    },
    locationStatusLeft: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: spacing.sm,
        flex: 1,
    },
    locationStatusIcon: {
        width: 32,
        height: 32,
        borderRadius: 16,
        backgroundColor: colors.white,
        alignItems: 'center',
        justifyContent: 'center',
    },
    locationStatusTitle: {
        color: colors.textPrimary,
        fontSize: fonts.sizes.sm,
        fontWeight: '600',
    },
    locationStatusSub: {
        color: colors.textSecondary,
        fontSize: fonts.sizes.xs,
        marginTop: 2,
    },
});
