from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    limit: int = Field(default=5, ge=1, le=10)
    origin: str | None = Field(default=None, max_length=255)
    category: Literal[
        "cafe", "restaurant", "playground", "school", "library", "healthcare",
        "transport", "sports", "services", "stay", "fishing", "museum",
        "attraction", "park", "water", "shopping",
    ] | None = None


class PlaceResponse(BaseModel):
    id: str
    name: str
    place_type: str
    lat: float
    lon: float
    description: str
    tags: dict[str, Any] = Field(default_factory=dict)
    score: float | None = None
    source_url: str = ""
    distance_km: float | None = None
    leg_distance_km: float | None = None
    leg_duration_minutes: float | None = None
    route_order: int | None = None
    verification_status: str = "unverified"
    verification_source: str = "OpenStreetMap"
    snapshot_updated_at: str | None = None


class VerificationSummary(BaseModel):
    mode: Literal["osm_live", "osm_partial", "osm_unavailable", "osm_snapshot"]
    checked_count: int = 0
    attempted_count: int = 0
    verified_count: int = 0
    excluded_closed_count: int = 0
    excluded_missing_count: int = 0
    excluded_mismatch_count: int = 0
    failure_reason: str = ""
    snapshot_candidate_count: int = 0
    snapshot_updated_at: str | None = None
    snapshot_age_days: int | None = None
    message: str


class RouteOrigin(BaseModel):
    label: str
    lat: float
    lon: float
    source: str


class RouteResponse(BaseModel):
    origin: RouteOrigin
    distance_km: float
    duration_minutes: float | None = None
    geometry: list[list[float]]
    mode: str
    disclaimer: str


class AskResponse(BaseModel):
    answer: str
    places: list[PlaceResponse]
    model_status: str
    route: RouteResponse
    verification: VerificationSummary


class TripCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class SavedPlaceCreate(BaseModel):
    place_id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=255)
    place_type: str = Field(min_length=1, max_length=80)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    description: str = Field(min_length=1, max_length=3000)
    tags: dict[str, Any] = Field(default_factory=dict)


class SavedPlaceResponse(BaseModel):
    id: int
    place_id: str
    name: str
    place_type: str
    lat: float
    lon: float
    description: str
    tags: dict[str, Any]


class TripResponse(BaseModel):
    id: int
    name: str
    created_at: datetime
    places: list[SavedPlaceResponse]
