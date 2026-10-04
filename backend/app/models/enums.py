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


class ModerationReason(str, Enum):
    """Why an admin rejected a report. Stored on the report and shown to admins, never to other users."""
    FAKE_OR_JOKE = "FAKE_OR_JOKE"
    OUTSIDE_UET_AREA = "OUTSIDE_UET_AREA"
    INVALID_ITEM = "INVALID_ITEM"
    INAPPROPRIATE_CONTENT = "INAPPROPRIATE_CONTENT"
    DUPLICATE_REPORT = "DUPLICATE_REPORT"
    INSUFFICIENT_INFORMATION = "INSUFFICIENT_INFORMATION"
    SUSPICIOUS_ACTIVITY = "SUSPICIOUS_ACTIVITY"
    OTHER = "OTHER"


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
    USER = "USER"  # typed by the person in a form field
    RULE = "RULE"  # inferred from free text by deterministic rules (not a learned model)


class FlagStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"
