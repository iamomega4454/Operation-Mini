from typing import List, Optional, Dict, Any
import asyncio
from concurrent.futures import ThreadPoolExecutor
from firebase_admin import messaging
from app.models.user import User
import logging

logger = logging.getLogger(__name__)

#------Max concurrent Firebase messaging threads---------
_FCM_EXECUTOR = ThreadPoolExecutor(max_workers=10)


class NotificationService:

#------This Function sends notification---------
    async def send_notification(
        self,
        fcm_token: str,
        title: str,
        body: str,
        data: Optional[Dict[str, str]] = None,
    ) -> bool:
        try:
            
            if data:
                data = {k: str(v) for k, v in data.items()}

            message = messaging.Message(
                notification=messaging.Notification(
                    title=title,
                    body=body,
                ),
                data=data or {},
                token=fcm_token,
                android=messaging.AndroidConfig(
                    priority="high",
                    notification=messaging.AndroidNotification(
                        sound="default",
                        priority="high",
                    ),
                ),
                apns=messaging.APNSConfig(
                    payload=messaging.APNSPayload(
                        aps=messaging.Aps(
                            sound="default",
                        ),
                    ),
                ),
            )

            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(_FCM_EXECUTOR, messaging.send, message)
            logger.info(f"Successfully sent notification to token {fcm_token[:10]}...")
            return True


        except messaging.UnregisteredError:
            logger.warning(f"Token {fcm_token[:10]}... is invalid or expired")
            return False
        except Exception as e:
            logger.error(f"Failed to send notification: {str(e)}")
            return False

#------This Function sends notification to user---------
    async def send_notification_to_user(
        self,
        user_uid: str,
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> int:
        user = await User.find_one(User.firebase_uid == user_uid)
        if not user or not user.fcm_tokens:
            logger.warning(f"No FCM tokens found for user {user_uid}")
            return 0

        success_count = 0
        invalid_tokens = []

        for token in user.fcm_tokens:
            success = await self.send_notification(token, title, body, data)
            if success:
                success_count += 1
            else:
                invalid_tokens.append(token)

        
        if invalid_tokens:
            await self.cleanup_invalid_tokens(user, invalid_tokens)

        return success_count

#------This Function sends bulk notifications---------
    async def send_bulk_notifications(
        self,
        user_uids: List[str],
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> int:
        total_sent = 0
        for uid in user_uids:
            count = await self.send_notification_to_user(uid, title, body, data)
            total_sent += count
        return total_sent

#------This Function cleans up invalid tokens---------
    async def cleanup_invalid_tokens(
        self, user: User, invalid_tokens: List[str]
    ) -> None:
        try:
            user.fcm_tokens = [
                token for token in user.fcm_tokens if token not in invalid_tokens
            ]
            await user.save()
            logger.info(
                f"Removed {len(invalid_tokens)} invalid token(s) from user {user.firebase_uid}"
            )
        except Exception as e:
            logger.error(f"Failed to cleanup invalid tokens: {str(e)}")

#------This Function sends SOS notification---------
    async def send_sos_notification(
        self,
        caregiver_uid: str,
        patient_name: str,
        patient_uid: str,
        sos_id: str,
        location: Optional[Dict[str, Any]] = None,
    ) -> int:
        data = {
            "type": "sos",
            "sos_id": sos_id,
            "patient_uid": patient_uid,
        }
        if location:
            data["latitude"] = str(location.get("latitude", ""))
            data["longitude"] = str(location.get("longitude", ""))

        return await self.send_notification_to_user(
            user_uid=caregiver_uid,
            title="🚨 Emergency Alert",
            body=f"{patient_name} triggered an SOS alert",
            data=data,
        )

#------This Function sends medication reminder---------
    async def send_medication_reminder(
        self,
        patient_uid: str,
        medication_name: str,
        medication_id: str,
    ) -> int:
        return await self.send_notification_to_user(
            user_uid=patient_uid,
            title="💊 Medication Reminder",
            body=f"Time to take {medication_name}",
            data={
                "type": "medication",
                "medication_id": medication_id,
            },
        )

#------This Function sends geofence alert---------
    async def send_geofence_alert(
        self,
        caregiver_uid: str,
        patient_name: str,
        patient_uid: str,
        event_type: str,
        region_name: str,
    ) -> int:
        if event_type == "exit":
            title = "⚠️ Location Alert"
            body = f"{patient_name} left the {region_name}"
        else:
            title = "📍 Location Update"
            body = f"{patient_name} entered the {region_name}"

        return await self.send_notification_to_user(
            user_uid=caregiver_uid,
            title=title,
            body=body,
            data={
                "type": "geofence",
                "patient_uid": patient_uid,
                "event_type": event_type,
                "region_name": region_name,
            },
        )


notification_service = NotificationService()


#------This Function shuts down the FCM thread pool---------
def shutdown_executor() -> None:
    """Gracefully shut down the shared FCM thread pool."""
    _FCM_EXECUTOR.shutdown(wait=False)
    logger.info("FCM executor shut down")
