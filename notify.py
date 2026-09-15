from firebase_admin import messaging
import logging

logger = logging.getLogger(__name__)

def send_sos_notification(tokens: list[str], device_name: str, ) -> bool:
    """
    Firebase Cloud Messaging (FCM) を使用してFlutterアプリにプッシュ通知を送信する。
    送信成功が1つ以上あればtrueを返す。
    """

    if not tokens:
        return False

    message = messaging.MulticastMessage(
        notification=messaging.Notification(
            title="【緊急】SOS通知",
            body=f"「{device_name}」からSOS信号を受信しました。"
        ),
        data={
            "type": "sos",
            "device_name": device_name
        },
        tokens=tokens
    )

    response = messaging.send_each_for_multicast(message)
    logger.info(f"FCM Multicast result: {response.success_count} success, {response.failure_count} failure.")

    return response.success_count > 0
