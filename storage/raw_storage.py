import sqlite3
import json
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

from models.raw_item import RawItem, SourceType
from utils.logger import get_logger


class RawStorage:
    """Stockage SQLite pour les données brutes scrapées"""
    
    def __init__(self, db_path: str = "./output/raw/scraping.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.logger = get_logger("RawStorage")
        self._init_db()
    
    def _init_db(self):
        """Initialise la base de données"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS raw_items (
                    id TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    brand TEXT,
                    theme TEXT,
                    raw_text TEXT NOT NULL,
                    url TEXT,
                    title TEXT,
                    rating INTEGER,
                    date TEXT,
                    metadata TEXT,
                    scraped_at TEXT NOT NULL,
                    client_slug TEXT NOT NULL
                )
            """)
            
            conn.execute("CREATE INDEX IF NOT EXISTS idx_source ON raw_items(source_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_platform ON raw_items(platform)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_client ON raw_items(client_slug)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_url ON raw_items(url)")
            
            conn.commit()
        
        self.logger.info(f"Database initialized: {self.db_path}")
    
    def save(self, items: List[RawItem]) -> int:
        """Sauvegarde les items, retourne le nombre d'items sauvegardés"""
        if not items:
            return 0
        
        saved = 0
        
        with sqlite3.connect(self.db_path) as conn:
            for item in items:
                try:
                    if not self.exists_item(item, conn):
                        conn.execute("""
                            INSERT INTO raw_items 
                            (id, source_type, platform, brand, theme, raw_text, url, title, rating, date, metadata, scraped_at, client_slug)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            item.id,
                            item.source_type.value,
                            item.platform,
                            item.brand,
                            item.theme,
                            item.raw_text,
                            item.url,
                            item.title,
                            item.rating,
                            item.date.isoformat() if item.date else None,
                            json.dumps(item.metadata),
                            item.scraped_at.isoformat(),
                            item.client_slug
                        ))
                        saved += 1
                except sqlite3.IntegrityError:
                    pass
                except Exception as e:
                    self.logger.error(f"Error saving item {item.id}: {e}")
            
            conn.commit()
        
        self.logger.info(f"Saved {saved}/{len(items)} items")
        return saved
    
    def exists_item(self, item: RawItem, conn: Optional[sqlite3.Connection] = None) -> bool:
        should_close = False
        if conn is None:
            conn = sqlite3.connect(self.db_path)
            should_close = True
        try:
            cursor = conn.execute(
                "SELECT 1 FROM raw_items WHERE client_slug = ? AND platform = ? AND raw_text = ? LIMIT 1",
                (item.client_slug, item.platform, item.raw_text)
            )
            return cursor.fetchone() is not None
        finally:
            if should_close:
                conn.close()

    def exists(self, url: str, conn: Optional[sqlite3.Connection] = None) -> bool:
        """Vérifie si une URL existe déjà"""
        if not url:
            return False
        
        should_close = False
        if conn is None:
            conn = sqlite3.connect(self.db_path)
            should_close = True
        
        try:
            cursor = conn.execute("SELECT 1 FROM raw_items WHERE url = ? LIMIT 1", (url,))
            return cursor.fetchone() is not None
        finally:
            if should_close:
                conn.close()
    
    def get_all(self, filters: Optional[Dict[str, Any]] = None) -> List[RawItem]:
        """Récupère tous les items avec filtres optionnels"""
        query = "SELECT * FROM raw_items"
        params = []
        
        if filters:
            conditions = []
            if "source_type" in filters:
                conditions.append("source_type = ?")
                params.append(filters["source_type"])
            if "platform" in filters:
                conditions.append("platform = ?")
                params.append(filters["platform"])
            if "client_slug" in filters:
                conditions.append("client_slug = ?")
                params.append(filters["client_slug"])
            
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
        
        items = []
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            
            for row in cursor:
                try:
                    item = RawItem(
                        id=row["id"],
                        source_type=SourceType(row["source_type"]),
                        platform=row["platform"],
                        brand=row["brand"],
                        theme=row["theme"],
                        raw_text=row["raw_text"],
                        url=row["url"],
                        title=row["title"],
                        rating=row["rating"],
                        date=datetime.fromisoformat(row["date"]) if row["date"] else None,
                        metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                        scraped_at=datetime.fromisoformat(row["scraped_at"]),
                        client_slug=row["client_slug"]
                    )
                    items.append(item)
                except Exception as e:
                    self.logger.error(f"Error loading item: {e}")
        
        return items
    
    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques de stockage"""
        stats = {
            "total_items": 0,
            "by_source_type": {},
            "by_platform": {},
            "by_client": {}
        }
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM raw_items")
            stats["total_items"] = cursor.fetchone()[0]
            
            cursor = conn.execute("SELECT source_type, COUNT(*) FROM raw_items GROUP BY source_type")
            stats["by_source_type"] = dict(cursor.fetchall())
            
            cursor = conn.execute("SELECT platform, COUNT(*) FROM raw_items GROUP BY platform")
            stats["by_platform"] = dict(cursor.fetchall())
            
            cursor = conn.execute("SELECT client_slug, COUNT(*) FROM raw_items GROUP BY client_slug")
            stats["by_client"] = dict(cursor.fetchall())
        
        return stats
    
    def clear(self, client_slug: Optional[str] = None):
        """Supprime les données (tout ou par client)"""
        with sqlite3.connect(self.db_path) as conn:
            if client_slug:
                conn.execute("DELETE FROM raw_items WHERE client_slug = ?", (client_slug,))
                self.logger.info(f"Cleared data for client: {client_slug}")
            else:
                conn.execute("DELETE FROM raw_items")
                self.logger.info("Cleared all data")
            conn.commit()
