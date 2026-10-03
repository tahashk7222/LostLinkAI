from enum import Enum


class Role(str, Enum):
    USER = "USER"
    ADMIN = "ADMIN"


class ReportType(str, Enum):
    LOST = "LOST"
    FOUND = "FOUND"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    POTENTIAL_MATCH = "POTENTIAL_MATCH"
    CONNECTED = "CONNECTED"
    RECOVERED = "RECOVERED"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"
    DEACTIVATED = "DEACTIVATED"  # moderation


class AIStatus(str, Enum):
    PENDING = "PENDING"
    DONE = "DONE"
    FAILED = "FAILED"


class MatchStatus(str, Enum):
    POTENTIAL_MATCH = "POTENTIAL_MATCH"
    VERIFICATION_PENDING = "VERIFICATION_PENDING"
    AWAITING_FINDER_REVIEW = "AWAITING_FINDER_REVIEW"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    DISMISSED = "DISMISSED"  # owner says "not mine"


class CaseStatus(str, Enum):
    CONNECTED = "CONNECTED"
    RECOVERED = "RECOVERED"
    CLOSED = "CLOSED"


class AttributeSource(str, Enum):
    USER = "USER"
    AI = "AI"


class FlagStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"
