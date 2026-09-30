from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any
import uuid


class SourceType(Enum):
    FORUM = "forum"
    REVIEW = "review"
    SERP = "serp"
    QA = "qa"


@dataclass
class RawItem:
    """Structure de données brute pour un élément scrapé"""
    
    source_type: SourceType
    platform: str
    raw_text: str
    url: str
    
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    brand: Optional[str] = None
    theme: Optional[str] = None
    title: Optional[str] = None
    rating: Optional[int] = None
    date: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    scraped_at: datetime = field(default_factory=datetime.now)
    client_slug: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour stockage"""
        return {
            "id": self.id,
            "source_type": self.source_type.value,
            "platform": self.platform,
            "brand": self.brand,
            "theme": self.theme,
            "raw_text": self.raw_text,
            "url": self.url,
            "title": self.title,
            "rating": self.rating,
            "date": self.date.isoformat() if self.date else None,
            "metadata": self.metadata,
            "scraped_at": self.scraped_at.isoformat(),
            "client_slug": self.client_slug
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RawItem":
        """Crée un RawItem depuis un dictionnaire"""
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            source_type=SourceType(data["source_type"]),
            platform=data["platform"],
            brand=data.get("brand"),
            theme=data.get("theme"),
            raw_text=data["raw_text"],
            url=data["url"],
            title=data.get("title"),
            rating=data.get("rating"),
            date=datetime.fromisoformat(data["date"]) if data.get("date") else None,
            metadata=data.get("metadata", {}),
            scraped_at=datetime.fromisoformat(data["scraped_at"]) if data.get("scraped_at") else datetime.now(),
            client_slug=data.get("client_slug", "")
        )
