import React, { useState } from 'react';
import { View, Text, StyleSheet, Pressable, ScrollView, Platform, KeyboardAvoidingView, TextInput, ActivityIndicator, Alert } from 'react-native';
import { useRouter } from 'expo-router';
import api from '../../src/services/api';
import Screen from '../../src/components/Screen';
import { colors, fonts, spacing, radius } from '../../src/theme';
import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';

const TIME_OPTIONS = [
  { key: 'morning', label: 'Morning', desc: 'Best before noon', icon: 'sunny-outline' },
  { key: 'daytime', label: 'All day', desc: 'Steady throughout', icon: 'partly-sunny-outline' },
  { key: 'evening', label: 'Evening', desc: 'Wind down time', icon: 'moon-outline' },
];

//------This Function handles the Patient Onboarding Routine Screen---------
export default function PatientOnboardingRoutineScreen() {
  const router = useRouter();
  const [timePreference, setTimePreference] = useState('');
  const [favoriteFood, setFavoriteFood] = useState('');
  const [dailyRoutine, setDailyRoutine] = useState('');
  const [dietaryNotes, setDietaryNotes] = useState('');
  const [wellnessHabits, setWellnessHabits] = useState('');
  const [saving, setSaving] = useState(false);

  //------This Function handles the Handle Next---------
  async function handleNext() {
    setSaving(true);
    try {
      const comfortsRaw = await AsyncStorage.getItem('onboarding_patient_comforts');
      const preferredName = await AsyncStorage.getItem('onboarding_patient_name');
      const people = await AsyncStorage.getItem('onboarding_patient_people');
      const healthNotes = await AsyncStorage.getItem('onboarding_patient_health_notes');
      const comforts = comfortsRaw ? JSON.parse(comfortsRaw) : [];

      const preferences = {
        hobbies: comforts,
        important_people: people || '',
        daily_routine: dailyRoutine,
        time_preference: timePreference,
        favorite_food: favoriteFood,
        communication_style: preferredName || '',
        health_notes: healthNotes || '',
        dietary_notes: dietaryNotes,
        wellness_habits: wellnessHabits,
      };

      // Store permanently for agentic bot context
      await AsyncStorage.setItem('patient_preferences', JSON.stringify(preferences));
      await api.put('/onboarding/preferences', preferences);

      await AsyncStorage.removeItem('onboarding_patient_comforts');
      await AsyncStorage.removeItem('onboarding_patient_name');
      await AsyncStorage.removeItem('onboarding_patient_people');
      await AsyncStorage.removeItem('onboarding_patient_health_notes');

      router.push('/(onboarding)/headphones');
    } catch (error: any) {
      const message = error?.response?.data?.detail || 'Unable to save your preferences right now.';
      Alert.alert('Save Failed', message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Screen>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} style={s.flex}>
        <ScrollView contentContainerStyle={s.content} showsVerticalScrollIndicator={false}>

          <View style={s.progressWrap}>
            <View style={s.progressBar}>
              <View style={[s.progressFill, { width: '50%' }]} />
            </View>
            <Text style={s.progressLabel}>2 of 4</Text>
          </View>

          <View style={s.headerBlock}>
            <Text style={s.greeting}>Almost there ✨</Text>
            <Text style={s.title}>Your everyday life</Text>
            <Text style={s.subtitle}>A few more things so Orito fits naturally into your day.</Text>
          </View>

          <View style={s.section}>
            <View style={s.sectionHeader}>
              <Ionicons name="time-outline" size={20} color={colors.textMuted} />
              <Text style={s.sectionTitle}>When do you feel most yourself?</Text>
            </View>
            <View style={s.timeGrid}>
              {TIME_OPTIONS.map((opt) => {
                const active = timePreference === opt.key;
                return (
                  <Pressable
                    key={opt.key}
                    style={({ pressed }) => [s.timeCard, active && s.timeCardActive, pressed && s.timeCardPressed]}
                    onPress={() => setTimePreference(opt.key)}
                  >
                    <Ionicons name={opt.icon as any} size={22} color={active ? colors.bg : colors.textSecondary} />
                    <Text style={[s.timeLabel, active && s.timeLabelActive]}>{opt.label}</Text>
                    <Text style={[s.timeDesc, active && s.timeDescActive]}>{opt.desc}</Text>
                    {active && (
                      <View style={s.checkBadge}>
                        <Ionicons name="checkmark" size={11} color={colors.white} />
                      </View>
                    )}
                  </Pressable>
                );
              })}
            </View>
          </View>

          <View style={s.section}>
            <View style={s.sectionHeader}>
              <Ionicons name="restaurant-outline" size={20} color={colors.textMuted} />
              <Text style={s.sectionTitle}>Food & eating</Text>
            </View>
            <TextInput
              style={s.input}
              value={favoriteFood}
              onChangeText={setFavoriteFood}
              placeholder="Comfort foods you love..."
              placeholderTextColor={colors.textMuted}
            />
            <TextInput
              style={[s.input, s.textArea]}
              value={dietaryNotes}
              onChangeText={setDietaryNotes}
              placeholder="Anything your body doesn't agree with..."
              placeholderTextColor={colors.textMuted}
              multiline
              numberOfLines={2}
              textAlignVertical="top"
            />
          </View>

          <View style={s.section}>
            <View style={s.sectionHeader}>
              <Ionicons name="leaf-outline" size={20} color={colors.textMuted} />
              <Text style={s.sectionTitle}>Your wellness habits</Text>
            </View>
            <Text style={s.hint}>Optional — vitamins, supplements, morning routines, anything regular</Text>
            <TextInput
              style={[s.input, s.textArea]}
              value={wellnessHabits}
              onChangeText={setWellnessHabits}
              placeholder="e.g. Morning vitamin D, evening walk, herbal tea before bed..."
              placeholderTextColor={colors.textMuted}
              multiline
              numberOfLines={3}
              textAlignVertical="top"
            />
          </View>

          <View style={s.section}>
            <View style={s.sectionHeader}>
              <Ionicons name="calendar-outline" size={20} color={colors.textMuted} />
              <Text style={s.sectionTitle}>What does a good day look like?</Text>
            </View>
            <TextInput
              style={[s.input, s.textArea]}
              value={dailyRoutine}
              onChangeText={setDailyRoutine}
              placeholder="Tea at 7, walk at 8, rest after lunch, call family at 6..."
              placeholderTextColor={colors.textMuted}
              multiline
              numberOfLines={3}
              textAlignVertical="top"
            />
          </View>

          <Pressable
            style={({ pressed }) => [s.primaryBtn, saving && s.primaryBtnDisabled, pressed && !saving && s.primaryBtnPressed]}
            onPress={handleNext}
            disabled={saving}
          >
            {saving ? (
              <ActivityIndicator color={colors.bg} size="small" />
            ) : (
              <>
                <Text style={s.primaryBtnText}>Continue</Text>
                <Ionicons name="arrow-forward" size={18} color={colors.bg} />
              </>
            )}
          </Pressable>

        </ScrollView>
      </KeyboardAvoidingView>
    </Screen>
  );
}

const s = StyleSheet.create({
  flex: { flex: 1 },
  content: {
    flexGrow: 1,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: spacing.xxl,
    gap: spacing.md,
  },
  progressWrap: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    marginBottom: spacing.xs,
  },
  progressBar: {
    flex: 1,
    height: 3,
    backgroundColor: colors.bgTertiary,
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
    letterSpacing: 0.5,
  },
  headerBlock: {
    gap: spacing.xs,
    marginBottom: spacing.xs,
  },
  greeting: {
    color: colors.textSecondary,
    fontSize: fonts.sizes.sm,
    fontWeight: '600',
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
  section: {
    backgroundColor: colors.surface,
    borderRadius: radius.xl,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  sectionTitle: {
    color: colors.textPrimary,
    fontSize: fonts.sizes.md,
    fontWeight: '700',
    flex: 1,
  },
  hint: {
    color: colors.textMuted,
    fontSize: fonts.sizes.xs,
    lineHeight: 16,
  },
  input: {
    backgroundColor: colors.bgTertiary,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: spacing.md,
    paddingVertical: 13,
    color: colors.textPrimary,
    fontSize: fonts.sizes.md,
  },
  textArea: {
    minHeight: 72,
    textAlignVertical: 'top',
    paddingTop: 13,
  },
  timeGrid: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  timeCard: {
    flex: 1,
    alignItems: 'center',
    gap: 5,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.sm,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.bgTertiary,
    position: 'relative',
  },
  timeCardActive: {
    borderColor: colors.white,
    backgroundColor: colors.white,
  },
  timeCardPressed: {
    opacity: 0.75,
  },
  timeLabel: {
    color: colors.textPrimary,
    fontSize: 11,
    fontWeight: '700',
    textAlign: 'center',
  },
  timeLabelActive: {
    color: colors.bg,
  },
  timeDesc: {
    color: colors.textMuted,
    fontSize: 10,
    textAlign: 'center',
  },
  timeDescActive: {
    color: colors.bgTertiary,
  },
  checkBadge: {
    position: 'absolute',
    top: 6,
    right: 6,
    width: 16,
    height: 16,
    borderRadius: 8,
    backgroundColor: colors.bg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  primaryBtn: {
    marginTop: spacing.sm,
    height: 56,
    borderRadius: radius.full,
    backgroundColor: colors.white,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
  },
  primaryBtnDisabled: {
    opacity: 0.6,
  },
  primaryBtnPressed: {
    opacity: 0.85,
  },
  primaryBtnText: {
    color: colors.bg,
    fontSize: fonts.sizes.md,
    fontWeight: '700',
  },
});
