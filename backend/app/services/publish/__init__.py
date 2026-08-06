from .facebook import FacebookChannel
from .youtube import YouTubeChannel
from .tiktok import TikTokChannel
from .instagram import InstagramChannel

CHANNEL_REGISTRY = {"facebook": FacebookChannel, "instagram": InstagramChannel, "youtube": YouTubeChannel, "tiktok": TikTokChannel}
