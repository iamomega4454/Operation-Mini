import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Network from 'expo-network';
import api from './api';

const AURA_KEY = 'aura_module_address';
const AURA_PORT = 8001;
const SCAN_TIMEOUT_MS = 2000;

interface AuraDevice {
    service: string;
    hostname: string;
    ip: string;
    ws_port: number;
    port?: number;
    version: string;
}

interface BackendAuraModule {
    patient_uid: string;
    ip: string;
    port: number;
    status: string;
}

type ConnectionState = 'disconnected' | 'connecting' | 'connected' | 'reconnecting';

interface AuraIdentifyResultMessage {
    type: 'identify_result';
    faces?: any[];
    mic_started?: boolean;
    error?: string;
    message?: string;
}

interface AuraMicAuthorizationResult {
    allowed: boolean;
    message?: string;
    response?: AuraIdentifyResultMessage;
}

let ws: WebSocket | null = null;
let messageHandler: ((data: any) => void) | null = null;
let stateChangeHandler: ((state: ConnectionState) => void) | null = null;
let connectionState: ConnectionState = 'disconnected';
let reconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 10;
const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 16000, 30000]; 

let pendingIdentifyRequest: Promise<AuraMicAuthorizationResult> | null = null;
let resolvePendingIdentify: ((value: AuraMicAuthorizationResult) => void) | null = null;
let identifyTimeoutHandle: ReturnType<typeof setTimeout> | null = null;
let lastIdentifyResult: AuraIdentifyResultMessage | null = null;

const IDENTIFY_TIMEOUT_MS = 15000;

let storedIp: string = '';
let storedPort: number = 8001;
let storedPatientUid: string = '';
let storedAuthToken: string = '';
let storedBackendUrl: string = '';

//------This Function handles the Reset Identify Request--------- 
function resetIdentifyRequest() {
    if (identifyTimeoutHandle) {
        clearTimeout(identifyTimeoutHandle);
        identifyTimeoutHandle = null;
    }
    pendingIdentifyRequest = null;
    resolvePendingIdentify = null;
}

//------This Function handles the Get Face Gate Message---------
function getFaceGateMessage(payload?: Partial<AuraIdentifyResultMessage>): string {
    const message = typeof payload?.message === 'string' ? payload.message.trim() : '';
    if (message) {
        return message;
    }

    switch (payload?.error) {
        case 'no_frame':
            return 'Aura camera is unavailable. Please try again.';
        case 'not_authenticated':
            return 'Aura module is not authenticated. Please reconnect and try again.';
        case 'identification_failed':
            return 'Face recognition failed. Please try again.';
        default:
            return 'Face not recognized. Please look at the Aura camera and try again.';
    }
}

//------This Function handles the Resolve Identify Request---------
function settleIdentifyRequest(result: AuraMicAuthorizationResult) {
    if (resolvePendingIdentify) {
        resolvePendingIdentify(result);
    }
    resetIdentifyRequest();
}

//------This Function handles the Dispatch Aura Message---------
function dispatchAuraMessage(data: any) {
    if (data?.type === 'identify_result') {
        const identifyResult = data as AuraIdentifyResultMessage;
        lastIdentifyResult = identifyResult;
        settleIdentifyRequest({
            allowed: identifyResult.mic_started === true,
            message: identifyResult.mic_started ? undefined : getFaceGateMessage(identifyResult),
            response: identifyResult,
        });
    }

    messageHandler?.(data);
}

//------This Function handles the Wait For Identify Result---------
export async function ensureAuraMicAuthorized(): Promise<AuraMicAuthorizationResult> {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        return {
            allowed: false,
            message: 'Aura module is not connected.',
        };
    }

    if (pendingIdentifyRequest) {
        return pendingIdentifyRequest;
    }

    pendingIdentifyRequest = new Promise<AuraMicAuthorizationResult>((resolve) => {
        resolvePendingIdentify = resolve;
        identifyTimeoutHandle = setTimeout(() => {
            settleIdentifyRequest({
                allowed: false,
                message: 'Face recognition timed out. Please try again.',
            });
        }, IDENTIFY_TIMEOUT_MS);
    });

    lastIdentifyResult = null;
    ws.send(JSON.stringify({ command: 'identify' }));
    return pendingIdentifyRequest;
}

//------This Function handles the Normalize Backend Url---------
function normalizeBackendUrl(url: string): string {
    const trimmed = (url || '').trim();
    if (!trimmed.startsWith('http://') && !trimmed.startsWith('https://')) {
        return '';
    }
    return trimmed.replace(/\/+$/, '');
}

//------This Function handles the Get Saved Module---------
export async function getSavedModule(): Promise<AuraDevice | null> {
    const saved = await AsyncStorage.getItem(AURA_KEY);
    if (saved) {
        try {
            return JSON.parse(saved);
        } catch { }
    }
    return null;
}

//------This Function handles the Probe Ip---------
async function probeIp(ip: string, port: number): Promise<AuraDevice | null> {
    const controller = new AbortController();
    //------This Function handles the Timeout---------
    const timeout = setTimeout(() => controller.abort(), SCAN_TIMEOUT_MS);

    try {
        const resp = await fetch(`http://${ip}:${port}/health`, {
            signal: controller.signal,
        });
        if (resp.ok) {
            const data = await resp.json();
            if (data.service === 'AURA_MODULE') {
                return {
                    service: data.service,
                    hostname: data.hostname || '',
                    ip: data.ip || ip,
                    ws_port: data.ws_port || port,
                    version: data.version || '1.0.0',
                };
            }
        }
    } catch {
    } finally {
        clearTimeout(timeout);
    }
    return null;
}

//------This Function handles the Get Subnet Prefix---------
async function getSubnetPrefix(): Promise<string | null> {
    try {
        const networkState = await Network.getIpAddressAsync();
        if (networkState) {
            const parts = networkState.split('.');
            if (parts.length === 4) {
                return `${parts[0]}.${parts[1]}.${parts[2]}`;
            }
        }
    } catch { }
    return null;
}

//------This Function handles the Normalize Module---------
function normalizeModule(module: BackendAuraModule): AuraDevice | null {
    if (!module || !module.ip || !module.port) {
        return null;
    }

    return {
        service: 'AURA_MODULE',
        hostname: module.patient_uid || '',
        ip: module.ip,
        ws_port: module.port,
        port: module.port,
        version: '1.0.0',
    };
}

//------This Function handles the Discover Via Backend---------
async function discoverViaBackend(): Promise<AuraDevice[]> {
    try {
        const response = await api.get('/aura/discover', {
            params: { status: 'online' },
        });

        const modules = Array.isArray(response?.data?.modules) ? response.data.modules : [];
        const devices: AuraDevice[] = [];
        const seen = new Set<string>();

        for (const module of modules) {
            const normalized = normalizeModule(module as BackendAuraModule);
            if (!normalized) {
                continue;
            }

            const key = `${normalized.ip}:${normalized.ws_port}`;
            if (seen.has(key)) {
                continue;
            }

            seen.add(key);
            devices.push(normalized);
        }

        return devices;
    } catch {
        return [];
    }
}

//------This Function handles the Scan For Aura Module---------
export async function scanForAuraModule(
    onProgress?: (percent: number) => void,
    onDeviceFound?: (device: AuraDevice) => void,
): Promise<void> {
    const emitted = new Set<string>();
    //------This Function handles the Emit Device---------
    const emitDevice = (device: AuraDevice) => {
        const key = `${device.ip}:${device.ws_port}`;
        if (emitted.has(key)) {
            return;
        }
        emitted.add(key);
        onDeviceFound?.(device);
    };

    const backendDevices = await discoverViaBackend();
    for (const device of backendDevices) {
        emitDevice(device);
    }
    onProgress?.(5);

    const saved = await getSavedModule();
    if (saved) {
        const verified = await probeIp(saved.ip, saved.ws_port);
        if (verified) {
            emitDevice(verified);
        }
    }

    const subnet = await getSubnetPrefix();
    if (!subnet) {
        onProgress?.(100);
        return;
    }

    const priorityEndings = [1, 2, 100, 101, 102, 103, 104, 105, 50, 51, 200, 150];

    for (const ending of priorityEndings) {
        const ip = `${subnet}.${ending}`;
        const found = await probeIp(ip, AURA_PORT);
        if (found) {
            emitDevice(found);
        }
    }
    onProgress?.(15);

    const BATCH_SIZE = 20;
    const allIps: string[] = [];
    for (let i = 2; i <= 254; i++) {
        if (!priorityEndings.includes(i)) {
            allIps.push(`${subnet}.${i}`);
        }
    }

    for (let batchStart = 0; batchStart < allIps.length; batchStart += BATCH_SIZE) {
        const batch = allIps.slice(batchStart, batchStart + BATCH_SIZE);
        //------This Function handles the Results---------
        const results = await Promise.all(batch.map((ip) => probeIp(ip, AURA_PORT)));

        for (const result of results) {
            if (result) {
                emitDevice(result);
            }
        }

        const percent = Math.min(15 + Math.round(((batchStart + BATCH_SIZE) / allIps.length) * 85), 99);
        onProgress?.(percent);
    }

    onProgress?.(100);
}

//------This Function handles the Verify Aura Module---------
export async function verifyAuraModule(ip: string, port: number = AURA_PORT): Promise<AuraDevice | null> {
    return probeIp(ip, port);
}

//------This Function handles the Save Aura Address---------
export async function saveAuraAddress(device: AuraDevice) {
    await AsyncStorage.setItem(AURA_KEY, JSON.stringify(device));
}

//------This Function handles the Connect To Aura---------
export function connectToAura(
    ip: string,
    port: number,
    patientUid: string,
    authToken: string,
    backendUrl?: string,
    onMessage?: (data: any) => void,
    onStateChange?: (state: ConnectionState) => void,
): WebSocket {
    
    storedIp = ip;
    storedPort = port;
    storedPatientUid = patientUid;
    storedAuthToken = authToken;
    storedBackendUrl = normalizeBackendUrl(backendUrl || storedBackendUrl);
    messageHandler = onMessage || null;
    stateChangeHandler = onStateChange || null;
    
    const url = `ws://${ip}:${port}/ws`;
    ws = new WebSocket(url);
    connectionState = 'connecting';
    stateChangeHandler?.('connecting');

    ws.onopen = () => {
        
        reconnectAttempts = 0;
        connectionState = 'connected';
        stateChangeHandler?.('connected');
        console.log('[AURA] WebSocket connected');
        lastIdentifyResult = null;
        resetIdentifyRequest();
        
        const connectPayload: Record<string, string> = {
            command: 'connect',
            patient_uid: patientUid,
            auth_token: authToken,
        };
        if (storedBackendUrl) {
            connectPayload.backend_url = storedBackendUrl;
        }
        ws?.send(JSON.stringify(connectPayload));
    };

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            dispatchAuraMessage(data);
        } catch { }
    };

    ws.onerror = (event) => {
        console.error('[AURA] WebSocket error:', event);
    };

    ws.onclose = (event) => {
        const wasConnected = connectionState === 'connected';
        connectionState = 'disconnected';
        stateChangeHandler?.('disconnected');
        lastIdentifyResult = null;
        settleIdentifyRequest({
            allowed: false,
            message: 'Aura module disconnected before face recognition completed.',
        });
        
        console.log('[AURA] WebSocket closed, attempting reconnection...');
        
        
        if (wasConnected || reconnectAttempts > 0) {
            attemptReconnection();
        } else if (reconnectAttempts === 0) {
            
            attemptReconnection();
        }
    };
    
    return ws;
}


//------This Function handles the Attempt Reconnection---------
const attemptReconnection = () => {
    if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
        console.error('[AURA] Max reconnection attempts reached');
        connectionState = 'disconnected';
        stateChangeHandler?.('disconnected');
        return;
    }
    
    const delay = RECONNECT_DELAYS[Math.min(reconnectAttempts, RECONNECT_DELAYS.length - 1)];
    connectionState = 'reconnecting';
    stateChangeHandler?.('reconnecting');
    reconnectAttempts++;
    
    console.log(`[AURA] Attempting reconnection ${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS} in ${delay}ms...`);
    
    setTimeout(() => {
        if (storedIp && storedPort) {
            try {
                connectToAura(
                    storedIp,
                    storedPort,
                    storedPatientUid,
                    storedAuthToken,
                    storedBackendUrl,
                    messageHandler ?? undefined,
                    stateChangeHandler ?? undefined
                );
            } catch (err: unknown) {
                console.log('[AURA] Reconnection failed, will retry...');
            }
        }
    }, delay);
};

//------This Function handles the Send Aura Command---------
export async function sendAuraCommand(command: string, extra: Record<string, any> = {}): Promise<boolean> {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        return false;
    }

    if (command === 'identify') {
        const authorization = await ensureAuraMicAuthorized();
        return Boolean(authorization.response);
    }

    if (command === 'start_listening' || command === 'live_transcription_start') {
        const authorization = await ensureAuraMicAuthorized();
        if (!authorization.allowed) {
            dispatchAuraMessage({
                type: command === 'start_listening' ? 'listening' : 'live_transcription',
                status: 'denied',
                error: 'face_not_recognized',
                message: authorization.message || getFaceGateMessage(lastIdentifyResult || undefined),
            });
            return false;
        }
    }

    ws.send(JSON.stringify({ command, ...extra }));
    return true;
}

//------This Function handles the Disconnect Aura---------
export function disconnectAura() {
    
    reconnectAttempts = MAX_RECONNECT_ATTEMPTS; 
    connectionState = 'disconnected';
    stateChangeHandler?.('disconnected');
    lastIdentifyResult = null;
    settleIdentifyRequest({
        allowed: false,
        message: 'Aura module disconnected.',
    });
    
    if (ws) {
        ws.close();
        ws = null;
    }
}

//------This Function handles the Is Aura Connected---------
export function isAuraConnected(): boolean {
    return ws !== null && ws.readyState === WebSocket.OPEN;
}

//------This Function handles the Trigger Aura Face Recognition---------
export async function triggerAuraFaceRecognition(
    relatives?: Array<{ id: string; name: string; relationship?: string }>
): Promise<{
    success: boolean;
    identifiedFaces?: Array<{
        person_id: string;
        person_name: string;
        confidence: number;
        relationship?: string;
    }>;
    personId?: string;
    personName?: string;
    confidence?: number;
    error?: string;
}> {
    const api = (await import('./api')).default;

    try {
        
        const payload: { relatives?: Array<{ id: string; name: string; relationship?: string }> } = {};
        
        
        if (relatives && relatives.length > 0) {
            payload.relatives = relatives.map(r => ({
                id: r.id,
                name: r.name,
                relationship: r.relationship || ''
            }));
        }
        
        
        const response = await api.post('/aura/identify_person', payload, {
            timeout: 30000
        });

        const data = response.data;

        if (data.success && data.identified_faces && data.identified_faces.length > 0) {
            const firstFace = data.identified_faces[0];
            return {
                success: true,
                identifiedFaces: data.identified_faces,
                personId: firstFace.person_id,
                personName: firstFace.person_name,
                confidence: firstFace.confidence,
            };
        } else if (data.success === false && data.error === 'no_face_detected') {
            return {
                success: false,
                error: 'No face detected in camera. Please position yourself in front of the camera.',
            };
        } else if (data.success === false && data.error === 'no_camera_frame') {
            return {
                success: false,
                error: 'Aura module camera is not available. Please check the camera connection.',
            };
        } else {
            return {
                success: false,
                error: 'Face recognition completed but no match found.',
            };
        }
    } catch (err: any) {
        if (err.response?.status === 404) {
            return {
                success: false,
                error: 'Aura module not registered. Please ensure the module is connected.',
            };
        } else if (err.response?.status === 503) {
            return {
                success: false,
                error: 'Aura module is offline. Please check the module connection.',
            };
        } else if (err.response?.status === 502) {
            return {
                success: false,
                error: err.response?.data?.detail || 'Aura module request failed. Please try again.',
            };
        } else if (err.response?.status === 504) {
            return {
                success: false,
                error: 'Face recognition timed out. Please try again.',
            };
        } else if (err.code === 'ECONNABORTED' || err.message?.includes('timeout')) {
            return {
                success: false,
                error: 'Backend connection timed out. Please try again.',
            };
        } else {
            return {
                success: false,
                error: 'Failed to connect to backend for face recognition.',
            };
        }
    }
}
