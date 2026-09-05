from datetime import date, datetime, timedelta
import os
from io import BytesIO

import qrcode
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

# Blockchain
from blockchain import verify_batch_on_blockchain


# ============================================================
# DATABASE
# ============================================================

Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


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
# AUTHENTICATION / JWT
# ============================================================

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)

SECRET_KEY = "honeychain-secret-key-change-later"
ALGORITHM = "HS256"

security = HTTPBearer()


# ============================================================
# ALLOWED ROLES
# ============================================================

ALLOWED_ROLES = {
    "beekeeper",
    "processor",
    "lab",
    "distributor",
    "customer",
    "admin"
}


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
# JWT FUNCTIONS
# ============================================================

def create_access_token(username: str, role: str):
    expire = datetime.utcnow() + timedelta(hours=24)

    payload = {
        "sub": username,
        "role": role,
        "exp": expire
    }

    return jwt.encode(
        payload,
        SECRET_KEY,
        algorithm=ALGORITHM
    )


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

        if not username:
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication token"
            )

    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token"
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


def require_role(*allowed_roles):

    def role_checker(
        current_user: User = Depends(get_current_user)
    ):
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to perform this action"
            )

        return current_user

    return role_checker


# ============================================================
# BASIC ROUTES
# ============================================================

@app.get("/")
def root():
    return {
        "message": "HoneyChain API is running",
        "version": "1.0.0",
        "status": "online"
    }


@app.get("/api/test")
def test_api():
    return {
        "message": "HoneyChain backend is working"
    }


@app.get("/api/database-test")
def database_test(db: Session = Depends(get_db)):

    try:
        count = db.query(HoneyBatch).count()

        return {
            "database": "connected",
            "honey_batches": count
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Database error: {str(e)}"
        )


# ============================================================
# USER REGISTRATION
# ============================================================

@app.post("/api/auth/register")
def register_user(
    user_data: UserRegister,
    db: Session = Depends(get_db)
):

    # Validate role
    if user_data.role not in ALLOWED_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role. Allowed roles: {', '.join(ALLOWED_ROLES)}"
        )

    # Check existing username
    existing_user = db.query(User).filter(
        User.username == user_data.username
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="Username already exists"
        )

    # Hash password
    password_hash = pwd_context.hash(
        user_data.password
    )

    new_user = User(
        username=user_data.username,
        password_hash=password_hash,
        role=user_data.role
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
# USER LOGIN
# ============================================================

@app.post("/api/auth/login")
def login_user(
    user_data: UserLogin,
    db: Session = Depends(get_db)
):

    user = db.query(User).filter(
        User.username == user_data.username
    ).first()

    if not user:

        raise HTTPException(
            status_code=401,
            detail="Invalid username or password"
        )

    if not pwd_context.verify(
        user_data.password,
        user.password_hash
    ):

        raise HTTPException(
            status_code=401,
            detail="Invalid username or password"
        )

    token = create_access_token(
        user.username,
        user.role
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "username": user.username,
        "role": user.role
    }


# ============================================================
# CREATE HONEY BATCH
# Only beekeeper/admin
# ============================================================

@app.post("/api/batches")
def create_batch(
    batch_data: HoneyBatchCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role("beekeeper", "admin")
    )
):

    # Check duplicate batch ID
    existing_batch = db.query(HoneyBatch).filter(
        HoneyBatch.batch_id == batch_data.batch_id
    ).first()

    if existing_batch:

        raise HTTPException(
            status_code=400,
            detail="Batch ID already exists"
        )

    new_batch = HoneyBatch(
        batch_id=batch_data.batch_id,
        beekeeper_name=batch_data.beekeeper_name,
        location=batch_data.location,
        hive_id=batch_data.hive_id,
        honey_type=batch_data.honey_type,
        harvest_date=batch_data.harvest_date,
        quantity_kg=batch_data.quantity_kg,
        status=batch_data.status
    )

    db.add(new_batch)
    db.commit()
    db.refresh(new_batch)

    return {
        "message": "Honey batch created successfully",
        "batch": {
            "batch_id": new_batch.batch_id,
            "beekeeper_name": new_batch.beekeeper_name,
            "location": new_batch.location,
            "hive_id": new_batch.hive_id,
            "honey_type": new_batch.honey_type,
            "harvest_date": new_batch.harvest_date,
            "quantity_kg": new_batch.quantity_kg,
            "status": new_batch.status
        },
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

    return [
        {
            "id": batch.id,
            "batch_id": batch.batch_id,
            "beekeeper_name": batch.beekeeper_name,
            "location": batch.location,
            "hive_id": batch.hive_id,
            "honey_type": batch.honey_type,
            "harvest_date": batch.harvest_date,
            "quantity_kg": batch.quantity_kg,
            "status": batch.status
        }
        for batch in batches
    ]


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

    return {
        "batch_id": batch.batch_id,
        "beekeeper_name": batch.beekeeper_name,
        "location": batch.location,
        "hive_id": batch.hive_id,
        "honey_type": batch.honey_type,
        "harvest_date": batch.harvest_date,
        "quantity_kg": batch.quantity_kg,
        "status": batch.status
    }


# ============================================================
# ADD SUPPLY CHAIN EVENT
# ============================================================

@app.post("/api/supply-chain")
def add_supply_chain_event(
    event_data: SupplyChainEventCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):

    # Find batch
    batch = db.query(HoneyBatch).filter(
        HoneyBatch.batch_id == event_data.batch_id
    ).first()

    if not batch:

        raise HTTPException(
            status_code=404,
            detail="Honey batch not found"
        )

    # Permission map
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

    # Check whether event type is valid
    if event_data.event_type not in event_permissions:

        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid event type. Allowed: "
                + ", ".join(event_permissions.keys())
            )
        )

    # Check role
    if current_user.role not in event_permissions[
        event_data.event_type
    ]:

        raise HTTPException(
            status_code=403,
            detail=(
                f"Role '{current_user.role}' "
                f"cannot create '{event_data.event_type}' events"
            )
        )

    # Create event
    new_event = SupplyChainEvent(
        batch_id=event_data.batch_id,
        event_type=event_data.event_type,
        location=event_data.location,
        actor=event_data.actor,
        notes=event_data.notes
    )

    db.add(new_event)

    # Update batch status
    batch.status = event_data.event_type.lower()

    db.commit()
    db.refresh(new_event)

    return {
        "message": "Supply chain event added successfully",
        "event": {
            "event_id": new_event.id,
            "batch_id": new_event.batch_id,
            "stage": new_event.event_type,
            "location": new_event.location,
            "actor": new_event.actor,
            "timestamp": new_event.timestamp,
            "notes": new_event.notes
        }
    }


# ============================================================
# GET SUPPLY CHAIN EVENTS
# ============================================================

@app.get("/api/batches/{batch_id}/events")
def get_supply_chain_events(
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
        SupplyChainEvent.timestamp
    ).all()

    return [
        {
            "event_id": event.id,
            "stage": event.event_type,
            "location": event.location,
            "actor": event.actor,
            "timestamp": event.timestamp,
            "notes": event.notes
        }
        for event in events
    ]


# ============================================================
# HONEY PASSPORT
# ============================================================

@app.get("/api/passport/{batch_id}")
def get_honey_passport(
    batch_id: str,
    db: Session = Depends(get_db)
):

    # Find batch
    batch = db.query(HoneyBatch).filter(
        HoneyBatch.batch_id == batch_id
    ).first()

    if not batch:

        raise HTTPException(
            status_code=404,
            detail="Honey batch not found"
        )

    # Get supply chain
    events = db.query(SupplyChainEvent).filter(
        SupplyChainEvent.batch_id == batch_id
    ).order_by(
        SupplyChainEvent.timestamp
    ).all()

    passport = {
        "batch_id": batch.batch_id,
        "beekeeper": batch.beekeeper_name,
        "origin": batch.location,
        "hive_id": batch.hive_id,
        "honey_type": batch.honey_type,
        "harvest_date": batch.harvest_date,
        "quantity_kg": batch.quantity_kg,
        "status": batch.status
    }

    supply_chain = [
        {
            "event_id": event.id,
            "stage": event.event_type,
            "location": event.location,
            "actor": event.actor,
            "timestamp": event.timestamp,
            "notes": event.notes
        }
        for event in events
    ]

    return {
        "passport": passport,
        "supply_chain": supply_chain
    }


# ============================================================
# GENERATE QR CODE
# ============================================================

@app.get("/api/qr/{batch_id}")
def generate_qr(
    batch_id: str,
    db: Session = Depends(get_db)
):

    # Check batch exists
    batch = db.query(HoneyBatch).filter(
        HoneyBatch.batch_id == batch_id
    ).first()

    if not batch:

        raise HTTPException(
            status_code=404,
            detail="Honey batch not found"
        )

    # Frontend URL
    frontend_url = os.getenv(
        "FRONTEND_URL",
        "http://localhost:8080"
    )

    # Passport URL
    passport_url = (
        f"{frontend_url}/passport/{batch_id}"
    )

    # Generate QR
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


# ============================================================
# BLOCKCHAIN VERIFICATION
# ============================================================

@app.get("/api/blockchain/verify/{batch_id}")
def verify_blockchain(
    batch_id: str
):

    try:

        result = verify_batch_on_blockchain(
            batch_id
        )

        return {
            "verified": True,
            "batch_id": result[0],
            "metadata_hash": result[1],
            "registered_by": result[2],
            "blockchain_timestamp": result[3],
            "network": "Sepolia Testnet",
            "contract_address": (
                "0x8B12321F29947DE607e16218D8A582756E77E61C"
            )
        }

    except Exception as e:

        raise HTTPException(
            status_code=404,
            detail=(
                f"Batch not found on blockchain: {str(e)}"
            )
        )


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/api/health")
def health_check():

    return {
        "status": "healthy",
        "service": "HoneyChain Backend",
        "blockchain": "Sepolia Testnet"
    }