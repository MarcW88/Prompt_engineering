import re
import hashlib
from dataclasses import dataclass, field
from typing import List, Set, Tuple, Optional

from models.raw_item import RawItem
from utils.config_loader import Config, FiltersConfig
from utils.logger import get_logger


@dataclass
class RejectedItem:
    """Item rejeté avec raison"""
    item: RawItem
    reason: str
    rule: str


@dataclass
class FilterResult:
    """Résultat du filtrage"""
    accepted: List[RawItem] = field(default_factory=list)
    rejected: List[RejectedItem] = field(default_factory=list)
    
    @property
    def stats(self) -> dict:
        return {
            "accepted": len(self.accepted),
            "rejected": len(self.rejected),
            "rejection_reasons": self._count_reasons()
        }
    
    def _count_reasons(self) -> dict:
        reasons = {}
        for item in self.rejected:
            reasons[item.rule] = reasons.get(item.rule, 0) + 1
        return reasons


class QualityFilter:
    """Filtre de qualité basé sur des règles simples"""
    
    def __init__(self, config: Config):
        self.config = config
        self.filters_config = config.filters
        self.logger = get_logger("QualityFilter")
        self.seen_hashes: Set[str] = set()
    
    def filter(self, items: List[RawItem]) -> FilterResult:
        """Filtre les items et retourne accepted/rejected"""
        result = FilterResult()
        
        for item in items:
            rejection = self._check_item(item)
            
            if rejection:
                result.rejected.append(RejectedItem(
                    item=item,
                    reason=rejection[0],
                    rule=rejection[1]
                ))
            else:
                result.accepted.append(item)
        
        self.logger.info(f"Filtered: {len(result.accepted)} accepted, {len(result.rejected)} rejected")
        return result
    
    def _check_item(self, item: RawItem) -> Optional[Tuple[str, str]]:
        """Vérifie un item, retourne (reason, rule) si rejeté, None si accepté"""
        
        text = item.raw_text
        
        if len(text) < self.filters_config.min_text_length:
            return (f"Text too short ({len(text)} < {self.filters_config.min_text_length})", "min_length")
        
        if len(text) > self.filters_config.max_text_length:
            return (f"Text too long ({len(text)} > {self.filters_config.max_text_length})", "max_length")
        
        text_hash = hashlib.md5(text.lower().encode()).hexdigest()
        if text_hash in self.seen_hashes:
            return ("Duplicate content", "duplicate")
        self.seen_hashes.add(text_hash)
        
        for pattern in self.filters_config.spam_patterns:
            if pattern.lower() in text.lower():
                return (f"Spam pattern detected: {pattern}", "spam")
        
        if self.filters_config.accepted_languages:
            try:
                from langdetect import detect
                detected_lang = detect(text)
                if detected_lang not in self.filters_config.accepted_languages:
                    return (f"Language mismatch ({detected_lang})", "language")
            except Exception:
                pass
        
        return None
    
    def reset(self):
        """Reset le filtre (vide le cache de hashes)"""
        self.seen_hashes.clear()
