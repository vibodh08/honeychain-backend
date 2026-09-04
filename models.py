from sqlalchemy import Column, Integer, String, Float, Date

from database import Base


class HoneyBatch(Base):
    __tablename__ = "honey_batches"

    id = Column(Integer, primary_key=True, index=True)

    batch_id = Column(String, unique=True, index=True, nullable=False)

    beekeeper_name = Column(String, nullable=False)

    location = Column(String, nullable=False)

    hive_id = Column(String, nullable=False)

    honey_type = Column(String, nullable=False)

    harvest_date = Column(Date, nullable=False)

    quantity_kg = Column(Float, nullable=False)

    status = Column(String, nullable=False)

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)