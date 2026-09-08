import json
import hashlib
import os

from datetime import date, datetime, timedelta

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

from pydantic import BaseModel

from sqlalchemy.orm import Session
from sqlalchemy import Column, Integer, String, Date, DateTime

from jose import JWTError, jwt
from passlib.context import CryptContext

from database import engine, SessionLocal, Base
from models import HoneyBatch, User
from supplychain import SupplyChainEvent

from blockchain import (
    verify_batch_on_blockchain,
    register_batch_on_blockchain,
)


# ============================================================
# DATABASE
# ============================================================

Base.metadata.create_all(bind=engine)


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="HoneyChain API",
    description="Blockchain-based honey traceability and verification system",
    version="1.0.0"
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# JWT / AUTHENTICATION
# ============================================================

SECRET_KEY = os.getenv(
    "SECRET_KEY",
    "honeychain-secret-key-change-later"
)

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60


pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/login"
)


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
# DATABASE DEPENDENCY
# ============================================================

def get_db():

    db = SessionLocal()

    try:
        yield db

    finally:
        db.close()


# ============================================================
# PASSWORD FUNCTIONS
# ============================================================

def hash_password(password: str) -> str:

    return pwd_context.hash(password)


def verify_password(
    plain_password: str,
    hashed_password: str
) -> bool:

    return pwd_context.verify(
        plain_password,
        hashed_password
    )


# ============================================================
# JWT FUNCTIONS
# ============================================================

def create_access_token(
    data: dict,
    expires_delta: timedelta | None = None
):

    to_encode = data.copy()

    if expires_delta:

        expire = (
            datetime.utcnow()
            + expires_delta
        )

    else:

        expire = (
            datetime.utcnow()
            + timedelta(
                minutes=ACCESS_TOKEN_EXPIRE_MINUTES
            )
        )

    to_encode.update({
        "exp": expire
    })

    return jwt.encode(
        to_encode,
        SECRET_KEY,
        algorithm=ALGORITHM
    )


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):

    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials"
    )

    try:

        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )

        username = payload.get("sub")

        if username is None:

            raise credentials_exception

    except JWTError:

        raise credentials_exception

    user = (
        db.query(User)
        .filter(
            User.username == username
        )
        .first()
    )

    if user is None:

        raise credentials_exception

    return user


def require_roles(*roles):

    def role_checker(
        current_user: User = Depends(
            get_current_user
        )
    ):

        if current_user.role not in roles:

            raise HTTPException(
                status_code=403,
                detail=(
                    "You do not have permission "
                    "to perform this action"
                )
            )

        return current_user

    return role_checker


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
# LAB CERTIFICATE DATABASE MODEL
# ============================================================

class LabCertificate(Base):

    __tablename__ = "lab_certificates"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    batch_id = Column(
        String,
        nullable=False,
        index=True
    )

    certificate_id = Column(
        String,
        nullable=False,
        unique=True,
        index=True
    )

    laboratory_name = Column(
        String,
        nullable=False
    )

    test_date = Column(
        Date,
        nullable=False
    )

    test_result = Column(
        String,
        nullable=False
    )

    quality_status = Column(
        String,
        nullable=False
    )

    notes = Column(
        String,
        nullable=True
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )


# Create lab_certificates table

Base.metadata.create_all(bind=engine)


class LabCertificateCreate(BaseModel):

    certificate_id: str
    laboratory_name: str
    test_date: date
    test_result: str
    quality_status: str
    notes: str | None = None


# ============================================================
# ROOT
# ============================================================

@app.get("/")
def root():

    return {

        "message":
            "HoneyChain API is running",

        "version":
            "1.0.0",

        "blockchain":
            "Sepolia Testnet"
    }


# ============================================================
# REGISTER USER
# ============================================================

@app.post("/api/register")
def register_user(
    user_data: UserRegister,
    db: Session = Depends(get_db)
):

    if user_data.role not in ALLOWED_ROLES:

        raise HTTPException(
            status_code=400,
            detail="Invalid role"
        )

    existing_user = (
        db.query(User)
        .filter(
            User.username ==
            user_data.username
        )
        .first()
    )

    if existing_user:

        raise HTTPException(
            status_code=400,
            detail="Username already exists"
        )

    new_user = User(

        username=
            user_data.username,

        password_hash=
            hash_password(
                user_data.password
            ),

        role=
            user_data.role
    )

    db.add(new_user)

    db.commit()

    db.refresh(new_user)

    return {

        "message":
            "User registered successfully",

        "username":
            new_user.username,

        "role":
            new_user.role
    }


# ============================================================
# LOGIN USER
# ============================================================
#
# IMPORTANT:
# OAuth2PasswordRequestForm is used here instead of
# UserLogin so Swagger's OAuth2 Authorize button works.
#
# Swagger sends:
#
# username=...
# password=...
#
# as form data.
#
# ============================================================

@app.post("/api/login")
def login_user(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):

    user = (
        db.query(User)
        .filter(
            User.username ==
            form_data.username
        )
        .first()
    )

    if not user:

        raise HTTPException(
            status_code=401,
            detail="Invalid username or password"
        )

    if not verify_password(
        form_data.password,
        user.password_hash
    ):

        raise HTTPException(
            status_code=401,
            detail="Invalid username or password"
        )

    access_token = create_access_token(

        data={
            "sub": user.username,
            "role": user.role
        }
    )

    return {

        "access_token":
            access_token,

        "token_type":
            "bearer",

        "username":
            user.username,

        "role":
            user.role
    }


# ============================================================
# CREATE HONEY BATCH
# ============================================================

@app.post("/api/batches")
def create_batch(

    batch_data: HoneyBatchCreate,

    db: Session = Depends(get_db),

    current_user: User = Depends(
        require_roles(
            "beekeeper",
            "admin"
        )
    )
):

    existing_batch = (
        db.query(HoneyBatch)
        .filter(
            HoneyBatch.batch_id ==
            batch_data.batch_id
        )
        .first()
    )

    if existing_batch:

        raise HTTPException(
            status_code=400,
            detail="Batch ID already exists"
        )

    new_batch = HoneyBatch(

        batch_id=
            batch_data.batch_id,

        beekeeper_name=
            batch_data.beekeeper_name,

        location=
            batch_data.location,

        hive_id=
            batch_data.hive_id,

        honey_type=
            batch_data.honey_type,

        harvest_date=
            batch_data.harvest_date,

        quantity_kg=
            batch_data.quantity_kg,

        status=
            batch_data.status
    )


    # ========================================================
    # IMMUTABLE METADATA
    # ========================================================

    metadata = {

        "batch_id":
            new_batch.batch_id,

        "beekeeper_name":
            new_batch.beekeeper_name,

        "location":
            new_batch.location,

        "hive_id":
            new_batch.hive_id,

        "honey_type":
            new_batch.honey_type,

        "harvest_date":
            new_batch.harvest_date.isoformat(),

        "quantity_kg":
            new_batch.quantity_kg
    }


    canonical_metadata = json.dumps(

        metadata,

        sort_keys=True,

        separators=(
            ",",
            ":"
        )
    )


    metadata_hash = hashlib.sha256(

        canonical_metadata.encode(
            "utf-8"
        )

    ).hexdigest()


    new_batch.metadata_hash = metadata_hash


    # Save database record

    db.add(new_batch)

    db.commit()

    db.refresh(new_batch)


    # ========================================================
    # BLOCKCHAIN REGISTRATION
    # ========================================================

    blockchain_result = None

    try:

        blockchain_result = (
            register_batch_on_blockchain(
                new_batch.batch_id,
                metadata_hash
            )
        )

    except Exception as e:

        blockchain_result = {

            "status":
                "Blockchain registration failed",

            "error":
                str(e)
        }


    return {

        "message":
            "Honey batch created successfully",

        "batch": {

            "id":
                new_batch.id,

            "batch_id":
                new_batch.batch_id,

            "beekeeper_name":
                new_batch.beekeeper_name,

            "location":
                new_batch.location,

            "hive_id":
                new_batch.hive_id,

            "honey_type":
                new_batch.honey_type,

            "harvest_date":
                new_batch.harvest_date,

            "quantity_kg":
                new_batch.quantity_kg,

            "status":
                new_batch.status,

            "metadata_hash":
                new_batch.metadata_hash
        },

        "blockchain":
            blockchain_result
    }


# ============================================================
# GET ALL BATCHES
# ============================================================

@app.get("/api/batches")
def get_batches(
    db: Session = Depends(get_db)
):

    batches = (

        db.query(HoneyBatch)

        .order_by(
            HoneyBatch.id.desc()
        )

        .all()
    )

    return batches


# ============================================================
# GET SINGLE BATCH
# ============================================================

@app.get("/api/batches/{batch_id}")
def get_batch(

    batch_id: str,

    db: Session = Depends(get_db)
):

    batch = (

        db.query(HoneyBatch)

        .filter(
            HoneyBatch.batch_id ==
            batch_id
        )

        .first()
    )

    if not batch:

        raise HTTPException(
            status_code=404,
            detail="Batch not found"
        )

    return batch


# ============================================================
# SUPPLY CHAIN PERMISSIONS
# ============================================================

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


# ============================================================
# CREATE SUPPLY CHAIN EVENT
# ============================================================

@app.post("/api/supply-chain")
def create_supply_chain_event(

    event_data: SupplyChainEventCreate,

    db: Session = Depends(get_db),

    current_user: User = Depends(
        get_current_user
    )
):

    if event_data.event_type not in event_permissions:

        raise HTTPException(

            status_code=400,

            detail=(
                "Invalid event type. "
                "Use: Harvested, Extracted, "
                "Processed, Lab Tested, "
                "Bottled, Distributed"
            )
        )


    allowed_roles = event_permissions[
        event_data.event_type
    ]


    if current_user.role not in allowed_roles:

        raise HTTPException(

            status_code=403,

            detail=(
                f"Role '{current_user.role}' "
                f"cannot create "
                f"'{event_data.event_type}' event"
            )
        )


    batch = (

        db.query(HoneyBatch)

        .filter(
            HoneyBatch.batch_id ==
            event_data.batch_id
        )

        .first()
    )


    if not batch:

        raise HTTPException(

            status_code=404,

            detail="Batch not found"
        )


    event = SupplyChainEvent(

        batch_id=
            event_data.batch_id,

        event_type=
            event_data.event_type,

        location=
            event_data.location,

        actor=
            event_data.actor,

        notes=
            event_data.notes
    )


    db.add(event)


    # Update current status

    batch.status = (
        event_data.event_type.lower()
    )


    db.commit()

    db.refresh(event)


    return {

        "message":
            "Supply chain event created successfully",

        "event": {

            "event_id":
                event.id,

            "batch_id":
                event.batch_id,

            "stage":
                event.event_type,

            "location":
                event.location,

            "actor":
                event.actor,

            "timestamp":
                event.timestamp,

            "notes":
                event.notes
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

    batch = (

        db.query(HoneyBatch)

        .filter(
            HoneyBatch.batch_id ==
            batch_id
        )

        .first()
    )


    if not batch:

        raise HTTPException(

            status_code=404,

            detail="Batch not found"
        )


    events = (

        db.query(SupplyChainEvent)

        .filter(
            SupplyChainEvent.batch_id ==
            batch_id
        )

        .order_by(
            SupplyChainEvent.timestamp.asc()
        )

        .all()
    )


    return [

        {

            "event_id":
                event.id,

            "batch_id":
                event.batch_id,

            "stage":
                event.event_type,

            "location":
                event.location,

            "actor":
                event.actor,

            "timestamp":
                event.timestamp,

            "notes":
                event.notes

        }

        for event in events
    ]


# ============================================================
# CREATE LAB CERTIFICATE
# ============================================================

@app.post("/api/batches/{batch_id}/lab-certificate")
def create_lab_certificate(

    batch_id: str,

    certificate_data: LabCertificateCreate,

    db: Session = Depends(get_db),

    current_user: User = Depends(
        require_roles(
            "lab",
            "admin"
        )
    )
):

    # --------------------------------------------------------
    # CHECK BATCH
    # --------------------------------------------------------

    batch = (

        db.query(HoneyBatch)

        .filter(
            HoneyBatch.batch_id ==
            batch_id
        )

        .first()
    )


    if not batch:

        raise HTTPException(

            status_code=404,

            detail="Batch not found"
        )


    # --------------------------------------------------------
    # CHECK DUPLICATE CERTIFICATE
    # --------------------------------------------------------

    existing_certificate = (

        db.query(LabCertificate)

        .filter(

            LabCertificate.certificate_id ==
            certificate_data.certificate_id

        )

        .first()
    )


    if existing_certificate:

        raise HTTPException(

            status_code=400,

            detail="Certificate ID already exists"
        )


    # --------------------------------------------------------
    # CREATE CERTIFICATE
    # --------------------------------------------------------

    certificate = LabCertificate(

        batch_id=
            batch_id,

        certificate_id=
            certificate_data.certificate_id,

        laboratory_name=
            certificate_data.laboratory_name,

        test_date=
            certificate_data.test_date,

        test_result=
            certificate_data.test_result,

        quality_status=
            certificate_data.quality_status,

        notes=
            certificate_data.notes
    )


    db.add(certificate)


    # --------------------------------------------------------
    # CHECK EXISTING LAB EVENT
    # --------------------------------------------------------

    existing_lab_event = (

        db.query(SupplyChainEvent)

        .filter(

            SupplyChainEvent.batch_id ==
            batch_id,

            SupplyChainEvent.event_type ==
            "Lab Tested"

        )

        .first()
    )


    # --------------------------------------------------------
    # AUTOMATIC LAB TESTED EVENT
    # --------------------------------------------------------

    if not existing_lab_event:

        lab_event = SupplyChainEvent(

            batch_id=
                batch_id,

            event_type=
                "Lab Tested",

            location=
                certificate_data.laboratory_name,

            actor=
                current_user.username,

            notes=(

                f"Certificate: "
                f"{certificate_data.certificate_id} | "

                f"Result: "
                f"{certificate_data.test_result} | "

                f"Quality: "
                f"{certificate_data.quality_status}"
            )
        )


        db.add(lab_event)


        batch.status = "lab tested"


    db.commit()

    db.refresh(certificate)


    return {

        "message":
            "Lab certificate added successfully",

        "certificate": {

            "id":
                certificate.id,

            "batch_id":
                certificate.batch_id,

            "certificate_id":
                certificate.certificate_id,

            "laboratory_name":
                certificate.laboratory_name,

            "test_date":
                certificate.test_date,

            "test_result":
                certificate.test_result,

            "quality_status":
                certificate.quality_status,

            "notes":
                certificate.notes,

            "created_at":
                certificate.created_at
        }
    }


# ============================================================
# GET LAB CERTIFICATE
# ============================================================

@app.get("/api/batches/{batch_id}/lab-certificate")
def get_lab_certificate(

    batch_id: str,

    db: Session = Depends(get_db)
):

    batch = (

        db.query(HoneyBatch)

        .filter(
            HoneyBatch.batch_id ==
            batch_id
        )

        .first()
    )


    if not batch:

        raise HTTPException(

            status_code=404,

            detail="Batch not found"
        )


    certificate = (

        db.query(LabCertificate)

        .filter(
            LabCertificate.batch_id ==
            batch_id
        )

        .order_by(
            LabCertificate.id.desc()
        )

        .first()
    )


    if not certificate:

        raise HTTPException(

            status_code=404,

            detail=(
                "No lab certificate found "
                "for this batch"
            )
        )


    return {

        "certificate": {

            "id":
                certificate.id,

            "batch_id":
                certificate.batch_id,

            "certificate_id":
                certificate.certificate_id,

            "laboratory_name":
                certificate.laboratory_name,

            "test_date":
                certificate.test_date,

            "test_result":
                certificate.test_result,

            "quality_status":
                certificate.quality_status,

            "notes":
                certificate.notes,

            "created_at":
                certificate.created_at
        }
    }


# ============================================================
# HONEY PASSPORT
# ============================================================

@app.get("/api/passport/{batch_id}")
def get_honey_passport(

    batch_id: str,

    db: Session = Depends(get_db)
):

    # --------------------------------------------------------
    # GET BATCH
    # --------------------------------------------------------

    batch = (

        db.query(HoneyBatch)

        .filter(
            HoneyBatch.batch_id ==
            batch_id
        )

        .first()
    )


    if not batch:

        raise HTTPException(

            status_code=404,

            detail="Batch not found"
        )


    # --------------------------------------------------------
    # SUPPLY CHAIN
    # --------------------------------------------------------

    events = (

        db.query(SupplyChainEvent)

        .filter(
            SupplyChainEvent.batch_id ==
            batch_id
        )

        .order_by(
            SupplyChainEvent.timestamp.asc()
        )

        .all()
    )


    supply_chain = [

        {

            "event_id":
                event.id,

            "stage":
                event.event_type,

            "location":
                event.location,

            "actor":
                event.actor,

            "timestamp":
                event.timestamp,

            "notes":
                event.notes

        }

        for event in events
    ]


    # --------------------------------------------------------
    # LAB CERTIFICATE
    # --------------------------------------------------------

    certificate = (

        db.query(LabCertificate)

        .filter(
            LabCertificate.batch_id ==
            batch_id
        )

        .order_by(
            LabCertificate.id.desc()
        )

        .first()
    )


    lab_certificate = None


    if certificate:

        lab_certificate = {

            "certificate_id":
                certificate.certificate_id,

            "laboratory_name":
                certificate.laboratory_name,

            "test_date":
                certificate.test_date,

            "test_result":
                certificate.test_result,

            "quality_status":
                certificate.quality_status,

            "notes":
                certificate.notes,

            "created_at":
                certificate.created_at
        }


    # --------------------------------------------------------
    # BLOCKCHAIN
    # --------------------------------------------------------

    blockchain_data = None


    try:

        blockchain_data = (

            verify_batch_on_blockchain(
                batch_id
            )
        )


    except Exception as e:

        blockchain_data = {

            "verified":
                False,

            "error":
                str(e)
        }


    # --------------------------------------------------------
    # FINAL PASSPORT
    # --------------------------------------------------------

    return {

        "passport": {

            "batch_id":
                batch.batch_id,

            "beekeeper_name":
                batch.beekeeper_name,

            "location":
                batch.location,

            "hive_id":
                batch.hive_id,

            "honey_type":
                batch.honey_type,

            "harvest_date":
                batch.harvest_date,

            "quantity_kg":
                batch.quantity_kg,

            "status":
                batch.status,

            "metadata_hash":
                batch.metadata_hash,

            "lab_certificate":
                lab_certificate,

            "blockchain":
                blockchain_data
        },

        "supply_chain":
            supply_chain
    }


# ============================================================
# REPAIR BLOCKCHAIN REGISTRATION
# ============================================================

@app.post("/api/batches/{batch_id}/repair-blockchain")
def repair_blockchain_registration(

    batch_id: str,

    db: Session = Depends(get_db),

    current_user: User = Depends(
        require_roles(
            "beekeeper",
            "admin"
        )
    )
):

    batch = (

        db.query(HoneyBatch)

        .filter(
            HoneyBatch.batch_id ==
            batch_id
        )

        .first()
    )


    if not batch:

        raise HTTPException(

            status_code=404,

            detail="Batch not found"
        )


    # --------------------------------------------------------
    # RECOVER METADATA HASH
    # --------------------------------------------------------

    if not batch.metadata_hash:

        metadata = {

            "batch_id":
                batch.batch_id,

            "beekeeper_name":
                batch.beekeeper_name,

            "location":
                batch.location,

            "hive_id":
                batch.hive_id,

            "honey_type":
                batch.honey_type,

            "harvest_date":
                batch.harvest_date.isoformat(),

            "quantity_kg":
                batch.quantity_kg
        }


        canonical_metadata = json.dumps(

            metadata,

            sort_keys=True,

            separators=(
                ",",
                ":"
            )
        )


        batch.metadata_hash = hashlib.sha256(

            canonical_metadata.encode(
                "utf-8"
            )

        ).hexdigest()


        db.commit()


    # --------------------------------------------------------
    # REGISTER
    # --------------------------------------------------------

    try:

        blockchain_result = (

            register_batch_on_blockchain(

                batch.batch_id,

                batch.metadata_hash
            )
        )


    except Exception as e:

        raise HTTPException(

            status_code=500,

            detail=str(e)
        )


    return {

        "message":
            "Blockchain registration submitted",

        "batch_id":
            batch.batch_id,

        "metadata_hash":
            batch.metadata_hash,

        "repaired_by":
            current_user.username,

        "blockchain":
            blockchain_result
    }


# ============================================================
# VERIFY BATCH ON BLOCKCHAIN
# ============================================================

@app.get("/api/batches/{batch_id}/blockchain")
def verify_batch_blockchain(

    batch_id: str,

    db: Session = Depends(get_db)
):

    batch = (

        db.query(HoneyBatch)

        .filter(
            HoneyBatch.batch_id ==
            batch_id
        )

        .first()
    )


    if not batch:

        raise HTTPException(

            status_code=404,

            detail="Batch not found"
        )


    try:

        blockchain_result = (

            verify_batch_on_blockchain(
                batch_id
            )
        )


    except Exception as e:

        raise HTTPException(

            status_code=500,

            detail=str(e)
        )


    return {

        "batch_id":
            batch_id,

        "database_metadata_hash":
            batch.metadata_hash,

        "blockchain":
            blockchain_result
    }


# ============================================================
# TAMPER / INTEGRITY CHECK
# ============================================================

@app.get("/api/batches/{batch_id}/integrity")
def check_batch_integrity(

    batch_id: str,

    db: Session = Depends(get_db)
):

    # --------------------------------------------------------
    # GET BATCH
    # --------------------------------------------------------

    batch = (

        db.query(HoneyBatch)

        .filter(
            HoneyBatch.batch_id ==
            batch_id
        )

        .first()
    )


    if not batch:

        raise HTTPException(

            status_code=404,

            detail="Batch not found"
        )


    # --------------------------------------------------------
    # LEGACY BATCH
    # --------------------------------------------------------

    if not batch.metadata_hash:

        return {

            "batch_id":
                batch_id,

            "integrity_verified":
                False,

            "status":
                (
                    "LEGACY BATCH - "
                    "Immutable hash not stored "
                    "in database"
                ),

            "current_database_hash":
                None,

            "stored_metadata_hash":
                None,

            "blockchain_hash":
                None,

            "database_hash_matches":
                False,

            "blockchain_hash_matches":
                False
        }


    # --------------------------------------------------------
    # RECREATE CURRENT METADATA
    # --------------------------------------------------------

    current_metadata = {

        "batch_id":
            batch.batch_id,

        "beekeeper_name":
            batch.beekeeper_name,

        "location":
            batch.location,

        "hive_id":
            batch.hive_id,

        "honey_type":
            batch.honey_type,

        "harvest_date":
            batch.harvest_date.isoformat(),

        "quantity_kg":
            batch.quantity_kg
    }


    canonical_metadata = json.dumps(

        current_metadata,

        sort_keys=True,

        separators=(
            ",",
            ":"
        )
    )


    current_hash = hashlib.sha256(

        canonical_metadata.encode(
            "utf-8"
        )

    ).hexdigest()


    # --------------------------------------------------------
    # DATABASE HASH
    # --------------------------------------------------------

    database_hash_matches = (

        current_hash ==
        batch.metadata_hash
    )


    # --------------------------------------------------------
    # BLOCKCHAIN HASH
    # --------------------------------------------------------

    blockchain_hash = None

    blockchain_hash_matches = False


    try:

        blockchain_result = (

            verify_batch_on_blockchain(
                batch_id
            )
        )


        if isinstance(
            blockchain_result,
            dict
        ):

            blockchain_hash = (
                blockchain_result.get(
                    "metadata_hash"
                )
            )


        elif isinstance(
            blockchain_result,
            (list, tuple)
        ):

            if len(blockchain_result) >= 2:

                blockchain_hash = (
                    blockchain_result[1]
                )


        if blockchain_hash:

            blockchain_hash_matches = (

                blockchain_hash ==
                batch.metadata_hash
            )


    except Exception:

        blockchain_hash = None


    # --------------------------------------------------------
    # FINAL DECISION
    # --------------------------------------------------------

    integrity_verified = (

        database_hash_matches
        and blockchain_hash_matches
    )


    if integrity_verified:

        status = (
            "VERIFIED - "
            "Database and blockchain data match"
        )

    else:

        status = (
            "TAMPER DETECTED - "
            "Data does not match blockchain"
        )


    return {

        "batch_id":
            batch_id,

        "integrity_verified":
            integrity_verified,

        "status":
            status,

        "current_database_hash":
            current_hash,

        "stored_metadata_hash":
            batch.metadata_hash,

        "blockchain_hash":
            blockchain_hash,

        "database_hash_matches":
            database_hash_matches,

        "blockchain_hash_matches":
            blockchain_hash_matches,

        "network":
            "Sepolia Testnet",

        "contract_address":
            (
                "0x8B12321F29947DE607e16218D8A582756E77E61C"
            )
    }


# ============================================================
# QR CODE ENDPOINT
# ============================================================

@app.get("/api/batches/{batch_id}/qr")
def get_qr_data(

    batch_id: str,

    db: Session = Depends(get_db)
):

    batch = (

        db.query(HoneyBatch)

        .filter(
            HoneyBatch.batch_id ==
            batch_id
        )

        .first()
    )


    if not batch:

        raise HTTPException(

            status_code=404,

            detail="Batch not found"
        )


    return {

        "batch_id":
            batch.batch_id,

        "passport_url":
            f"/api/passport/{batch.batch_id}",

        "verification_url":
            f"/api/batches/"
            f"{batch.batch_id}/integrity",

        "message":
            (
                "Scan this QR code to view "
                "the Honey Passport"
            )
    }


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
def health_check():

    return {

        "status":
            "healthy",

        "service":
            "HoneyChain API",

        "blockchain":
            "Sepolia Testnet",

        "contract":
            (
                "0x8B12321F29947DE607e16218D8A582756E77E61C"
            )
    }