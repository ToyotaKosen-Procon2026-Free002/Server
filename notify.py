from firebase_admin import messaging
import logging

logger = logging.getLogger(__name__)

def send_sos_notification(tokens: list[str], device_name: str) -> bool:
    """
    Firebase Cloud Messaging (FCM) を使用してFlutterアプリにプッシュ通知を送信する。
    Android / iOS 共に高優先度（即時配信・ポップアップ表示）の設定を付与する。
    送信成功が1つ以上あればtrueを返す。
    """
    if not tokens:
        return False

    # 1. Android用の高優先度設定（重要度最大・チャンネル指定）
    android_config = messaging.AndroidConfig(
        priority="high",
        notification=messaging.AndroidNotification(
            channel_id="sos_channel",  # Flutter側と一致させる通知チャンネルID
            priority="high",           # ヘッズアップ通知（画面上部ポップアップ）を強制
            default_sound=True,
            default_vibrate_timings=True,
        )
    )

    # 2. iOS/APNs用の高優先度設定（即時配信ヘッダーとバナー許可）
    apns_config = messaging.APNSConfig(
        headers={"apns-priority": "10"},  # 10 = 即時配信（5にすると省電力時に遅延される）
        payload=messaging.APNSPayload(
            aps=messaging.Aps(
                alert=messaging.ApsAlert(
                    title="【緊急】SOS通知",
                    body=f"「{device_name}」からSOS信号を受信しました。",
                ),
                sound="default",
                badge=1,
                content_available=True,
            )
        )
    )

    message = messaging.MulticastMessage(
        notification=messaging.Notification(
            title="【緊急】SOS通知",
            body=f"「{device_name}」からSOS信号を受信しました。"
        ),
        data={
            "type": "sos",
            "device_name": device_name
        },
        tokens=tokens,
        android=android_config,
        apns=apns_config
    )

    try:
        response = messaging.send_each_for_multicast(message)
        logger.info(f"FCM Multicast result: {response.success_count} success, {response.failure_count} failure.")
        return response.success_count > 0
    except Exception as e:
        logger.error(f"FCM送信中に例外が発生しました: {e}")
        return False
