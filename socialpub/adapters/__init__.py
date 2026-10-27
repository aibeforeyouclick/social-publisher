from .instagram import InstagramAdapter
from .skeletons import FacebookAdapter, LinkedInAdapter, TikTokAdapter, XAdapter
from .youtube import YouTubeAdapter

REGISTRY = {a.name: a for a in (InstagramAdapter(), YouTubeAdapter(), FacebookAdapter(), TikTokAdapter(),
                                LinkedInAdapter(), XAdapter())}
