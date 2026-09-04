from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime

from database import Base


class SupplyChainEvent(Base):
    __tablename__ = "supply_chain_events"

    id = Column(Integer, primary_key=True, index=True)

    batch_id = Column(String, nullable=False, index=True)

    event_type = Column(String, nullable=False)

    location = Column(String, nullable=False)

    actor = Column(String, nullable=False)

    timestamp = Column(DateTime, default=datetime.utcnow)

    notes = Column(String, nullable=True)