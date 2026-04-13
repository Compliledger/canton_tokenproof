from .GENIUS_v1 import evaluate as genius_v1
from .CLARITY_v1 import evaluate as clarity_v1
from .SEC_v1 import evaluate as sec_v1

REGISTRY = {
    "GENIUS_v1": genius_v1,
    "CLARITY_v1": clarity_v1,
    "SEC_CLASSIFICATION_v1": sec_v1,
}
