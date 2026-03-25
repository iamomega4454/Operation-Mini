import React, { useEffect, useState, useCallback } from 'react';
import {
    View, Text, StyleSheet, ScrollView, TouchableOpacity,
    Alert, RefreshControl, Linking, Modal, TextInput, ActivityIndicator,
} from 'react-native';
import { useRouter } from 'expo-router';
import api from '../../src/services/api';
import AsyncStorage from '@react-native-async-storage/async-storage';
import ConnectionIndicator from '../../src/components/ConnectionIndicator';
import { colors, fonts, spacing, radius } from '../../src/theme';
import { Ionicons } from '@expo/vector-icons';
import { getTodaySteps, getStepHistory } from '../../src/services/pedometer';

interface DailyReport { date: string; steps: number; medicationsTaken: number; medicationsTotal: number; conversations: number; journalEntries: number; suggestionsAccepted: number; suggestionsDismissed: number; }
interface EmotionData { emotion: string; count: number; percentage: number; }
interface EmotionTrend { trend: 'improving' | 'stable' | 'declining'; change: number; }
interface TimelineEvent { time: string; type: 'medication' | 'sos' | 'journal' | 'conversation' | 'activity'; description: string; }
interface ActivityPeriod { period: string; steps: number; events: TimelineEvent[]; }
interface WeeklyComparison { stepsChange: number; medicationAdherenceChange: number; socialInteractionsChange: number; thisWeek: { steps: number; medicationAdherence: number; socialInteractions: number; }; lastWeek: { steps: number; medicationAdherence: number; socialInteractions: number; }; }
interface BehaviorAlert { id: string; type: 'missed_medication' | 'no_activity' | 'sos' | 'unusual'; message: string; time: string; reviewed: boolean; }
interface ReportSettings { notificationsEnabled: boolean; quietHoursStart: string; quietHoursEnd: string; }

//------This Function handles the Reports Screen---------
export default function ReportsScreen() {
    const router = useRouter();
    const [refreshing, setRefreshing] = useState(false);
    const [selectedDate, setSelectedDate] = useState(new Date());
    const [dailyReport, setDailyReport] = useState<DailyReport | null>(null);
    const [emotions, setEmotions] = useState<EmotionData[]>([]);
    const [emotionTrend, setEmotionTrend] = useState<EmotionTrend>({ trend: 'stable', change: 0 });
    const [timeline, setTimeline] = useState<ActivityPeriod[]>([]);
    const [weeklyComparison, setWeeklyComparison] = useState<WeeklyComparison | null>(null);
    const [alerts, setAlerts] = useState<BehaviorAlert[]>([]);
    const [settings, setSettings] = useState<ReportSettings>({ notificationsEnabled: true, quietHoursStart: '22:00', quietHoursEnd: '07:00' });
    const [showEncouragementModal, setShowEncouragementModal] = useState(false);
    const [encouragementMessage, setEncouragementMessage] = useState('');
    const [patientPhone, setPatientPhone] = useState<string>('');
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [patientUid, setPatientUid] = useState<string | null>(null);
    const [sendingEncouragement, setSendingEncouragement] = useState(false);
    const [schedulingCheckin, setSchedulingCheckin] = useState(false);

    useEffect(() => { loadPatientUid(); }, []);
    useEffect(() => { if (patientUid !== null) { loadData(); loadSettings(); } }, [selectedDate, patientUid]);

    //------This Function handles the Load Patient Uid---------
    async function loadPatientUid() {
        try {
            const meRes = await api.get('/auth/me');
            const userData = meRes.data;
            if (userData.role === 'caregiver' && userData.linked_patients?.length > 0) { setPatientUid(userData.linked_patients[0]); }
            else if (userData.role === 'patient') { setPatientUid(userData.firebase_uid); }
            else { setPatientUid(null); }
        } catch { setPatientUid(null); }
    }

    //------This Function handles the Load Data---------
    async function loadData() {
        setLoading(true); setError(null);
        try {
            const dateStr = formatDate(selectedDate);
            const params = buildPatientQuery({ date: dateStr });
            const [dailyRes, emotionsRes, timelineRes, weeklyRes, alertsRes] = await Promise.all([
                api.get(`/reports/daily${params}`).catch(() => null),
                api.get(`/reports/emotions${buildPatientQuery()}`).catch(() => null),
                api.get(`/reports/timeline${params}`).catch(() => null),
                api.get(`/reports/weekly${buildPatientQuery()}`).catch(() => null),
                api.get(`/reports/alerts${buildPatientQuery()}`).catch(() => null),
            ]);
            if (dailyRes?.data) {
                let steps = 0;
                if (dateStr === new Date().toISOString().split('T')[0]) { try { steps = await getTodaySteps(); } catch { steps = 0; } }
                setDailyReport({ ...dailyRes.data, steps });
            } else { setDailyReport(null); }
            if (emotionsRes?.data) { setEmotions(emotionsRes.data.emotions || []); setEmotionTrend(emotionsRes.data.trend || { trend: 'stable', change: 0 }); }
            else { setEmotions([]); setEmotionTrend({ trend: 'stable', change: 0 }); }
            if (timelineRes?.data) { setTimeline(timelineRes.data.periods || []); } else { setTimeline([]); }
            if (weeklyRes?.data) {
                try { const stepHistory = await getStepHistory(7); const thisWeekSteps = Object.values(stepHistory).reduce((a: number, b: number) => a + b, 0) as number; setWeeklyComparison({ ...weeklyRes.data, thisWeek: { ...weeklyRes.data.thisWeek, steps: thisWeekSteps } }); }
                catch { setWeeklyComparison(weeklyRes.data); }
            } else { setWeeklyComparison(null); }
            if (alertsRes?.data) { setAlerts(alertsRes.data.alerts || []); } else { setAlerts([]); }
            try {
                const meRes = await api.get('/auth/me');
                const lp = Array.isArray(meRes.data.linked_patients) ? meRes.data.linked_patients : [];
                const firstLinkedPatient = lp[0];
                if (firstLinkedPatient && typeof firstLinkedPatient === 'object' && 'phone' in firstLinkedPatient) {
                    setPatientPhone((firstLinkedPatient as { phone?: string }).phone || '');
                } else {
                    setPatientPhone('');
                }
            } catch {
                setPatientPhone('');
            }
        } catch { setError('Failed to load report data.'); } finally { setLoading(false); }
    }

    //------This Function handles the Load Settings---------
    async function loadSettings() { try { const stored = await AsyncStorage.getItem('caregiver_report_settings'); if (stored) setSettings(JSON.parse(stored)); } catch { } }

    //------This Function handles the On Refresh---------
    const onRefresh = useCallback(async () => { setRefreshing(true); await loadData(); setRefreshing(false); }, [selectedDate]);

    //------This Function handles the Format Date---------
    function formatDate(d: Date): string { return d.toISOString().split('T')[0]; }

    //------This Function handles the Format Display Date---------
    function formatDisplayDate(d: Date): string { return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' }); }

    //------This Function handles the Change Date---------
    function changeDate(days: number) { const nd = new Date(selectedDate); nd.setDate(nd.getDate() + days); if (nd <= new Date()) setSelectedDate(nd); }

    //------This Function handles the Mark Alert Reviewed---------
    function markAlertReviewed(id: string) { setAlerts(p => p.map(a => a.id === id ? { ...a, reviewed: true } : a)); }

    //------This Function handles the Handle Call Patient---------
    function handleCallPatient() { if (patientPhone) Linking.openURL(`tel:${patientPhone}`); else Alert.alert('No Phone Number', 'Patient phone number is not available.'); }

    //------This Function handles the Handle Send Encouragement---------
    async function handleSendEncouragement() {
        if (!encouragementMessage.trim()) { Alert.alert('Empty Message', 'Please enter a message.'); return; }
        if (!patientUid) { Alert.alert('No Patient Linked', 'Link a patient account first.'); return; }
        try {
            setSendingEncouragement(true);
            await api.post('/reports/encouragement', {
                patient_uid: patientUid,
                message: encouragementMessage.trim(),
            });
            setShowEncouragementModal(false);
            setEncouragementMessage('');
            Alert.alert('Sent', 'Your encouragement was delivered to the patient.');
        } catch (error: any) {
            const message = error?.response?.data?.detail || 'Failed to send encouragement';
            Alert.alert('Error', message);
        } finally {
            setSendingEncouragement(false);
        }
    }

    //------This Function handles the Create Checkin Reminder---------
    async function createCheckinReminder(hoursFromNow: number) {
        if (!patientUid) { Alert.alert('No Patient Linked', 'Link a patient account first.'); return; }
        try {
            setSchedulingCheckin(true);
            const when = new Date();
            when.setHours(when.getHours() + hoursFromNow);
            await api.post(`/reminders/?patient_uid=${encodeURIComponent(patientUid)}`, {
                title: 'Caregiver Check-in',
                description: 'Scheduled check-in from caregiver reports',
                datetime: when.toISOString(),
                created_by: 'caregiver',
                source: 'manual',
            });
            Alert.alert('Scheduled', `Check-in reminder set for ${when.toLocaleString()}`);
        } catch (error: any) {
            const message = error?.response?.data?.detail || 'Failed to schedule check-in';
            Alert.alert('Error', message);
        } finally {
            setSchedulingCheckin(false);
        }
    }

    //------This Function handles the Handle Schedule Checkin---------
    function handleScheduleCheckin() {
        Alert.alert('Schedule Check-in', 'Set a reminder?', [
            { text: 'Cancel', style: 'cancel' },
            { text: '1 Hour', onPress: () => createCheckinReminder(1) },
            { text: '3 Hours', onPress: () => createCheckinReminder(3) },
            { text: 'Tomorrow', onPress: () => createCheckinReminder(24) },
        ]);
    }

    //------This Function handles the Get Trend Icon---------
    function getTrendIcon(t: string) { return t === 'improving' ? 'trending-up' : t === 'declining' ? 'trending-down' : 'remove'; }

    //------This Function handles the Get Trend Color---------
    function getTrendColor(t: string) { return t === 'improving' ? colors.success : t === 'declining' ? colors.red : colors.textSecondary; }

    //------This Function handles the Get Alert Icon---------
    function getAlertIcon(t: string) { switch (t) { case 'missed_medication': return 'medical'; case 'no_activity': return 'walk'; case 'sos': return 'alert'; default: return 'warning'; } }

    //------This Function handles the Build Patient Query---------
    function buildPatientQuery(extra: { date?: string } = {}) {
        const params = new URLSearchParams();
        if (extra.date) params.set('date', extra.date);
        if (patientUid) params.set('patient_uid', patientUid);
        const query = params.toString();
        return query ? `?${query}` : '';
    }

    const unreviewedAlerts = alerts.filter(a => !a.reviewed);

    return (
        <View style={s.container}>
            <View style={s.header}>
                <TouchableOpacity onPress={() => router.back()} style={s.backBtn} activeOpacity={0.7}>
                    <Ionicons name="arrow-back" size={20} color={colors.textPrimary} />
                </TouchableOpacity>
                <Text style={s.title}>Activity Reports</Text>
                <ConnectionIndicator />
            </View>

            <ScrollView style={s.scrollView} contentContainerStyle={s.scrollContent} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.white} />}>
                <View style={s.datePicker}>
                    <TouchableOpacity onPress={() => changeDate(-1)} style={s.dateArrow} activeOpacity={0.7}>
                        <Ionicons name="chevron-back" size={20} color={colors.textPrimary} />
                    </TouchableOpacity>
                    <Text style={s.dateText}>{formatDisplayDate(selectedDate)}</Text>
                    <TouchableOpacity onPress={() => changeDate(1)} style={s.dateArrow} disabled={formatDate(selectedDate) === formatDate(new Date())} activeOpacity={0.7}>
                        <Ionicons name="chevron-forward" size={20} color={formatDate(selectedDate) === formatDate(new Date()) ? colors.textMuted : colors.textPrimary} />
                    </TouchableOpacity>
                </View>

                {!patientUid && (
                    <View style={s.linkPatientCard}>
                        <Ionicons name="link-outline" size={22} color={colors.textSecondary} />
                        <Text style={s.linkPatientTitle}>No linked patient account</Text>
                        <Text style={s.linkPatientSub}>Link a patient to unlock reports and caregiver actions.</Text>
                    </View>
                )}

                {dailyReport && (
                    <View style={s.section}>
                        <Text style={s.sectionLabel}>DAILY SUMMARY</Text>
                        <View style={s.statsGrid}>
                            {[
                                { icon: 'footsteps', value: dailyReport.steps.toLocaleString(), label: 'Steps' },
                                { icon: 'medical', value: `${dailyReport.medicationsTaken}/${dailyReport.medicationsTotal}`, label: 'Meds Taken' },
                                { icon: 'chatbubbles', value: String(dailyReport.conversations), label: 'Conversations' },
                                { icon: 'book', value: String(dailyReport.journalEntries), label: 'Journal' },
                            ].map((stat, i) => (
                                <View key={i} style={s.statCard}>
                                    <Ionicons name={stat.icon as any} size={20} color={colors.textSecondary} />
                                    <Text style={s.statValue}>{stat.value}</Text>
                                    <Text style={s.statLabel}>{stat.label}</Text>
                                </View>
                            ))}
                        </View>
                    </View>
                )}

                <View style={s.section}>
                    <View style={s.sectionHeader}>
                        <Text style={s.sectionLabel}>MOOD & EMOTIONS</Text>
                        <View style={[s.trendBadge, { backgroundColor: getTrendColor(emotionTrend.trend) + '15' }]}>
                            <Ionicons name={getTrendIcon(emotionTrend.trend) as any} size={12} color={getTrendColor(emotionTrend.trend)} />
                            <Text style={[s.trendText, { color: getTrendColor(emotionTrend.trend) }]}>{emotionTrend.trend}</Text>
                        </View>
                    </View>
                    {emotions.map((em) => (
                        <View key={em.emotion} style={s.emotionRow}>
                            <Text style={s.emotionName}>{em.emotion}</Text>
                            <View style={s.emotionBarBg}>
                                <View style={[s.emotionBar, { width: `${em.percentage}%` }]} />
                            </View>
                            <Text style={s.emotionCount}>{em.count}</Text>
                        </View>
                    ))}
                </View>

                <View style={s.section}>
                    <Text style={s.sectionLabel}>ACTIVITY TIMELINE</Text>
                    {timeline.map((period, idx) => (
                        <View key={idx} style={s.timelinePeriod}>
                            <View style={s.periodHeader}>
                                <Text style={s.periodTitle}>{period.period}</Text>
                                <Text style={s.periodSteps}>{period.steps.toLocaleString()} steps</Text>
                            </View>
                            {period.events.map((event, ei) => (
                                <View key={ei} style={s.timelineEvent}>
                                    <View style={s.eventDot} />
                                    <View style={s.eventContent}>
                                        <Text style={s.eventTime}>{event.time}</Text>
                                        <Text style={s.eventDesc}>{event.description}</Text>
                                    </View>
                                </View>
                            ))}
                            {period.events.length === 0 && <Text style={s.noEvents}>No events recorded</Text>}
                        </View>
                    ))}
                </View>

                {weeklyComparison && (
                    <View style={s.section}>
                        <Text style={s.sectionLabel}>WEEKLY COMPARISON</Text>
                        <View style={s.compRow}>
                            {[
                                { label: 'Steps', value: weeklyComparison.thisWeek.steps.toLocaleString(), change: weeklyComparison.stepsChange },
                                { label: 'Med Adherence', value: `${weeklyComparison.thisWeek.medicationAdherence}%`, change: weeklyComparison.medicationAdherenceChange },
                                { label: 'Social', value: String(weeklyComparison.thisWeek.socialInteractions), change: weeklyComparison.socialInteractionsChange },
                            ].map((c, i) => (
                                <View key={i} style={s.compCard}>
                                    <Text style={s.compLabel}>{c.label}</Text>
                                    <Text style={s.compValue}>{c.value}</Text>
                                    <View style={s.compChange}>
                                        <Ionicons name={c.change >= 0 ? 'arrow-up' : 'arrow-down'} size={10} color={c.change >= 0 ? colors.success : colors.red} />
                                        <Text style={[s.compChangeText, { color: c.change >= 0 ? colors.success : colors.red }]}>{Math.abs(c.change)}%</Text>
                                    </View>
                                </View>
                            ))}
                        </View>
                    </View>
                )}

                {unreviewedAlerts.length > 0 && (
                    <View style={s.section}>
                        <View style={s.sectionHeader}>
                            <Text style={s.sectionLabel}>ALERTS</Text>
                            <View style={s.alertBadge}><Text style={s.alertBadgeText}>{unreviewedAlerts.length}</Text></View>
                        </View>
                        {unreviewedAlerts.map((alert) => (
                            <View key={alert.id} style={s.alertCard}>
                                <View style={s.alertIcon}><Ionicons name={getAlertIcon(alert.type) as any} size={18} color={colors.red} /></View>
                                <View style={{ flex: 1 }}>
                                    <Text style={s.alertMsg}>{alert.message}</Text>
                                    <Text style={s.alertTime}>{new Date(alert.time).toLocaleTimeString()}</Text>
                                </View>
                                <TouchableOpacity style={s.reviewBtn} onPress={() => markAlertReviewed(alert.id)} activeOpacity={0.7}>
                                    <Ionicons name="checkmark" size={18} color={colors.success} />
                                </TouchableOpacity>
                            </View>
                        ))}
                    </View>
                )}

                <View style={s.section}>
                    <Text style={s.sectionLabel}>QUICK ACTIONS</Text>
                    {[
                        { icon: 'call', title: 'Call Patient', sub: 'Open phone dialer', fn: handleCallPatient },
                        { icon: 'heart', title: 'Send Encouragement', sub: 'Send a supportive message', fn: () => setShowEncouragementModal(true) },
                        { icon: 'calendar', title: 'Schedule Check-in', sub: 'Set a reminder', fn: handleScheduleCheckin },
                    ].map((action, i) => (
                        <TouchableOpacity key={i} style={[s.actionBtn, !patientUid && s.actionBtnDisabled]} onPress={action.fn} activeOpacity={0.7} disabled={!patientUid}>
                            <View style={s.actionIconWrap}><Ionicons name={action.icon as any} size={20} color={colors.textPrimary} /></View>
                            <View style={{ flex: 1 }}>
                                <Text style={s.actionTitle}>{action.title}</Text>
                                <Text style={s.actionSub}>{action.sub}</Text>
                            </View>
                            <Ionicons name="chevron-forward" size={16} color={colors.textMuted} />
                        </TouchableOpacity>
                    ))}
                </View>

                <View style={{ height: spacing.xxl }} />
            </ScrollView>

            <Modal visible={showEncouragementModal} transparent animationType="fade" onRequestClose={() => setShowEncouragementModal(false)}>
                <View style={s.modalOverlay}>
                    <View style={s.modalContent}>
                        <Text style={s.modalTitle}>Send Encouragement</Text>
                        <Text style={s.modalSub}>Send a supportive message to the patient</Text>
                        <TextInput style={s.msgInput} placeholder="Type your message..." placeholderTextColor={colors.textMuted} value={encouragementMessage} onChangeText={setEncouragementMessage} multiline maxLength={200} />
                        <Text style={s.charCount}>{encouragementMessage.length}/200</Text>
                        <View style={s.modalActions}>
                            <TouchableOpacity style={s.modalCancel} onPress={() => { setShowEncouragementModal(false); setEncouragementMessage(''); }} activeOpacity={0.7} disabled={sendingEncouragement}>
                                <Ionicons name="close-outline" size={16} color={colors.textPrimary} />
                                <Text style={s.modalCancelText}>Cancel</Text>
                            </TouchableOpacity>
                            <TouchableOpacity style={s.modalSend} onPress={handleSendEncouragement} activeOpacity={0.85} disabled={sendingEncouragement}>
                                {sendingEncouragement ? <ActivityIndicator size="small" color={colors.bg} /> : (
                                    <>
                                        <Ionicons name="send-outline" size={16} color={colors.bg} />
                                        <Text style={s.modalSendText}>Send</Text>
                                    </>
                                )}
                            </TouchableOpacity>
                        </View>
                    </View>
                </View>
            </Modal>
        </View>
    );
}

const s = StyleSheet.create({
    container: { flex: 1, backgroundColor: colors.bg },
    header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: spacing.xl, paddingTop: spacing.xxl, paddingBottom: spacing.md },
    backBtn: { width: 36, height: 36, borderRadius: 18, backgroundColor: colors.surface, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: colors.border },
    title: { color: colors.textPrimary, fontSize: fonts.sizes.lg, fontWeight: '600', letterSpacing: -0.3 },
    scrollView: { flex: 1 },
    scrollContent: { paddingHorizontal: spacing.xl },

    datePicker: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', paddingVertical: spacing.md, marginBottom: spacing.sm },
    dateArrow: { padding: spacing.sm },
    dateText: { color: colors.textPrimary, fontSize: fonts.sizes.md, fontWeight: '600', marginHorizontal: spacing.xl, letterSpacing: -0.2 },
    linkPatientCard: { backgroundColor: colors.surface, borderRadius: radius.xl, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, alignItems: 'center', gap: spacing.xs, marginBottom: spacing.xl },
    linkPatientTitle: { color: colors.textPrimary, fontSize: fonts.sizes.md, fontWeight: '600' },
    linkPatientSub: { color: colors.textSecondary, fontSize: fonts.sizes.sm, textAlign: 'center' },

    section: { marginBottom: spacing.xl },
    sectionHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: spacing.md },
    sectionLabel: { color: colors.textMuted, fontSize: 10, fontWeight: '600', letterSpacing: 1.5, marginBottom: spacing.md },

    statsGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
    statCard: { flex: 1, minWidth: '45%', backgroundColor: colors.surface, borderRadius: radius.xl, padding: spacing.md, alignItems: 'center', borderWidth: 1, borderColor: colors.border },
    statValue: { color: colors.textPrimary, fontSize: fonts.sizes.xl, fontWeight: '300', marginTop: spacing.xs, letterSpacing: -0.5 },
    statLabel: { color: colors.textSecondary, fontSize: fonts.sizes.xs, marginTop: 2 },

    trendBadge: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: spacing.sm, paddingVertical: 3, borderRadius: radius.full },
    trendText: { fontSize: 10, fontWeight: '600', textTransform: 'capitalize' },

    emotionRow: { flexDirection: 'row', alignItems: 'center', marginBottom: spacing.sm, gap: spacing.sm },
    emotionName: { color: colors.textSecondary, fontSize: fonts.sizes.xs, width: 56, textTransform: 'capitalize' },
    emotionBarBg: { flex: 1, height: 4, backgroundColor: colors.surface, borderRadius: 2 },
    emotionBar: { height: 4, backgroundColor: colors.textPrimary, borderRadius: 2 },
    emotionCount: { color: colors.textMuted, fontSize: fonts.sizes.xs, width: 24, textAlign: 'right' },

    timelinePeriod: { marginBottom: spacing.lg },
    periodHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: spacing.sm },
    periodTitle: { color: colors.textPrimary, fontSize: fonts.sizes.sm, fontWeight: '600' },
    periodSteps: { color: colors.textMuted, fontSize: fonts.sizes.xs },
    timelineEvent: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.md, marginBottom: spacing.sm, paddingLeft: spacing.sm },
    eventDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: colors.textMuted, marginTop: 6 },
    eventContent: { flex: 1 },
    eventTime: { color: colors.textMuted, fontSize: fonts.sizes.xs },
    eventDesc: { color: colors.textSecondary, fontSize: fonts.sizes.sm, marginTop: 2 },
    noEvents: { color: colors.textMuted, fontSize: fonts.sizes.sm, paddingLeft: spacing.lg },

    compRow: { flexDirection: 'row', gap: spacing.sm },
    compCard: { flex: 1, backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.md, borderWidth: 1, borderColor: colors.border },
    compLabel: { color: colors.textMuted, fontSize: 9, fontWeight: '600', letterSpacing: 0.5 },
    compValue: { color: colors.textPrimary, fontSize: fonts.sizes.lg, fontWeight: '300', marginTop: spacing.xs, letterSpacing: -0.3 },
    compChange: { flexDirection: 'row', alignItems: 'center', gap: 2, marginTop: spacing.xs },
    compChangeText: { fontSize: 10, fontWeight: '600' },

    alertBadge: { backgroundColor: colors.red, borderRadius: radius.full, width: 20, height: 20, alignItems: 'center', justifyContent: 'center' },
    alertBadgeText: { color: colors.white, fontSize: 10, fontWeight: '700' },
    alertCard: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, padding: spacing.md, backgroundColor: 'rgba(255,59,48,0.04)', borderRadius: radius.lg, borderWidth: 1, borderColor: 'rgba(255,59,48,0.15)', marginBottom: spacing.sm },
    alertIcon: { width: 36, height: 36, borderRadius: 10, backgroundColor: 'rgba(255,59,48,0.1)', alignItems: 'center', justifyContent: 'center' },
    alertMsg: { color: colors.textPrimary, fontSize: fonts.sizes.sm, fontWeight: '500' },
    alertTime: { color: colors.textMuted, fontSize: fonts.sizes.xs, marginTop: 2 },
    reviewBtn: { padding: spacing.sm },

    actionBtn: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, padding: spacing.md, backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm },
    actionBtnDisabled: { opacity: 0.45 },
    actionIconWrap: { width: 40, height: 40, borderRadius: 10, backgroundColor: colors.surfaceLight, alignItems: 'center', justifyContent: 'center' },
    actionTitle: { color: colors.textPrimary, fontSize: fonts.sizes.md, fontWeight: '600', letterSpacing: -0.2 },
    actionSub: { color: colors.textSecondary, fontSize: fonts.sizes.xs, marginTop: 2 },

    modalOverlay: { flex: 1, backgroundColor: 'rgba(0,0,0,0.7)', justifyContent: 'center', alignItems: 'center', padding: spacing.xl },
    modalContent: { backgroundColor: colors.surface, borderRadius: radius.xl, padding: spacing.xl, width: '100%', borderWidth: 1, borderColor: colors.border },
    modalTitle: { color: colors.textPrimary, fontSize: fonts.sizes.lg, fontWeight: '600', letterSpacing: -0.3 },
    modalSub: { color: colors.textSecondary, fontSize: fonts.sizes.sm, marginTop: spacing.xs, marginBottom: spacing.lg },
    msgInput: { backgroundColor: colors.bgTertiary, borderRadius: radius.md, padding: spacing.md, color: colors.textPrimary, fontSize: fonts.sizes.md, minHeight: 100, textAlignVertical: 'top', borderWidth: 1, borderColor: colors.border },
    charCount: { color: colors.textMuted, fontSize: fonts.sizes.xs, textAlign: 'right', marginTop: spacing.xs },
    modalActions: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.lg },
    modalCancel: { flex: 1, paddingVertical: 14, borderRadius: radius.full, alignItems: 'center', justifyContent: 'center', flexDirection: 'row', gap: spacing.xs, backgroundColor: colors.surfaceLight, borderWidth: 1, borderColor: colors.border },
    modalCancelText: { color: colors.textPrimary, fontSize: fonts.sizes.sm, fontWeight: '600' },
    modalSend: { flex: 1, paddingVertical: 14, borderRadius: radius.full, alignItems: 'center', justifyContent: 'center', flexDirection: 'row', gap: spacing.xs, backgroundColor: colors.white },
    modalSendText: { color: colors.bg, fontSize: fonts.sizes.sm, fontWeight: '600' },
});
