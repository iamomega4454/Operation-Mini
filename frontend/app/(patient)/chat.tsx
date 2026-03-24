import React, { useState, useRef, useEffect } from 'react';
import {
    View,
    Text,
    StyleSheet,
    TouchableOpacity,
    Animated,
    Alert,
    Linking,
    Easing,
} from 'react-native';
import { useRouter, useLocalSearchParams } from 'expo-router';
import AsyncStorage from '@react-native-async-storage/async-storage';
import api from '../../src/services/api';
import {
    ensureAuraMicAuthorized,
    isAuraConnected,
} from '../../src/services/aura-discovery';
import {
    sendMessageStream,
    resetConversation,
    initializeOrito,
    getUserContext,
} from '../../src/services/orito';
import { incrementConversations, incrementVoiceCommands } from '../../src/services/moduleStats';
import {
    voiceAssistantService,
    detectWakeWord,
    extractCommand,
    WakeWordState,
    startRecognition,
    stopRecognition,
} from '../../src/services/voiceAssistant';
import nativeSpeechService from '../../src/services/nativeSpeech';
import OritoOverlay from '../../src/components/OritoOverlay';
import OritoAvatar from '../../src/components/OritoAvatar';
import Header from '../../src/components/Header';
import { fonts } from '../../src/theme';
import { Ionicons } from '@expo/vector-icons';


function getVoiceStateLabel(state: WakeWordState): string {
    switch (state) {
        case 'listening':
            return 'LISTENING';
        case 'processing':
            return 'THINKING...';
        case 'speaking':
            return 'SPEAKING';
        default:
            return 'Tap to Talk';
    }
}

function getVoiceStateColor(state: WakeWordState): string {
    switch (state) {
        case 'listening':
            return '#2dd4bf';
        case 'processing':
            return '#f59e0b';
        case 'speaking':
            return '#60a5fa';
        default:
            return '#94a3b8';
    }
}

function getMicButtonColor(state: WakeWordState): string {
    switch (state) {
        case 'listening':
            return '#ef4444';
        case 'processing':
            return '#1e293b';
        case 'speaking':
            return '#1e293b';
        default:
            return '#0f172a';
    }
}

function getMicIcon(state: WakeWordState): keyof typeof Ionicons.glyphMap {
    switch (state) {
        case 'listening':
            return 'stop';
        case 'processing':
            return 'hourglass-outline';
        case 'speaking':
            return 'volume-high';
        default:
            return 'mic';
    }
}


//------Equalizer ring that animates around the bot avatar---------
const BAR_COUNT = 24;
const EQ_CONTAINER = 310;
const AVATAR_R = 84;
const BAR_H = 28;
const BAR_W = 3.5;
const BAR_DIST = AVATAR_R + 10 + BAR_H / 2;

function EqualizerRing({ active, listening }: { active: boolean; listening: boolean }) {
    const barAnims = useRef(
        Array.from({ length: BAR_COUNT }, () => new Animated.Value(0.12))
    ).current;

    useEffect(() => {
        if (!active && !listening) {
            barAnims.forEach((a) =>
                Animated.spring(a, { toValue: 0.12, useNativeDriver: true }).start()
            );
            return;
        }

        const stopFns: (() => void)[] = [];
        barAnims.forEach((anim, i) => {
            const baseSpeed = listening ? 180 : 260;
            const speed = baseSpeed + (i % 6) * 55;
            const maxVal = listening ? 0.5 + (i % 3) * 0.1 : 0.75 + (i % 4) * 0.08;
            const minVal = 0.1 + (i % 3) * 0.04;
            // stagger initial phase
            anim.setValue(minVal + ((Math.sin(i * (Math.PI * 2) / BAR_COUNT) + 1) / 2) * (maxVal - minVal));
            const loop = Animated.loop(
                Animated.sequence([
                    Animated.timing(anim, { toValue: maxVal, duration: speed, easing: Easing.inOut(Easing.ease), useNativeDriver: true }),
                    Animated.timing(anim, { toValue: minVal, duration: speed * 1.1, easing: Easing.inOut(Easing.ease), useNativeDriver: true }),
                ])
            );
            loop.start();
            stopFns.push(() => loop.stop());
        });

        return () => stopFns.forEach((fn) => fn());
    }, [active, listening, barAnims]);

    const color = listening ? '#f87171' : '#4ade80';

    return (
        <View style={{ width: EQ_CONTAINER, height: EQ_CONTAINER, position: 'absolute' }}>
            {barAnims.map((anim, i) => {
                const angle = (i / BAR_COUNT) * 360;
                return (
                    <Animated.View
                        key={i}
                        style={{
                            position: 'absolute',
                            left: EQ_CONTAINER / 2 - BAR_W / 2,
                            top: EQ_CONTAINER / 2 - BAR_H / 2,
                            width: BAR_W,
                            height: BAR_H,
                            borderRadius: BAR_W / 2,
                            backgroundColor: color,
                            opacity: active || listening ? 0.85 : 0.4,
                            transform: [
                                { rotate: `${angle}deg` },
                                { translateY: -BAR_DIST },
                                { scaleY: anim },
                            ],
                        }}
                    />
                );
            })}
        </View>
    );
}

//------This Function handles the Speak Response---------
async function speakResponse(text: string) {
    console.log('[Chat] speakResponse called, text length:', text.length);
    let rate = 1.0;
    let pitch = 1.0;
    let voiceGender: string | undefined;

    try {
        const settingsRaw = await AsyncStorage.getItem('user_settings_voice');
        if (settingsRaw) {
            const s = JSON.parse(settingsRaw);
            if (s.voice_feedback === false) return;
            if (s.voice_speed != null) rate = s.voice_speed;
            if (s.voice_pitch != null) pitch = s.voice_pitch;
            if (typeof s.voice_gender === 'string') {
                voiceGender = s.voice_gender;
            }
        }
    } catch {
        // ignore and use defaults
    }

    await nativeSpeechService.speak(text, {
        rate,
        pitch,
        language: 'en',
        voiceGender,
    });
}

//------This Function handles the Chat Screen---------
export default function ChatScreen() {
    const router = useRouter();
    const { autoStart } = useLocalSearchParams();

    const [loading, setLoading] = useState(false);
    const [isListening, setIsListening] = useState(false);
    const [overlayState, setOverlayState] = useState<WakeWordState>('idle');
    const [overlayTranscription, setOverlayTranscription] = useState('');
    const [overlayResponse, setOverlayResponse] = useState('');
    const [showOverlay, setShowOverlay] = useState(false);
    const [userName, setUserName] = useState<string | null>(null);
    const [micGateMessage, setMicGateMessage] = useState<string | null>(null);

    const fadeAnim = useRef(new Animated.Value(0)).current;
    // Ref that mirrors overlayTranscription state so timeout closures always read the latest value
    const overlayTranscriptionRef = useRef('');
    const isMountedRef = useRef(true);
    const isProcessingTranscriptRef = useRef(false);
    const autoStartHandledRef = useRef(false);
    const isStartingListeningRef = useRef(false);
    const isStoppingListeningRef = useRef(false);
    const isSendingRef = useRef(false);
    const conversationActiveRef = useRef(false);
    const forceEndpointTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    // Ref to trigger auto-restart after TTS; avoids stale closure over loading/overlayState
    const shouldAutoRestartRef = useRef(false);
    // Mirror refs so callbacks captured in the init closure always read live values
    const isListeningRef = useRef(false);
    const overlayStateRef = useRef<WakeWordState>('idle');

    // Wrapper setters that keep refs in sync with state — use these everywhere
    // inside the component so callbacks captured in stale closures always get
    // the live value via the ref, not the stale closure copy.
    function setListening(value: boolean) {
        isListeningRef.current = value;
        setIsListening(value);
    }
    function setOverlay(value: WakeWordState) {
        overlayStateRef.current = value;
        setOverlayState(value);
    }

    const listeningActive = isListening || overlayState === 'listening';

    // Auto-restart listening after TTS completes (when conversationActive and state returns to idle)
    useEffect(() => {
        if (
            overlayState === 'idle' &&
            !loading &&
            !isProcessingTranscriptRef.current &&
            shouldAutoRestartRef.current &&
            conversationActiveRef.current
        ) {
            shouldAutoRestartRef.current = false;
            const timer = setTimeout(() => {
                if (
                    isMountedRef.current &&
                    conversationActiveRef.current &&
                    !isStoppingListeningRef.current
                ) {
                    void startListening();
                }
            }, 400);
            return () => clearTimeout(timer);
        }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [overlayState, loading]);

    useEffect(() => {
        let disposed = false;
        isMountedRef.current = true;

        //------This Function handles the Init---------
        const init = async () => {
            await initializeOrito();
            if (disposed) return;

            const context = getUserContext();
            if (context.userName) {
                setUserName(context.userName);
            }

            await voiceAssistantService.initialize();
            if (disposed) return;

            voiceAssistantService.setWakeWordCallback(() => {
                setShowOverlay(true);
                setOverlay('listening');
                setListening(true);
                playWakeSound();
            });

            voiceAssistantService.setStateChangeCallback((state) => {
                setOverlay(state);
                setListening(state === 'listening');
            });

            voiceAssistantService.setTranscriptionCallback((text, isFinal) => {
                setOverlayTranscription(text);
                overlayTranscriptionRef.current = text;

                const finalText = text.trim();

                // Empty final Turn (e.g. silence after ForceEndpoint) — cancel any
                // pending timeout, stop listening, and reset state to idle.
                if (isFinal && !finalText) {
                    if (forceEndpointTimeoutRef.current) {
                        clearTimeout(forceEndpointTimeoutRef.current);
                        forceEndpointTimeoutRef.current = null;
                    }
                    nativeSpeechService.clearLatestPartialTranscript();
                    // Reset state synchronously first so the UI is never stuck
                    // in 'listening' if stopListening() is blocked by a guard race.
                    setListening(false);
                    setOverlay('idle');
                    conversationActiveRef.current = false;
                    void stopListening();
                    return;
                }

                if (!isFinal) {
                    return;
                }

                if (isProcessingTranscriptRef.current) {
                    return;
                }

                // Clear any pending ForceEndpoint timeout — we got the transcript naturally
                if (forceEndpointTimeoutRef.current) {
                    clearTimeout(forceEndpointTimeoutRef.current);
                    forceEndpointTimeoutRef.current = null;
                }

                // Clear the buffered partial now that we have a final transcript
                nativeSpeechService.clearLatestPartialTranscript();
                isProcessingTranscriptRef.current = true;
                setListening(false);
                setOverlay('processing');

                const { detected } = detectWakeWord(finalText);
                const commandText = (detected ? extractCommand(finalText) : finalText).trim();
                if (!commandText) {
                    setOverlay('idle');
                    isProcessingTranscriptRef.current = false;
                    return;
                }

                incrementVoiceCommands().catch(() => { });

                void handleSend(commandText, true).finally(() => {
                    isProcessingTranscriptRef.current = false;
                });
            });

            Animated.timing(fadeAnim, {
                toValue: 1,
                duration: 450,
                useNativeDriver: true,
            }).start();

            if (autoStart === 'true' && !autoStartHandledRef.current) {
                autoStartHandledRef.current = true;
                conversationActiveRef.current = true;
                await startListening();
            }
        };

        void init();

        return () => {
            disposed = true;
            isMountedRef.current = false;
            isProcessingTranscriptRef.current = false;
            if (forceEndpointTimeoutRef.current) {
                clearTimeout(forceEndpointTimeoutRef.current);
                forceEndpointTimeoutRef.current = null;
            }
            void stopRecognition().catch(() => { });
            voiceAssistantService.cleanup();
            void nativeSpeechService.stopSpeaking().catch(() => { });
        };
    }, [autoStart, fadeAnim]);

    //------This Function handles the Play Wake Sound---------
    async function playWakeSound() {
        try {
            const { default: Haptics } = await import('expo-haptics');
            await Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
        } catch {
            // ignore
        }
    }

    //------This Function handles the Start Listening---------
    async function startListening() {
        console.log('[Chat] startListening called, state:', { loading, overlayState, listeningActive, isProcessing: isProcessingTranscriptRef.current });
        if (
            loading ||
            overlayState === 'processing' ||
            listeningActive ||
            isProcessingTranscriptRef.current ||
            isStartingListeningRef.current ||
            isStoppingListeningRef.current
        ) {
            console.log('[Chat] startListening blocked by guards', {
                loading,
                overlayState,
                listeningActive,
                isProcessing: isProcessingTranscriptRef.current,
                isStarting: isStartingListeningRef.current,
                isStopping: isStoppingListeningRef.current,
            });
            return;
        }

        isStartingListeningRef.current = true;

        try {
            if (isAuraConnected()) {
                const micAuthorization = await ensureAuraMicAuthorized();
                if (!micAuthorization.allowed) {
                    const deniedMessage = micAuthorization.message || 'Face not recognized. Please look at the Aura camera and try again.';
                    setMicGateMessage(deniedMessage);
                    conversationActiveRef.current = false;
                    shouldAutoRestartRef.current = false;
                    setListening(false);
                    setOverlay('idle');
                    Alert.alert('Face Not Recognized', deniedMessage);
                    return;
                }
            }

            setMicGateMessage(null);
            void playWakeSound();

            setOverlayResponse('');
            setOverlayTranscription('');
            overlayTranscriptionRef.current = '';

            const started = await startRecognition();
            console.log('[Chat] startRecognition result:', started);
            if (!started) {
                Alert.alert(
                    'Microphone Unavailable',
                    'Could not start live speech recognition. Please check microphone permissions.',
                );
                setOverlay('idle');
                return;
            }

            setListening(true);
            setOverlay('listening');
        } catch (error) {
            console.error('[Chat] Failed to start listening:', error);
            setListening(false);
            setOverlay('idle');
        } finally {
            isStartingListeningRef.current = false;
        }
    }

    //------This Function handles the Stop Listening---------
    async function stopListening() {
        // Always clear the listening flag immediately — even if already stopping — so
        // the UI never gets stuck in a 'listening' visual state due to a double-tap race
        // or a stale closure in the transcription callback.
        setListening(false);

        // Use refs here (not the stale closure values of listeningActive / overlayState)
        // because stopListening() is called from inside the setTranscriptionCallback closure
        // which was captured when init ran and never sees updated state.
        const liveListening = isListeningRef.current;
        const liveOverlay   = overlayStateRef.current;
        if ((!liveListening && liveOverlay !== 'processing') || isStoppingListeningRef.current) {
            return;
        }

        isStoppingListeningRef.current = true;

        try {
            await stopRecognition();
            if (!isProcessingTranscriptRef.current) {
                setOverlay('idle');
            }
        } catch (error) {
            console.error('[Chat] Failed to stop listening:', error);
            setOverlay('idle');
        } finally {
            isStoppingListeningRef.current = false;
        }
    }

    //------This Function handles the Handle Send---------
    async function handleSend(textOverride?: string, fromOverlay: boolean = false) {
        const text = (textOverride || '').trim();
        console.log('[Chat] handleSend called:', { textLength: text.length, fromOverlay, loading, isSending: isSendingRef.current });
        if (!text || loading || isSendingRef.current) {
            if (fromOverlay) {
                setOverlay('idle');
            }
            return;
        }

        isSendingRef.current = true;
        setLoading(true);
        incrementConversations().catch(() => { });

        try {
            let reply = '';

            reply = await sendMessageStream(
                text,
                () => {},
                () => {},
            );

            if (!isMountedRef.current) {
                return;
            }

            let displayReply = reply;
            if (reply.startsWith('CALL_ACTION:')) {
                const parts = reply.replace('CALL_ACTION:', '').split('|');
                const phone = parts[0]?.trim();
                const message = parts[1]?.trim() || `Calling ${phone}`;
                displayReply = message;
                if (phone) {
                    Linking.openURL(`tel:${phone}`).catch(() => {
                        Alert.alert('Call Failed', `Could not initiate call to ${phone}`);
                    });
                }
            }

            if (fromOverlay) {
                setOverlayResponse(displayReply);
                setOverlay('speaking');
            }

            try {
                const conversationContent = `User: ${text}\n\nOrito: ${displayReply}`;
                await api.post('/journal/', {
                    content: conversationContent,
                    source: 'ai_generated',
                    mood: '',
                });
            } catch (error) {
                console.error('[Chat] Failed to save to journal:', error);
            }

            await speakResponse(displayReply);
            if (fromOverlay && isMountedRef.current) {
                setOverlay('idle');
                // Signal the auto-restart useEffect (avoids stale closure over loading/overlayState)
                shouldAutoRestartRef.current = true;
            }
        } catch (error) {
            if (!isMountedRef.current) {
                return;
            }

            console.error('[Chat] Failed to send message:', error);

            const fallbackReply = 'I ran into a voice processing issue. Please try again.';
            if (fromOverlay) {
                setOverlayResponse(fallbackReply);
                setOverlay('idle');
            }
        } finally {
            isSendingRef.current = false;
            if (isMountedRef.current) {
                setLoading(false);
            }
        }
    }

    //------This Function handles the Close Overlay---------
    function closeOverlay() {
        conversationActiveRef.current = false;
        shouldAutoRestartRef.current = false;
        if (forceEndpointTimeoutRef.current) {
            clearTimeout(forceEndpointTimeoutRef.current);
            forceEndpointTimeoutRef.current = null;
        }
        setShowOverlay(false);
        setOverlay('idle');
        setOverlayTranscription('');
        overlayTranscriptionRef.current = '';
        setOverlayResponse('');
        setMicGateMessage(null);
        setListening(false);
        isProcessingTranscriptRef.current = false;
        isStartingListeningRef.current = false;
        isStoppingListeningRef.current = false;

        void stopRecognition().catch(() => { });
        void nativeSpeechService.stopSpeaking().catch(() => { });
    }

    //------This Function handles the Handle Overlay Start Listening---------
    function handleOverlayStartListening() {
        startListening();
    }

    //------This Function handles the Handle Overlay Stop Listening---------
    function handleOverlayStopListening() {
        stopListening();
    }

    //------This Function handles the Handle Overlay Stop Speaking---------
    function handleOverlayStopSpeaking() {
        void nativeSpeechService.stopSpeaking().catch(() => { });
        setOverlay('idle');
    }

    //------This Function handles the Handle Mic Button---------
    function handleMicButtonPress() {
        console.log('[Chat] handleMicButtonPress, listeningActive:', listeningActive, 'overlayState:', overlayState, 'conversationActive:', conversationActiveRef.current);

        // Cancel if processing or speaking
        if (overlayState === 'processing' || overlayState === 'speaking') {
            conversationActiveRef.current = false;
            shouldAutoRestartRef.current = false;
            if (forceEndpointTimeoutRef.current) {
                clearTimeout(forceEndpointTimeoutRef.current);
                forceEndpointTimeoutRef.current = null;
            }
            void stopListening();
            void nativeSpeechService.stopSpeaking().catch(() => { });
            setOverlay('idle');
            return;
        }

        // Tap while listening = ForceEndpoint to flush AssemblyAI's current turn
        if (listeningActive) {
            if (isProcessingTranscriptRef.current) return; // already processing

            // Send ForceEndpoint so AssemblyAI immediately returns whatever it heard
            const forced = nativeSpeechService.forceEndpoint();
            console.log('[Chat] ForceEndpoint sent:', forced);

            if (!forced) {
                // WebSocket not open — fall back to partial transcript
                const partialText = (nativeSpeechService.getLatestPartialTranscript() || overlayTranscriptionRef.current).trim();
                void stopListening();
                if (partialText) {
                    isProcessingTranscriptRef.current = true;
                    setOverlay('processing');
                    nativeSpeechService.clearLatestPartialTranscript();
                    incrementVoiceCommands().catch(() => { });
                    void handleSend(partialText, true).finally(() => {
                        isProcessingTranscriptRef.current = false;
                    });
                } else {
                    conversationActiveRef.current = false;
                }
                return;
            }

            // ForceEndpoint sent — wait up to 2.5s for AssemblyAI Turn callback
            // The transcription callback will handle it; this timeout is a safety fallback
            forceEndpointTimeoutRef.current = setTimeout(() => {
                forceEndpointTimeoutRef.current = null;
                if (!isProcessingTranscriptRef.current) {
                    const partialText = (nativeSpeechService.getLatestPartialTranscript() || overlayTranscriptionRef.current).trim();
                    console.log('[Chat] ForceEndpoint timeout, partial:', partialText);
                    void stopListening();
                    if (partialText) {
                        isProcessingTranscriptRef.current = true;
                        setOverlay('processing');
                        nativeSpeechService.clearLatestPartialTranscript();
                        incrementVoiceCommands().catch(() => { });
                        void handleSend(partialText, true).finally(() => {
                            isProcessingTranscriptRef.current = false;
                        });
                    } else {
                        conversationActiveRef.current = false;
                        setOverlay('idle');
                    }
                }
            }, 2500);
            return;
        }

        // Start conversation
        conversationActiveRef.current = true;
        void startListening();
    }

    const liveTranscript = overlayTranscription;
    const isSpeaking = overlayState === 'speaking';
    const isProcessing = overlayState === 'processing' || loading;
    const avatarState = isSpeaking ? 'speaking' : isProcessing ? 'thinking' : listeningActive ? 'listening' : 'idle';

    return (
        <View style={s.container}>
            <OritoOverlay
                visible={showOverlay}
                state={overlayState}
                transcription={overlayTranscription}
                response={overlayResponse}
                onClose={closeOverlay}
                onStartListening={handleOverlayStartListening}
                onStopListening={handleOverlayStopListening}
                onStopSpeaking={handleOverlayStopSpeaking}
            />

            <Header
                title="Orito"
                subtitle="Voice Assistant"
                centered
                showBack
                onBackPress={() => router.back()}
                rightElement={
                    <TouchableOpacity
                        style={s.resetBtn}
                        onPress={() => {
                            conversationActiveRef.current = false;
                            resetConversation();
                        }}
                        activeOpacity={0.85}
                    >
                        <Ionicons name="refresh" size={16} color="#cbd5e1" />
                    </TouchableOpacity>
                }
            />

            {/* Avatar - top area, tappable as mic */}
            <Animated.View style={[s.avatarSection, { opacity: fadeAnim }]}>
                <TouchableOpacity
                    onPress={handleMicButtonPress}
                    activeOpacity={0.88}
                >
                    <View style={s.eqWrap}>
                        <EqualizerRing active={isSpeaking || isProcessing} listening={listeningActive} />
                        <View style={[s.avatarCircle, listeningActive && s.avatarCircleActive, isProcessing && s.avatarCircleProcessing]}>
                            <OritoAvatar state={avatarState} size={160} />
                        </View>
                    </View>
                </TouchableOpacity>
                <Text style={s.statusLabel}>{getVoiceStateLabel(overlayState)}</Text>
                {micGateMessage ? (
                    <Text style={s.micGateMessage}>{micGateMessage}</Text>
                ) : null}
                {userName && !liveTranscript ? (
                    <Text style={s.userNameHint}>Connected as {userName}</Text>
                ) : null}
                {liveTranscript ? (
                    <View style={s.transcriptCard}>
                        <Ionicons name="mic" size={12} color="#34d399" style={{ marginRight: 6 }} />
                        <Text style={s.transcriptText} numberOfLines={2}>{liveTranscript}</Text>
                    </View>
                ) : null}
            </Animated.View>
        </View>
    );
}

const s = StyleSheet.create({
    container: {
        flex: 1,
        backgroundColor: '#020617',
    },
    resetBtn: {
        width: 32,
        height: 32,
        borderRadius: 16,
        borderWidth: 1,
        borderColor: '#334155',
        backgroundColor: '#0f172a',
        alignItems: 'center',
        justifyContent: 'center',
    },
    avatarSection: {
        flex: 1,
        alignItems: 'center',
        justifyContent: 'flex-start',
        paddingTop: 24,
    },
    eqWrap: {
        width: 310,
        height: 310,
        alignItems: 'center',
        justifyContent: 'center',
    },
    avatarCircle: {
        position: 'absolute',
        width: 168,
        height: 168,
        borderRadius: 84,
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: 'transparent',
    },
    avatarCircleActive: {
        borderWidth: 2,
        borderColor: '#ef4444',
    },
    avatarCircleProcessing: {
        borderWidth: 2,
        borderColor: '#22d3ee',
    },
    statusLabel: {
        color: '#94a3b8',
        fontSize: fonts.sizes.sm,
        fontWeight: '600',
        marginTop: 10,
        letterSpacing: 0.4,
        textTransform: 'uppercase',
    },
    userNameHint: {
        color: '#475569',
        fontSize: fonts.sizes.xs,
        marginTop: 4,
    },
    micGateMessage: {
        color: '#fca5a5',
        fontSize: fonts.sizes.xs,
        marginTop: 6,
        textAlign: 'center',
        paddingHorizontal: 24,
    },
    transcriptCard: {
        flexDirection: 'row',
        alignItems: 'center',
        marginTop: 10,
        backgroundColor: '#052e2b',
        borderRadius: 12,
        borderWidth: 1,
        borderColor: '#0f3f36',
        paddingHorizontal: 12,
        paddingVertical: 6,
        maxWidth: 300,
    },
    transcriptText: {
        color: '#d1fae5',
        fontSize: fonts.sizes.sm,
        flex: 1,
    },
    micHint: {
        color: '#475569',
        fontSize: fonts.sizes.xs,
        marginTop: 10,
        letterSpacing: 0.3,
    },
});
