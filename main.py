from datetime import date, datetime, timedelta
import qrcode
from fastapi.responses import StreamingResponse
from io import BytesIO

from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from jose import jwt

from database import engine, SessionLocal, Base
from models import HoneyBatch, User
from supplychain import SupplyChainEvent


# Create database tables
Base.metadata.create_all(bind=engine)


# Create FastAPI application
app = FastAPI(title="HoneyChain API")


# Password hashing
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)


# JWT settings
SECRET_KEY = "honeychain-secret-key-change-later"
ALGORITHM = "HS256"
security = HTTPBearer()


# Database connection
def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()

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


# =========================================================
# USER / AUTHENTICATION MODELS
# =========================================================

class UserRegister(BaseModel):
    username: str
    password: str
    role: str


class UserLogin(BaseModel):
    username: str
    password: str


# =========================================================
# HONEY BATCH MODEL
# =========================================================

class HoneyBatchCreate(BaseModel):
    batch_id: str
    beekeeper_name: str
    location: str
    hive_id: str
    honey_type: str
    harvest_date: date
    quantity_kg: float
    status: str


# =========================================================
# SUPPLY CHAIN EVENT MODEL
# =========================================================

class SupplyChainEventCreate(BaseModel):
    batch_id: str
    event_type: str
    location: str
    actor: str
    notes: str | None = None


# =========================================================
# BASIC TEST APIs
# =========================================================

@app.get("/")
def home():
    return {
        "message": "HoneyChain API is running 🐝"
    }


@app.get("/api/test")
def test_api():
    return {
        "project": "HoneyChain",
        "status": "working"
    }


@app.get("/api/database-test")
def database_test():
    with engine.connect() as connection:
        return {
            "database": "connected"
        }


# =========================================================
# USER REGISTRATION
# =========================================================

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
        "customer"
    ]

    if user.role not in allowed_roles:
        raise HTTPException(
            status_code=400,
            detail="Invalid role"
        )

    # Check if username already exists
    existing_user = db.query(User).filter(
        User.username == user.username
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="Username already exists"
        )

    # Hash password
    hashed_password = pwd_context.hash(user.password)

    # Create new user
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


# =========================================================
# USER LOGIN
# =========================================================

@app.post("/api/login")
def login_user(
    user: UserLogin,
    db: Session = Depends(get_db)
):

    # Find user
    existing_user = db.query(User).filter(
        User.username == user.username
    ).first()

    # User doesn't exist
    if not existing_user:
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password"
        )

    # Check password
    if not pwd_context.verify(
        user.password,
        existing_user.password_hash
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password"
        )

    # Create JWT token
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
        "role": existing_user.role
    }


# =========================================================
# CREATE HONEY BATCH
# =========================================================

@app.post("/api/batches")
def create_batch(
    batch: HoneyBatchCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role(["beekeeper", "admin"])
    )
):

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
        "message": "Honey batch created successfully 🐝",
        "batch_id": new_batch.batch_id
    }


# =========================================================
# GET HONEY BATCH
# =========================================================

@app.get("/api/batches/{batch_id}")
def get_batch(
    batch_id: str,
    db: Session = Depends(get_db)
):

    batch = db.query(HoneyBatch).filter(
        HoneyBatch.batch_id == batch_id
    ).first()

    if not batch:
        return {
            "message": "Honey batch not found"
        }

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


# =========================================================
# ADD SUPPLY CHAIN EVENT
# =========================================================

@app.post("/api/batches/{batch_id}/events")
def add_supply_chain_event(
    batch_id: str,
    event: SupplyChainEventCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):

    # Check whether batch exists
    batch = db.query(HoneyBatch).filter(
        HoneyBatch.batch_id == batch_id
    ).first()

    if not batch:
        raise HTTPException(
            status_code=404,
            detail="Honey batch not found"
        )

    # Define which role can perform each event
    event_permissions = {
        "Harvested": ["beekeeper", "admin"],
        "Extracted": ["processor", "admin"],
        "Processed": ["processor", "admin"],
        "Lab Tested": ["lab", "admin"],
        "Bottled": ["processor", "admin"],
        "Distributed": ["distributor", "admin"]
    }

    # Check whether event type is valid
    if event.event_type not in event_permissions:
        raise HTTPException(
            status_code=400,
            detail="Invalid supply chain event type"
        )

    # Check user's role
    allowed_roles = event_permissions[event.event_type]

    if current_user.role not in allowed_roles:
        raise HTTPException(
            status_code=403,
            detail=f"Role '{current_user.role}' cannot perform '{event.event_type}'"
        )

    # Create event
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
        "message": "Supply chain event added successfully 🐝",
        "event_id": new_event.id,
        "batch_id": batch_id,
        "event_type": event.event_type,
        "performed_by": current_user.username,
        "role": current_user.role
    }

    # Check whether batch exists
    batch = db.query(HoneyBatch).filter(
        HoneyBatch.batch_id == batch_id
    ).first()

    if not batch:
        return {
            "message": "Honey batch not found"
        }

    # Create event
    new_event = SupplyChainEvent(
        batch_id=batch_id,
        event_type=event.event_type,
        location=event.location,
        actor=event.actor,
        notes=event.notes
    )

    db.add(new_event)
    db.commit()
    db.refresh(new_event)

    return {
        "message": "Supply chain event added successfully 🐝",
        "event_id": new_event.id,
        "batch_id": batch_id
    }


# =========================================================
# GET SUPPLY CHAIN HISTORY
# =========================================================

@app.get("/api/batches/{batch_id}/events")
def get_supply_chain_events(
    batch_id: str,
    db: Session = Depends(get_db)
):

    events = db.query(SupplyChainEvent).filter(
        SupplyChainEvent.batch_id == batch_id
    ).order_by(
        SupplyChainEvent.timestamp
    ).all()

    if not events:
        return {
            "message": "No supply chain events found"
        }

    return {
        "batch_id": batch_id,
        "total_events": len(events),
        "events": [
            {
                "event_id": event.id,
                "event_type": event.event_type,
                "location": event.location,
                "actor": event.actor,
                "timestamp": event.timestamp,
                "notes": event.notes
            }
            for event in events
        ]
    }


# =========================================================
# HONEY PASSPORT
# =========================================================

@app.get("/api/passport/{batch_id}")
def get_honey_passport(
    batch_id: str,
    db: Session = Depends(get_db)
):

    # Find honey batch
    batch = db.query(HoneyBatch).filter(
        HoneyBatch.batch_id == batch_id
    ).first()

    if not batch:
        return {
            "message": "Honey batch not found"
        }

    # Find supply chain events
    events = db.query(SupplyChainEvent).filter(
        SupplyChainEvent.batch_id == batch_id
    ).order_by(
        SupplyChainEvent.timestamp
    ).all()

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

        "supply_chain": [
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
    }

# =========================================================
# HONEY PASSPORT QR CODE
# =========================================================

@app.get("/api/qr/{batch_id}")
def generate_qr(batch_id: str):

    passport_url = (
        f"http://127.0.0.1:8000/api/passport/{batch_id}"
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
    qr_image.save(image_bytes, format="PNG")
    image_bytes.seek(0)

    return StreamingResponse(
        image_bytes,
        media_type="image/png"
    )