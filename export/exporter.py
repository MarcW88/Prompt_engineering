import csv
import json
import re
from pathlib import Path
from typing import List, Dict, Any
from dataclasses import dataclass

from models.raw_item import RawItem
from utils.config_loader import Config
from utils.logger import get_logger


@dataclass
class EnrichedItem:
    """Item enrichi avec métadonnées supplémentaires"""
    item: RawItem
    is_question: bool
    sentiment_hint: str
    
    def to_dict(self) -> Dict[str, Any]:
        base = self.item.to_dict()
        base["is_question"] = self.is_question
        base["sentiment_hint"] = self.sentiment_hint
        return base


class Exporter:
    """Export des données filtrées vers CSV/JSON"""
    
    QUESTION_PATTERNS = [
        r'\?',
        r'^comment\s',
        r'^pourquoi\s',
        r'^quel(le)?s?\s',
        r'^où\s',
        r'^quand\s',
        r'^est-ce que\s',
        r'^qui\s',
        r'^combien\s',
    ]
    
    NEGATIVE_KEYWORDS = [
        "problème", "nul", "mauvais", "déçu", "horrible",
        "arnaque", "éviter", "jamais", "pire", "catastrophe",
        "honte", "scandale", "inacceptable", "inadmissible"
    ]
    
    def __init__(self, config: Config, output_dir: str = "./output"):
        self.config = config
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger = get_logger("Exporter")
    
    def enrich(self, items: List[RawItem]) -> List[EnrichedItem]:
        """Enrichit les items avec is_question et sentiment_hint"""
        enriched = []
        
        for item in items:
            is_question = self._detect_question(item.raw_text, item.title)
            sentiment = self._detect_sentiment(item)
            
            enriched.append(EnrichedItem(
                item=item,
                is_question=is_question,
                sentiment_hint=sentiment
            ))
        
        return enriched
    
    def _detect_question(self, text: str, title: str = None) -> bool:
        """Détecte si le contenu est une question"""
        check_text = f"{title or ''} {text}".lower().strip()
        
        for pattern in self.QUESTION_PATTERNS:
            if re.search(pattern, check_text, re.IGNORECASE):
                return True
        
        return False
    
    def _detect_sentiment(self, item: RawItem) -> str:
        """Détecte le sentiment (negative, neutral, positive)"""
        if item.rating is not None:
            if item.rating <= 2:
                return "negative"
            elif item.rating >= 4:
                return "positive"
        
        text_lower = item.raw_text.lower()
        for keyword in self.NEGATIVE_KEYWORDS:
            if keyword in text_lower:
                return "negative"
        
        return "neutral"
    
    def to_csv(self, items: List[RawItem], filename: str, enrich: bool = True) -> str:
        """Exporte vers CSV"""
        output_path = self.output_dir / "clean" / filename
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        if enrich:
            enriched_items = self.enrich(items)
            data = [item.to_dict() for item in enriched_items]
        else:
            data = [item.to_dict() for item in items]
        
        if not data:
            self.logger.warning("No data to export")
            return str(output_path)
        
        fields = self.config.output.fields or list(data[0].keys())
        
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(data)
        
        self.logger.info(f"Exported {len(data)} items to {output_path}")
        return str(output_path)
    
    def to_json(self, items: List[RawItem], filename: str, enrich: bool = True) -> str:
        """Exporte vers JSON"""
        output_path = self.output_dir / "clean" / filename
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        if enrich:
            enriched_items = self.enrich(items)
            data = [item.to_dict() for item in enriched_items]
        else:
            data = [item.to_dict() for item in items]
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        self.logger.info(f"Exported {len(data)} items to {output_path}")
        return str(output_path)
    
    def export_rejected(self, rejected_items: List, filename: str = "rejected.csv") -> str:
        """Exporte les items rejetés"""
        output_path = self.output_dir / "rejected" / filename
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        if not rejected_items:
            return str(output_path)
        
        fields = ["id", "source_type", "platform", "raw_text", "url", "reason", "rule"]
        
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            
            for rejected in rejected_items:
                row = {
                    "id": rejected.item.id,
                    "source_type": rejected.item.source_type.value,
                    "platform": rejected.item.platform,
                    "raw_text": rejected.item.raw_text[:500],
                    "url": rejected.item.url,
                    "reason": rejected.reason,
                    "rule": rejected.rule
                }
                writer.writerow(row)
        
        self.logger.info(f"Exported {len(rejected_items)} rejected items to {output_path}")
        return str(output_path)
