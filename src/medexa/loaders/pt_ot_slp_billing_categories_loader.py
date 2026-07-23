import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

class PtOtSlpBillingCategoriesLoader:
    def __init__(self, config_path: Path):
        self._cpt_data: Dict[str, Dict[str, Any]] = {}
        self._raw_data: Dict[str, Any] = {}
        self._load(config_path)

    def _load(self, config_path: Path) -> None:
        if not config_path.exists():
            logger.warning(f"File not found: {config_path}")
            return
            
        try:
            with open(config_path, encoding="utf-8") as f:
                raw_data = json.load(f)
            
            if isinstance(raw_data, dict):
                self._raw_data = raw_data
                categories = raw_data.get("categories", [])
                if isinstance(categories, list):
                    for category in categories:
                        if isinstance(category, dict):
                            codes = category.get("codes", [])
                            # Exclude the codes list from the info stored per CPT to save memory,
                            # but retain all other fields
                            category_info = {k: v for k, v in category.items() if k != "codes"}
                            for cpt in codes:
                                self._cpt_data[cpt] = category_info
            else:
                logger.warning(f"Invalid JSON structure in {config_path}. Expected a root dictionary.")
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing JSON from {config_path}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error reading {config_path}: {e}")

    # --- Root level metadata methods ---

    def get_total_codes(self) -> Optional[int]:
        return self._raw_data.get("total_codes")

    def get_all_billing_rule_definitions(self) -> Dict[str, str]:
        return self._raw_data.get("billing_rule_definitions", {})

    def get_billing_rule_definition(self, rule_name: str) -> Optional[str]:
        definitions = self.get_all_billing_rule_definitions()
        return definitions.get(rule_name)

    def get_summary(self) -> Dict[str, int]:
        return self._raw_data.get("summary", {})

    # --- CPT specific getter methods ---

    def get_cpt_info(self, cpt_code: str) -> Optional[Dict[str, Any]]:
        return self._cpt_data.get(cpt_code)

    def has_cpt(self, cpt_code: str) -> bool:
        return cpt_code in self._cpt_data

    def get_category_id(self, cpt_code: str) -> Optional[str]:
        info = self.get_cpt_info(cpt_code)
        return info.get("category_id") if info else None

    def get_billing_rule(self, cpt_code: str) -> Optional[str]:
        info = self.get_cpt_info(cpt_code)
        return info.get("billing_rule") if info else None

    def get_description(self, cpt_code: str) -> Optional[str]:
        info = self.get_cpt_info(cpt_code)
        return info.get("description") if info else None

    def get_segment_size_minutes(self, cpt_code: str) -> Optional[int]:
        info = self.get_cpt_info(cpt_code)
        return info.get("segment_size_minutes") if info else None

    def get_unit_threshold_minutes(self, cpt_code: str) -> Optional[int]:
        info = self.get_cpt_info(cpt_code)
        return info.get("unit_threshold_minutes") if info else None

    def get_min_time_for_1_unit(self, cpt_code: str) -> Optional[str]:
        info = self.get_cpt_info(cpt_code)
        return info.get("min_time_for_1_unit") if info else None

    def get_max_units_allowed(self, cpt_code: str) -> Optional[str]:
        info = self.get_cpt_info(cpt_code)
        return info.get("max_units_allowed") if info else None

    def get_time_band(self, cpt_code: str) -> Optional[str]:
        info = self.get_cpt_info(cpt_code)
        return info.get("time_band") if info else None

    def get_all_codes(self) -> List[str]:
        return list(self._cpt_data.keys())
