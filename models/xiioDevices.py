from app.database import Column, SurrogatePK, db

class XiioDevices(SurrogatePK, db.Model):
    __tablename__ = 'xiiodevices'
    title = Column(db.String(100))
    ip = Column(db.String(100))
    token = Column(db.String(255))
    device_type = Column(db.String(255))
    device_id = Column(db.Integer)
    update_period = Column(db.Integer)
    updated = Column(db.DateTime)
