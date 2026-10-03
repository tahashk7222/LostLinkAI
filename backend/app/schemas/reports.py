from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import AIStatus, AttributeSource, ReportStatus, ReportType


class ReportBase(BaseModel):
    category: str = Field(min_length=2, max_length=50)
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(min_length=5, max_length=2000)
    color: str | None = Field(default=None, max_length=50)
    brand: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=80)
    distinctive_features: str | None = Field(default=None, max_length=1000)
    private_details: str | None = Field(default=None, max_length=1000)
    date_time: datetime
    location: str = Field(min_length=2, max_length=200)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @field_validator("category", "name", "location", "color", "brand", "model")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v


class ReportCreate(ReportBase):
    report_type: ReportType


class ReportUpdate(BaseModel):
    category: str | None = Field(default=None, min_length=2, max_length=50)
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, min_length=5, max_length=2000)
    color: str | None = Field(default=None, max_length=50)
    brand: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=80)
    distinctive_features: str | None = Field(default=None, max_length=1000)
    private_details: str | None = Field(default=None, max_length=1000)
    date_time: datetime | None = None
    location: str | None = Field(default=None, min_length=2, max_length=200)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    status: ReportStatus | None = None  # only CLOSED allowed for owners


class ImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    url: str


class AttributeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    attribute_name: str
    attribute_value: str
    source: AttributeSource
    confidence: float


class ReportPublic(BaseModel):
    """What any signed-in user may see. No private details, no exact coordinates, no contact info."""

    id: int
    report_type: ReportType
    category: str
    name: str
    description: str
    color: str | None
    brand: str | None
    model: str | None
    distinctive_features: str | None
    date_time: datetime
    location: str
    approx_latitude: float | None
    approx_longitude: float | None
    status: ReportStatus
    created_at: datetime
    reporter_name: str
    images: list[ImageOut]
    is_owner: bool = False


class ReportPrivate(ReportPublic):
    """The report author's own view."""

    private_details: str | None
    latitude: float | None
    longitude: float | None
    ai_status: AIStatus
    ai_error: str | None
    attributes: list[AttributeOut]


class Page(BaseModel):
    items: list
    total: int
    page: int
    page_size: int
