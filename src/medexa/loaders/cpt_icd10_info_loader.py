import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

class CptIcd10InfoLoader:
    def __init__(self, config_path: Path):
        # Store raw info if needed for get_cpt_info
        self._cpt_data: Dict[str, Dict[str, Any]] = {}
        # Precompute sets for O(1) valid ICD-10 lookups
        self._valid_icd10_sets: Dict[str, Set[str]] = {}
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
                        # Extract codes into a set for fast lookup
                        icd10_list = item.get("valid_icd10_codes", [])
                        valid_set = {
                            icd.get("code") for icd in icd10_list if isinstance(icd, dict) and icd.get("code")
                        }
                        self._valid_icd10_sets[cpt] = valid_set
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

    def get_valid_icd10_codes(self, cpt_code: str) -> List[str]:
        """Returns a list of valid ICD-10 code strings for the given CPT."""
        valid_set = self._valid_icd10_sets.get(cpt_code)
        return list(valid_set) if valid_set is not None else []

    def is_valid_icd10(self, cpt_code: str, icd10_code: str) -> bool:
        """Checks if the given ICD-10 code is valid for the given CPT code in O(1) time."""
        valid_set = self._valid_icd10_sets.get(cpt_code)
        return icd10_code in valid_set if valid_set is not None else False

    def get_all_codes(self) -> List[str]:
        return list(self._cpt_data.keys())
