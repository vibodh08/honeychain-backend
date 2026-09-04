from datetime import date, datetime, timedelta
import os
from io import BytesIO

import qrcode
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from jose import jwt

from database import engine, SessionLocal, Base
from models import HoneyBatch, User
from supplychain import SupplyChainEvent


# ============================================================
# DATABASE
# ============================================================

Base.metadata.create_all(bind=engine)


# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI(
    title="HoneyChain API",
    description="Blockchain-based honey traceability and smart beekeeping management system",
    version="1.0.0"
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "https://honey-passport-trace-r51y.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# AUTHENTICATION CONFIGURATION
# ============================================================

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)

SECRET_KEY = "honeychain-secret-key-change-later"
ALGORITHM = "HS256"

security = HTTPBearer()


# ============================================================
# DATABASE DEPENDENCY
# ============================================================

def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


# ============================================================
# PYDANTIC MODELS
# ============================================================

class UserRegister(BaseModel):
    username: str
    password: str
    role: str


class UserLogin(BaseModel):
    username: str
    password: str


class HoneyBatchCreate(BaseModel):
    batch_id: str
    beekeeper_name: str
    location: str
    hive_id: str
    honey_type: str
    harvest_date: date
    quantity_kg: float
    status: str


class SupplyChainEventCreate(BaseModel):
    batch_id: str
    event_type: str
    location: str
    actor: str
    notes: str | None = None


# ============================================================
# PASSWORD FUNCTIONS
# ============================================================

def hash_password(password: str):
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str):
    return pwd_context.verify(password, password_hash)


# ============================================================
# BASIC ROUTES
# ============================================================

@app.get("/")
def root():
    return {
        "message": "HoneyChain API is running 🐝🍯"
    }


@app.get("/api/test")
def test_api():
    return {
        "message": "HoneyChain API working successfully"
    }


# ============================================================
# DATABASE TEST
# ============================================================

@app.get("/api/database-test")
def database_test(db: Session = Depends(get_db)):

    try:
        db.execute("SELECT 1")

        return {
            "message": "Database connected successfully 🐝"
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Database connection failed: {str(e)}"
        )


# ============================================================
# USER REGISTRATION
# ============================================================

@app.post("/api/register")
def register_user(
    user: UserRegister,
    db: Session = Depends(get_db)
):

    allowed_roles = [
        "beekeeper",
        "processor",
        "lab",
        "distributor",
        "customer",
        "admin"
    ]

    if user.role not in allowed_roles:
        raise HTTPException(
            status_code=400,
            detail="Invalid role"
        )

    existing_user = db.query(User).filter(
        User.username == user.username
    ).first()

    if existing_user:

        raise HTTPException(
            status_code=400,
            detail="Username already exists"
        )

    hashed_password = hash_password(user.password)

    new_user = User(
        username=user.username,
        password_hash=hashed_password,
        role=user.role
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "message": "User registered successfully",
        "username": new_user.username,
        "role": new_user.role
    }


# ============================================================
# LOGIN
# ============================================================

@app.post("/api/login")
def login_user(
    user: UserLogin,
    db: Session = Depends(get_db)
):

    existing_user = db.query(User).filter(
        User.username == user.username
    ).first()

    if not existing_user:

        raise HTTPException(
            status_code=401,
            detail="Invalid username or password"
        )

    if not verify_password(
        user.password,
        existing_user.password_hash
    ):

        raise HTTPException(
            status_code=401,
            detail="Invalid username or password"
        )

    token_data = {
        "sub": existing_user.username,
        "role": existing_user.role,
        "exp": datetime.utcnow() + timedelta(hours=2)
    }

    token = jwt.encode(
        token_data,
        SECRET_KEY,
        algorithm=ALGORITHM
    )

    return {
        "message": "Login successful",
        "access_token": token,
        "token_type": "bearer",
        "username": existing_user.username,
        "role": existing_user.role
    }


# ============================================================
# GET CURRENT USER
# ============================================================

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):

    token = credentials.credentials

    try:

        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )

        username = payload.get("sub")
        role = payload.get("role")

        if not username or not role:

            raise HTTPException(
                status_code=401,
                detail="Invalid token"
            )

        user = db.query(User).filter(
            User.username == username
        ).first()

        if not user:

            raise HTTPException(
                status_code=401,
                detail="User not found"
            )

        return user

    except Exception:

        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token"
        )


# ============================================================
# ROLE CHECKER
# ============================================================

def require_role(allowed_roles: list[str]):

    def role_checker(
        current_user: User = Depends(get_current_user)
    ):

        if current_user.role not in allowed_roles:

            raise HTTPException(
                status_code=403,
                detail="You do not have permission for this action"
            )

        return current_user

    return role_checker


# ============================================================
# CREATE HONEY BATCH
# ============================================================

@app.post("/api/batches")
def create_batch(
    batch: HoneyBatchCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role(["beekeeper", "admin"])
    )
):

    existing_batch = db.query(HoneyBatch).filter(
        HoneyBatch.batch_id == batch.batch_id
    ).first()

    if existing_batch:

        raise HTTPException(
            status_code=400,
            detail="Batch ID already exists"
        )

    new_batch = HoneyBatch(
        batch_id=batch.batch_id,
        beekeeper_name=batch.beekeeper_name,
        location=batch.location,
        hive_id=batch.hive_id,
        honey_type=batch.honey_type,
        harvest_date=batch.harvest_date,
        quantity_kg=batch.quantity_kg,
        status=batch.status
    )

    db.add(new_batch)
    db.commit()
    db.refresh(new_batch)

    return {
        "message": "Honey batch created successfully 🐝🍯",
        "batch_id": new_batch.batch_id,
        "created_by": current_user.username,
        "role": current_user.role
    }


# ============================================================
# GET ALL HONEY BATCHES
# ============================================================

@app.get("/api/batches")
def get_batches(
    db: Session = Depends(get_db)
):

    batches = db.query(HoneyBatch).all()

    return batches


# ============================================================
# GET SINGLE HONEY BATCH
# ============================================================

@app.get("/api/batches/{batch_id}")
def get_batch(
    batch_id: str,
    db: Session = Depends(get_db)
):

    batch = db.query(HoneyBatch).filter(
        HoneyBatch.batch_id == batch_id
    ).first()

    if not batch:

        raise HTTPException(
            status_code=404,
            detail="Honey batch not found"
        )

    return batch


# ============================================================
# ADD SUPPLY CHAIN EVENT
# ============================================================

@app.post("/api/batches/{batch_id}/events")
def add_supply_chain_event(
    batch_id: str,
    event: SupplyChainEventCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):

    batch = db.query(HoneyBatch).filter(
        HoneyBatch.batch_id == batch_id
    ).first()

    if not batch:

        raise HTTPException(
            status_code=404,
            detail="Honey batch not found"
        )

    event_permissions = {

        "Harvested": [
            "beekeeper",
            "admin"
        ],

        "Extracted": [
            "processor",
            "admin"
        ],

        "Processed": [
            "processor",
            "admin"
        ],

        "Lab Tested": [
            "lab",
            "admin"
        ],

        "Bottled": [
            "processor",
            "admin"
        ],

        "Distributed": [
            "distributor",
            "admin"
        ]
    }

    if event.event_type not in event_permissions:

        raise HTTPException(
            status_code=400,
            detail="Invalid supply chain event type"
        )

    allowed_roles = event_permissions[
        event.event_type
    ]

    if current_user.role not in allowed_roles:

        raise HTTPException(
            status_code=403,
            detail=(
                f"Role '{current_user.role}' cannot "
                f"perform '{event.event_type}'"
            )
        )

    new_event = SupplyChainEvent(

        batch_id=batch_id,

        event_type=event.event_type,

        location=event.location,

        actor=current_user.username,

        notes=event.notes
    )

    db.add(new_event)

    db.commit()

    db.refresh(new_event)

    return {

        "message": (
            "Supply chain event added successfully 🐝"
        ),

        "event_id": new_event.id,

        "batch_id": batch_id,

        "event_type": event.event_type,

        "performed_by": current_user.username,

        "role": current_user.role
    }


# ============================================================
# HONEY PASSPORT
# ============================================================

@app.get("/api/passport/{batch_id}")
def get_honey_passport(
    batch_id: str,
    db: Session = Depends(get_db)
):

    batch = db.query(HoneyBatch).filter(
        HoneyBatch.batch_id == batch_id
    ).first()

    if not batch:

        raise HTTPException(
            status_code=404,
            detail="Honey batch not found"
        )

    events = db.query(SupplyChainEvent).filter(
        SupplyChainEvent.batch_id == batch_id
    ).order_by(
        SupplyChainEvent.timestamp.asc()
    ).all()

    supply_chain = []

    for event in events:

        supply_chain.append({

            "event_id": event.id,

            "stage": event.event_type,

            "location": event.location,

            "actor": event.actor,

            "timestamp": event.timestamp,

            "notes": event.notes
        })

    return {

        "passport": {

            "batch_id": batch.batch_id,

            "beekeeper": batch.beekeeper_name,

            "origin": batch.location,

            "hive_id": batch.hive_id,

            "honey_type": batch.honey_type,

            "harvest_date": batch.harvest_date,

            "quantity_kg": batch.quantity_kg,

            "status": batch.status
        },

        "supply_chain": supply_chain
    }


# ============================================================
# QR CODE
# ============================================================

@app.get("/api/qr/{batch_id}")
def generate_qr(
    batch_id: str,
    db: Session = Depends(get_db)
):

    batch = db.query(HoneyBatch).filter(
        HoneyBatch.batch_id == batch_id
    ).first()

    if not batch:

        raise HTTPException(
            status_code=404,
            detail="Honey batch not found"
        )

    frontend_url = os.getenv(
        "FRONTEND_URL",
        "http://localhost:8080"
    )

    passport_url = (
        f"{frontend_url}/passport/{batch_id}"
    )

    qr = qrcode.QRCode(

        version=1,

        box_size=10,

        border=4
    )

    qr.add_data(passport_url)

    qr.make(fit=True)

    qr_image = qr.make_image()

    image_bytes = BytesIO()

    qr_image.save(
        image_bytes,
        format="PNG"
    )

    image_bytes.seek(0)

    return StreamingResponse(
        image_bytes,
        media_type="image/png"
    )