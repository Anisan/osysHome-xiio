from app.database import Column, SurrogatePK, db

class XiioProperties(SurrogatePK, db.Model):
    __tablename__ = 'xiioproperties'
    device_id = Column(db.Integer)
    property_name = Column(db.String(50), nullable=False)
    title = Column(db.String(100))
    value = Column(db.String(255))
    linked_object = Column(db.String(255))
    linked_property = Column(db.String(255))
    linked_method = Column(db.String(255))
    command = Column(db.String(50))
    updated = Column(db.DateTime)
