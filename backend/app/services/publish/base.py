from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from ...models import Account, Post, PublishJob


@dataclass
class PublishPayload:
    job: PublishJob
    post: Post
    account: Account
    video: Path
    package_root: Path
    cover: Path | None = None


@dataclass
class PublishResult:
    success: bool
    video_id: str = ""
    log: str = ""
    status: str = "submitted"
    platform_url: str = ""


class PublishChannel(ABC):
    @abstractmethod
    def publish(self, payload: PublishPayload) -> PublishResult:
        raise NotImplementedError
