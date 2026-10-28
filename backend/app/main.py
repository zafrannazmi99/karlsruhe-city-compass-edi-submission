import asyncio
import json

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .auth import current_user
from .config import settings
from .database import Base, SavedPlace, Trip, User, engine, get_db
from .ollama import grounded_answer
from .place_categories import category_label, effective_categories
from .place_verification import use_recent_snapshot, verify_recommendations
from .routing import plan_route
from .schemas import (
    AskRequest,
    AskResponse,
    LoginRequest,
    PlaceResponse,
    RegisterRequest,
    SavedPlaceCreate,
    SavedPlaceResponse,
    TokenResponse,
    TripCreate,
    TripResponse,
    UserResponse,
)
from .security import create_access_token, hash_password, verify_password
from .vector_store import search_places


Base.metadata.create_all(bind=engine)
app = FastAPI(title="Karlsruhe City Compass", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


def trip_to_response(trip: Trip) -> TripResponse:
    return TripResponse(
        id=trip.id,
        name=trip.name,
        created_at=trip.created_at,
        places=[
            SavedPlaceResponse(
                id=place.id,
                place_id=place.place_id,
                name=place.name,
                place_type=place.place_type,
                lat=place.lat,
                lon=place.lon,
                description=place.description,
                tags=json.loads(place.tags_json or "{}"),
            )
            for place in trip.places
        ],
    )


@app.get("/health")
def health():
    return {
        "status": "ok",
        "app": "Karlsruhe City Compass",
        "vector_database": "Milvus",
        "embedding_model": settings.embedding_model,
        "generation_model": settings.ollama_model,
    }


@app.post("/auth/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    email = str(payload.email).strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    user = User(email=email, password_hash=hash_password(payload.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists.") from None
    db.refresh(user)
    return TokenResponse(access_token=create_access_token(user.id), user=UserResponse.model_validate(user))


@app.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    email = str(payload.email).strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    return TokenResponse(access_token=create_access_token(user.id), user=UserResponse.model_validate(user))


@app.get("/auth/me", response_model=UserResponse)
def me(user: User = Depends(current_user)):
    return user


@app.post("/search", response_model=list[PlaceResponse])
def search(payload: AskRequest):
    try:
        categories, _intent_source = effective_categories(payload.question, payload.category)
        candidates = search_places(
            payload.question,
            payload.limit,
            candidate_count=max(payload.limit * 8, 40),
            category=categories or None,
        )
        places, _verification = asyncio.run(
            verify_recommendations(
                candidates,
                limit=payload.limit,
                expected_categories=categories,
            )
        )
        if not places and _verification["mode"] == "osm_unavailable":
            places, _verification = use_recent_snapshot(
                candidates,
                _verification,
                limit=payload.limit,
                candidate_limit=max(payload.limit * 4, 20),
                expected_categories=categories,
            )
        places, _route = plan_route(places, payload.origin, limit=payload.limit)
        return places
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/ask", response_model=AskResponse)
def ask(payload: AskRequest):
    try:
        categories, intent_source = effective_categories(payload.question, payload.category)
        candidates = search_places(
            payload.question,
            payload.limit,
            candidate_count=max(payload.limit * 12, 60),
            category=categories or None,
        )
        # Keep Milvus relevance order for the source check. The verifier makes
        # live Overpass calls in batches and moves on when a record is missing,
        # closed, or no longer belongs to the requested category.
        verified_places, verification = asyncio.run(
            verify_recommendations(
                candidates,
                limit=payload.limit,
                expected_categories=categories,
            )
        )
        if not verified_places and verification["mode"] == "osm_unavailable":
            verified_places, verification = use_recent_snapshot(
                candidates,
                verification,
                limit=payload.limit,
                candidate_limit=max(payload.limit * 4, 20),
                expected_categories=categories,
            )
        places, route = plan_route(verified_places, payload.origin, limit=payload.limit)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if intent_source == "prompt" and payload.category and payload.category not in categories:
        requested = ", ".join(category_label(item) for item in categories)
        verification["message"] = (
            f"Your wording explicitly asks for {requested}, so it took priority over the "
            f"selected {category_label(payload.category)} focus. {verification['message']}"
        )
    answer, model_status = grounded_answer(
        payload.question,
        places,
        route,
        use_llm=verification["mode"] != "osm_snapshot",
    )
    return AskResponse(
        answer=answer,
        places=places,
        model_status=model_status,
        route=route,
        verification=verification,
    )


@app.get("/trips", response_model=list[TripResponse])
def list_trips(user: User = Depends(current_user), db: Session = Depends(get_db)):
    trips = db.scalars(
        select(Trip).where(Trip.user_id == user.id).options(selectinload(Trip.places)).order_by(Trip.id)
    ).all()
    return [trip_to_response(trip) for trip in trips]


@app.post("/trips", response_model=TripResponse, status_code=status.HTTP_201_CREATED)
def create_trip(payload: TripCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    trip = Trip(name=payload.name.strip(), user_id=user.id)
    db.add(trip)
    db.commit()
    db.refresh(trip)
    return trip_to_response(trip)


def owned_trip(trip_id: int, user: User, db: Session) -> Trip:
    trip = db.scalar(
        select(Trip)
        .where(Trip.id == trip_id, Trip.user_id == user.id)
        .options(selectinload(Trip.places))
    )
    if trip is None:
        raise HTTPException(status_code=404, detail="Trip not found.")
    return trip


@app.post("/trips/{trip_id}/places", response_model=TripResponse)
def add_place(
    trip_id: int,
    payload: SavedPlaceCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    trip = owned_trip(trip_id, user, db)
    if any(place.place_id == payload.place_id for place in trip.places):
        raise HTTPException(status_code=409, detail="This place is already saved to the trip.")
    db.add(SavedPlace(
        trip_id=trip.id,
        place_id=payload.place_id,
        name=payload.name,
        place_type=payload.place_type,
        lat=payload.lat,
        lon=payload.lon,
        description=payload.description,
        tags_json=json.dumps(payload.tags, ensure_ascii=False),
    ))
    db.commit()
    return trip_to_response(owned_trip(trip_id, user, db))


@app.delete("/trips/{trip_id}/places/{saved_place_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_place(
    trip_id: int,
    saved_place_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    trip = owned_trip(trip_id, user, db)
    place = next((item for item in trip.places if item.id == saved_place_id), None)
    if place is None:
        raise HTTPException(status_code=404, detail="Saved place not found.")
    db.delete(place)
    db.commit()


@app.delete("/trips/{trip_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_trip(trip_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    trip = owned_trip(trip_id, user, db)
    db.delete(trip)
    db.commit()
