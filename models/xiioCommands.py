from app.database import Column, SurrogatePK, db

class XiioCommands(SurrogatePK, db.Model):
    __tablename__ = 'xiiocommands'
    device_id = Column(db.Integer)
    name = Column(db.String(50), nullable=False)
    description = Column(db.String(255))
