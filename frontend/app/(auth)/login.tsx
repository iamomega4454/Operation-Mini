import React, { useState, useEffect } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, ActivityIndicator, Alert, ScrollView } from 'react-native';
import { useRouter } from 'expo-router';

let GoogleSignin: any = null;
let firebaseAuth: any = null;

let googleSigninConfigured = false;

try {
    GoogleSignin = require('@react-native-google-signin/google-signin').GoogleSignin;
} catch (e) {
    console.log('GoogleSignin not available in Expo Go');
}

try {
    firebaseAuth = require('@react-native-firebase/auth').default;
} catch (e) {
    console.log('Firebase Auth not available in Expo Go');
}

import { useAuth } from '../../src/context/auth';
import AuraLogo from '../../src/components/AuraLogo';
import { colors, fonts, spacing, radius } from '../../src/theme';
import { Ionicons } from '@expo/vector-icons';


let _googleWebClientId: string | null = null;
//------This Function resolves the Google Web Client ID from google-services.json---------
function getGoogleWebClientId(): string {
    if (_googleWebClientId !== null) return _googleWebClientId;
    try {
        const googleServices = require('../google-services.json');
        const client = googleServices?.client?.[0];
        const oauthClients: any[] = Array.isArray(client?.oauth_client) ? client.oauth_client : [];
        const appInviteClients: any[] = Array.isArray(
            client?.services?.appinvite_service?.other_platform_oauth_client
        ) ? client.services.appinvite_service.other_platform_oauth_client : [];
        const webClient = [...oauthClients, ...appInviteClients].find(
            (e: any) => e?.client_type === 3 && typeof e?.client_id === 'string'
        );
        _googleWebClientId = typeof webClient?.client_id === 'string' ? webClient.client_id : '';
    } catch {
        _googleWebClientId = '';
    }
    return _googleWebClientId as string;
}


const DEV_ROLES = [
    { role: 'patient' as const, label: 'Patient', icon: 'person-outline' as const, name: 'Alex Rivera' },
    { role: 'caregiver' as const, label: 'Caregiver', icon: 'heart-outline' as const, name: 'Dr. Sarah Chen' },
    { role: 'admin' as const, label: 'Admin', icon: 'shield-outline' as const, name: 'System Admin' },
];

//------This Function handles the Login Screen---------
export default function LoginScreen() {
    const [loading, setLoading] = useState(false);
    const { signIn, devSignIn } = useAuth();
    const router = useRouter();

    const hasInitializedRef = React.useRef(false);

    useEffect(() => {
        if (hasInitializedRef.current) return;
        if (!GoogleSignin) {
            console.log('Google Sign-In native module not available');
        } else if (!googleSigninConfigured) {
            try {
                if (!getGoogleWebClientId()) {
                    console.warn('No valid Google Web Client ID found in google-services.json.');
                }
                GoogleSignin.configure({ webClientId: getGoogleWebClientId() });
                googleSigninConfigured = true;
            } catch (e) {
                console.error('Google Signin config error', e);
            }
        }
        hasInitializedRef.current = true;
    }, []);

    //------This Function handles the Handle Google Sign In---------
    async function handleGoogleSignIn() {
        try {
            setLoading(true);
            await handleNativeGoogleSignIn();
        } finally {
            setLoading(false);
        }
    }

    //------This Function handles the Handle Native Google Sign In---------
    async function handleNativeGoogleSignIn() {
        if (!GoogleSignin || !firebaseAuth) {
            Alert.alert('Development Mode', 'Google Sign-In requires a development build.');
            return;
        }
        if (!getGoogleWebClientId()) {
            Alert.alert('Configuration Error', 'Google OAuth web client ID is missing from google-services.json.');
            return;
        }
        try {
            await GoogleSignin.hasPlayServices();
            const signInResult = await GoogleSignin.signIn();
            const userInfo = signInResult?.data || signInResult;
            if (!userInfo) return;
            const idToken = userInfo.idToken;
            if (!idToken) {
                throw new Error('No ID token obtained from Google Sign-In. Check the Google OAuth web client ID.');
            }

            const credential = firebaseAuth.GoogleAuthProvider.credential(idToken);
            const firebaseUser = await firebaseAuth().signInWithCredential(credential);
            const fbToken = await firebaseUser.user.getIdToken(true);

            await signIn(
                fbToken,
                firebaseUser.user.displayName || '',
                firebaseUser.user.photoURL || '',
            );
            router.replace('/');
        } catch (err: any) {
            if (err.code === 'auth/invalid-credential') {
                Alert.alert('Sign In Failed', 'Authentication token expired. Please check your device clock.');
            } else if (err.code === 'DEVELOPER_ERROR' || err.code === '10') {
                console.warn('Native Google sign-in configuration error.', err);
                Alert.alert(
                    'Google Sign-In Configuration Error',
                    'Android OAuth is not configured for this build. Add this build SHA-1 to Firebase, download updated google-services.json, then rebuild.'
                );
            } else {
                Alert.alert('Sign In Failed', err.message || 'Something went wrong');
            }
        }
    }

    return (
        <View style={s.container}>
            <ScrollView contentContainerStyle={s.scrollContent} showsVerticalScrollIndicator={false}>
                <View style={s.hero}>
                    <AuraLogo size="xlarge" color={colors.white} style={s.logo} />
                    <View style={s.divider} />
                    <Text style={s.tagline}>memory amplified</Text>
                </View>

                <View style={s.actions}>
                    <TouchableOpacity
                        style={[s.button, loading && s.buttonLoading]}
                        onPress={handleGoogleSignIn}
                        disabled={loading}
                        activeOpacity={0.85}
                    >
                        {loading ? (
                            <ActivityIndicator color={colors.bg} />
                        ) : (
                            <>
                                <Ionicons name="logo-google" size={18} color={colors.bg} />
                                <Text style={s.buttonText}>Continue with Google</Text>
                            </>
                        )}
                    </TouchableOpacity>
                </View>

                <Text style={s.terms}>
                    By continuing, you agree to our Terms of Service
                </Text>

                {__DEV__ && (
                    <View style={s.devSection}>
                        <View style={s.devHeader}>
                            <View style={s.devBadge}>
                                <Ionicons name="code-slash" size={10} color={colors.bg} />
                            </View>
                            <Text style={s.devTitle}>DEV MODE</Text>
                        </View>
                        <Text style={s.devSubtitle}>Sign in as a test user</Text>

                        <View style={s.devRoles}>
                            {DEV_ROLES.map((item) => (
                                <TouchableOpacity
                                    key={item.role}
                                    style={s.roleCard}
                                    onPress={() => devSignIn(item.role)}
                                    activeOpacity={0.7}
                                >
                                    <View style={s.roleIcon}>
                                        <Ionicons name={item.icon} size={18} color={colors.textPrimary} />
                                    </View>
                                    <Text style={s.roleLabel}>{item.label}</Text>
                                    <Text style={s.roleName}>{item.name}</Text>
                                </TouchableOpacity>
                            ))}
                        </View>
                    </View>
                )}
            </ScrollView>
        </View>
    );
}

const s = StyleSheet.create({
    container: {
        flex: 1,
        backgroundColor: colors.bg,
    },
    scrollContent: {
        flexGrow: 1,
        paddingVertical: spacing.xxl * 2,
        paddingHorizontal: spacing.xl,
    },
    hero: {
        flex: 1,
        alignItems: 'center',
        justifyContent: 'center',
        gap: spacing.lg,
        minHeight: 300,
    },
    logo: {
        marginBottom: spacing.sm,
    },
    divider: {
        width: 32,
        height: 1,
        backgroundColor: colors.border,
    },
    tagline: {
        color: colors.textSecondary,
        fontSize: fonts.sizes.sm,
        letterSpacing: 8,
        textTransform: 'lowercase',
        opacity: 0.6,
    },
    actions: {
        width: '100%',
        alignItems: 'center',
        marginBottom: spacing.lg,
    },
    button: {
        backgroundColor: colors.white,
        width: '100%',
        height: 56,
        borderRadius: radius.full,
        alignItems: 'center',
        justifyContent: 'center',
        flexDirection: 'row',
        gap: spacing.xs,
    },
    buttonLoading: {
        opacity: 0.9,
    },
    buttonText: {
        color: colors.bg,
        fontSize: fonts.sizes.md,
        fontWeight: '600',
        letterSpacing: -0.2,
    },
    terms: {
        color: colors.textMuted,
        fontSize: 11,
        textAlign: 'center',
        letterSpacing: 0.3,
        lineHeight: 16,
        paddingHorizontal: spacing.lg,
        marginBottom: spacing.xl,
    },

    devSection: {
        borderTopWidth: 1,
        borderTopColor: colors.border,
        paddingTop: spacing.xl,
        marginTop: spacing.sm,
    },
    devHeader: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: spacing.sm,
        marginBottom: 4,
    },
    devBadge: {
        backgroundColor: colors.red,
        width: 20,
        height: 20,
        borderRadius: 4,
        alignItems: 'center',
        justifyContent: 'center',
    },
    devTitle: {
        color: colors.red,
        fontSize: 10,
        fontWeight: '700',
        letterSpacing: 2,
    },
    devSubtitle: {
        color: colors.textMuted,
        fontSize: fonts.sizes.xs,
        marginBottom: spacing.lg,
    },
    devRoles: {
        flexDirection: 'row',
        gap: spacing.sm,
    },
    roleCard: {
        flex: 1,
        backgroundColor: colors.surface,
        borderRadius: radius.xl,
        padding: spacing.md,
        alignItems: 'center',
        gap: 6,
        borderWidth: 1,
        borderColor: colors.border,
    },
    roleIcon: {
        width: 36,
        height: 36,
        borderRadius: 10,
        backgroundColor: colors.surfaceLight,
        alignItems: 'center',
        justifyContent: 'center',
        marginBottom: 2,
    },
    roleLabel: {
        color: colors.textPrimary,
        fontSize: fonts.sizes.xs,
        fontWeight: '600',
    },
    roleName: {
        color: colors.textMuted,
        fontSize: 9,
        textAlign: 'center',
    },
});
