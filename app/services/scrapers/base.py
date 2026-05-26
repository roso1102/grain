from abc import ABC, abstractmethod
from typing import Dict, Optional

class BaseScraper(ABC):
    name: str = ""
    @abstractmethod
    def can_handle(self, url: str) -> bool: ...
    @abstractmethod
    async def scrape(self, url: str) -> Optional[Dict[str, str]]: ...