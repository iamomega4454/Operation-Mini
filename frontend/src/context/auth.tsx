import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import api from '../services/api';
import { connectionMonitor } from '../services/connectionMonitor';
import { authEvents } from '../services/authEvents';
import { clearAuthToken, getAuthToken, setAuthToken } from '../services/authToken';

export interface User {
    id: string;
    firebase_uid: string;
    email: string;
    display_name: string;
    photo_url: string;
    role: 'patient' | 'caregiver' | 'admin';
    linked_patients: string[];
    is_onboarded: boolean;
    isVoiceSetup?: boolean;
}

interface AuthState {
    user: User | null;
    token: string | null;
    loading: boolean;
    connectionError: boolean;
    signIn: (idToken: string, name: string, photo: string) => Promise<void>;
    signOut: () => Promise<void>;
    refreshUser: () => Promise<void>;
    markOnboarded: () => void;
    devSignIn: (role: 'patient' | 'caregiver' | 'admin') => void;
    isVoiceSetup: boolean;
    setVoiceSetup: (done: boolean) => Promise<void>;
    initialLoadDone: boolean;
}

const AuthContext = createContext<AuthState>({
    user: null,
    token: null,
    loading: true,
    connectionError: false,
    signIn: async () => { },
    signOut: async () => { },
    refreshUser: async () => { },
    markOnboarded: () => { },
    devSignIn: () => { },
    isVoiceSetup: false,
    setVoiceSetup: async () => { },
    initialLoadDone: false,
});

//------This Function handles the Auth Provider---------
export function AuthProvider({ children }: { children: ReactNode }) {
    const [user, setUser] = useState<User | null>(null);
    const [token, setToken] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [connectionError, setConnectionError] = useState(false);
    const [initialLoadDone, setInitialLoadDone] = useState(false);
    const [isVoiceSetup, setIsVoiceSetupState] = useState(false);
    const wasDisconnectedRef = React.useRef(false);

    useEffect(() => {
        const unsubscribeAuth = authEvents.subscribe('unauthorized', () => {
            signOut();
        });

        return () => {
            unsubscribeAuth();
        };
    }, []);

    useEffect(() => {
        loadSavedSession();

    }, []);

    useEffect(() => {
        const unsubscribe = connectionMonitor.subscribe((isNowConnected, pingTime) => {
            if (!isNowConnected) {
                wasDisconnectedRef.current = true;
                setConnectionError(true);
            } else {
                if (wasDisconnectedRef.current && initialLoadDone) {
                    wasDisconnectedRef.current = false;
                    setConnectionError(false);
                    reloadSession();
                } else {
                    setConnectionError(false);
                }
            }
        });

        return () => {
            unsubscribe();
        };
    }, [initialLoadDone]);

    //------This Function handles the Reload Session---------
    async function reloadSession() {
        try {
            const saved = await getAuthToken();
            if (saved) {
                setToken(saved);
                const res = await api.get('/auth/me');
                setUser(res.data);
                setConnectionError(false);
            }
        } catch {
        }
    }

    //------This Function handles the Load Saved Session---------
    async function loadSavedSession() {
        try {
            const voiceSetup = await AsyncStorage.getItem('isVoiceSetup');
            setIsVoiceSetupState(voiceSetup === 'true');

            const saved = await getAuthToken();
            if (saved) {
                setToken(saved);
                const res = await api.get('/auth/me');
                setUser(res.data);
            }
        } catch (err: any) {
            if (err.code === 'ECONNABORTED' || err.message?.includes('Network Error') || !err.response) {
                setConnectionError(true);
            } else {
                await clearAuthToken();
                setToken(null);
            }
        }
        setLoading(false);
        setInitialLoadDone(true);
    }

    //------This Function handles the Sign In---------
    async function signIn(idToken: string, name: string, photo: string) {
        await setAuthToken(idToken);
        setToken(idToken);
        const registrationPayload = {
            display_name: name,
            photo_url: photo,
        };

        try {
            await api.post('/auth/register', registrationPayload);
            const meRes = await api.get('/auth/me');
            setUser(meRes.data);
        } catch (err: any) {
            if (err.response?.status === 401) {
                const refreshedToken = await getAuthToken(true);
                if (refreshedToken && refreshedToken !== idToken) {
                    await setAuthToken(refreshedToken);
                    setToken(refreshedToken);

                    try {
                        await api.post('/auth/register', registrationPayload);
                        const retryMe = await api.get('/auth/me');
                        setUser(retryMe.data);
                        return;
                    } catch (retryErr: any) {
                        err = retryErr;
                    }
                }
            }

            if (err.code === 'ECONNABORTED' || err.message?.includes('Network Error') || !err.response) {
                await clearAuthToken();
                setToken(null);
                throw new Error('Connection failed');
            }
            if (err.response?.status === 403) {
                await clearAuthToken();
                setToken(null);
                throw new Error('Account banned');
            }
            await clearAuthToken();
            setToken(null);
            throw err;
        }
    }

    //------This Function handles the Sign Out---------
    async function signOut() {
        await clearAuthToken();
        await AsyncStorage.removeItem('dev_mode_user');
        setUser(null);
        setToken(null);
    }

    //------This Function handles the Dev Sign In---------
    function devSignIn(role: 'patient' | 'caregiver' | 'admin') {
        if (!__DEV__) return;
        const fakeUsers: Record<string, User> = {
            patient: {
                id: 'dev-patient-001',
                firebase_uid: 'dev_patient_uid',
                email: 'patient@aura.dev',
                display_name: 'Alex Rivera',
                photo_url: '',
                role: 'patient',
                linked_patients: [],
                is_onboarded: true,
            },
            caregiver: {
                id: 'dev-caregiver-001',
                firebase_uid: 'dev_caregiver_uid',
                email: 'caregiver@aura.dev',
                display_name: 'Dr. Sarah Chen',
                photo_url: '',
                role: 'caregiver',
                linked_patients: ['dev_patient_uid'],
                is_onboarded: true,
            },
            admin: {
                id: 'dev-admin-001',
                firebase_uid: 'dev_admin_uid',
                email: 'admin@aura.dev',
                display_name: 'System Admin',
                photo_url: '',
                role: 'admin',
                linked_patients: [],
                is_onboarded: true,
            },
        };
        const fakeUser = fakeUsers[role];
        console.log('[DEV] Signing in as:', role, fakeUser.display_name);
        setUser(fakeUser);
        setToken('dev-token-' + role);
        setLoading(false);
        setInitialLoadDone(true);
        setConnectionError(false);
        AsyncStorage.setItem('firebase_token', 'dev-token-' + role);
        AsyncStorage.setItem('dev_mode_user', JSON.stringify(fakeUser));
    }

    //------This Function handles the Refresh User---------
    async function refreshUser() {
        try {
            const res = await api.get('/auth/me');
            setUser(res.data);
        } catch { }
    }

    //------This Function handles the Mark Onboarded---------
    function markOnboarded() {
        setUser((prev) => {
            if (!prev) {
                return prev;
            }
            return { ...prev, is_onboarded: true };
        });
    }

    //------This Function handles the Set Voice Setup---------
    async function setVoiceSetup(done: boolean) {
        await AsyncStorage.setItem('isVoiceSetup', done ? 'true' : 'false');
        setIsVoiceSetupState(done);
    }

    return (
        <AuthContext.Provider value={{
            user,
            token,
            loading,
            connectionError,
            signIn,
            signOut,
            refreshUser,
            markOnboarded,
            devSignIn,
            isVoiceSetup,
            setVoiceSetup,
            initialLoadDone,
        }}>
            {children}
        </AuthContext.Provider>
    );
}

//------This Function handles the Use Auth---------
export const useAuth = () => useContext(AuthContext);
