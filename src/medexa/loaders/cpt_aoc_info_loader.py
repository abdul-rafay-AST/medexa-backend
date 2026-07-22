import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from medexa.ports.cpt_metadata import CptAocPort

logger = logging.getLogger(__name__)

class CptAocInfoLoader(CptAocPort):
    def __init__(self, config_path: Path):
        self._cpt_data: Dict[str, Dict[str, Any]] = {}
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

    def is_addon_code(self, cpt_code: str) -> bool:
        info = self.get_cpt_info(cpt_code)
        return bool(info.get("isAddonCode")) if info else False

    def get_parent_code(self, cpt_code: str) -> Optional[str]:
        info = self.get_cpt_info(cpt_code)
        return info.get("parentCode") if info else None

    def get_allowed_addons(self, cpt_code: str) -> List[str]:
        info = self.get_cpt_info(cpt_code)
        return info.get("addonCodesAllowed", []) if info else []

    def get_billing_rule(self, cpt_code: str) -> Optional[str]:
        info = self.get_cpt_info(cpt_code)
        return info.get("billingRule") if info else None

    def get_billing_time(self, cpt_code: str) -> Optional[str]:
        info = self.get_cpt_info(cpt_code)
        return info.get("billingTime") if info else None

    def get_all_codes(self) -> List[str]:
        return list(self._cpt_data.keys())
