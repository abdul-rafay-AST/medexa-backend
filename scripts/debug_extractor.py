import pathlib
import sys
import uuid

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from medexa.api.dependencies import get_container  # noqa: E402
from medexa.schemas import SessionState  # noqa: E402
from medexa.utils.time import now_utc  # noqa: E402

container = get_container()
TRANSCRIPT = [
    "Let's start with some soft tissue work on the left shoulder",
    "Now we'll move into functional activities on the left shoulder",
    "Let's finish with a hot pack",
]
state = SessionState(session_id=str(uuid.uuid4()), status="active")
current_time = now_utc()

for text in TRANSCRIPT:
    entities = container.entity_extractor.extract(text, str(uuid.uuid4()))
    print(f"TEXT: {text}")
    print(f"  ENTITIES: {entities}")
    for e in entities:
        print(f"    - matched_phrase={e.matched_phrase}, activity_label={e.activity_label}, possible_cpt={e.possible_cpt}, is_negated={e.is_negated}, is_billable={e.is_billable}")
    
    new_suggestions = container.suggestion_generator.generate(
        session_id=state.session_id,
        entities=entities,
        existing=state.suggestions,
        now=current_time,
    )
    print(f"  SUGGESTIONS: {new_suggestions}")
