import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

class CptPtpInfoLoader:
    def __init__(self, config_path: Path):
        self._cpt_data: Dict[str, Dict[str, Any]] = {}
        
        # Pre-indexed mappings for O(1) lookups
        # Format: { "cpt_code": { "primary_code": "modifier_indicator" } }
        self._bundled_into_index: Dict[str, Dict[str, str]] = {}
        
        # Format: { "cpt_code": { "bundled_code": "modifier_indicator" } }
        self._bundles_others_index: Dict[str, Dict[str, str]] = {}
        
        self._load(config_path)

    def _load(self, config_path: Path) -> None:
        if not config_path.exists():
            logger.warning(f"File not found: {config_path}")
            return
            
        try:
            with open(config_path, encoding="utf-8") as f:
                raw_data = json.load(f)
            
            if isinstance(raw_data, list):
                for item in raw_data:
                    cpt = item.get("cpt_code")
                    if cpt:
                        self._cpt_data[cpt] = item
                        
                        # Pre-index bundled_into relationships
                        self._bundled_into_index[cpt] = {}
                        ptp_data = item.get("ptp", {})
                        
                        for bi in ptp_data.get("bundled_into", []):
                            primary = bi.get("primary_code")
                            if primary:
                                self._bundled_into_index[cpt][primary] = bi.get("modifier_indicator", "")
                                
                        # Pre-index bundles_others relationships
                        self._bundles_others_index[cpt] = {}
                        for bo in ptp_data.get("bundles_others", []):
                            bundled = bo.get("bundled_code")
                            if bundled:
                                self._bundles_others_index[cpt][bundled] = bo.get("modifier_indicator", "")
            else:
                logger.warning(f"Invalid JSON structure in {config_path}. Expected a list of dictionaries.")
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing JSON from {config_path}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error reading {config_path}: {e}")

    def get_cpt_info(self, cpt_code: str) -> Optional[Dict[str, Any]]:
        return self._cpt_data.get(cpt_code)

    def has_cpt(self, cpt_code: str) -> bool:
        return cpt_code in self._cpt_data

    def get_bundled_into(self, cpt_code: str) -> List[Dict[str, str]]:
        info = self.get_cpt_info(cpt_code)
        if info and "ptp" in info:
            return info["ptp"].get("bundled_into", [])
        return []

    def get_bundles_others(self, cpt_code: str) -> List[Dict[str, str]]:
        info = self.get_cpt_info(cpt_code)
        if info and "ptp" in info:
            return info["ptp"].get("bundles_others", [])
        return []

    def is_bundled_into(self, cpt_code: str, primary_cpt: str) -> bool:
        """Checks if cpt_code is bundled into primary_cpt in O(1) time."""
        if cpt_code in self._bundled_into_index:
            return primary_cpt in self._bundled_into_index[cpt_code]
        return False

    def bundles_code(self, cpt_code: str, secondary_cpt: str) -> bool:
        """Checks if cpt_code bundles secondary_cpt in O(1) time."""
        if cpt_code in self._bundles_others_index:
            return secondary_cpt in self._bundles_others_index[cpt_code]
        return False

    def get_modifier_indicator(self, cpt_code: str, related_cpt: str) -> Optional[str]:
        """
        Gets the modifier indicator between two codes in O(1) time.
        First checks if cpt_code is bundled into related_cpt.
        If not, checks if cpt_code bundles related_cpt.
        """
        # Check bundled_into relationship first
        if cpt_code in self._bundled_into_index and related_cpt in self._bundled_into_index[cpt_code]:
            return self._bundled_into_index[cpt_code][related_cpt]
            
        # Check bundles_others relationship
        if cpt_code in self._bundles_others_index and related_cpt in self._bundles_others_index[cpt_code]:
            return self._bundles_others_index[cpt_code][related_cpt]
            
        return None

    def get_all_codes(self) -> List[str]:
        return list(self._cpt_data.keys())
