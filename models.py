from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# Junction table for many-to-many relationship
reading_material_tags = db.Table(
    'reading_material_tags',
    db.Column('reading_material_id', db.Integer, db.ForeignKey('reading_material.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id'), primary_key=True)
)


class Status(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    display_name = db.Column(db.String(50), nullable=False)
    color = db.Column(db.String(20), default='gray')  # CSS color class
    position = db.Column(db.Integer, default=0)  # For ordering

    reading_materials = db.relationship('ReadingMaterial', backref='status_obj', lazy='dynamic')

    def __repr__(self):
        return self.display_name


class ReadingMaterial(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    link = db.Column(db.String(500), nullable=True)
    status_id = db.Column(db.Integer, db.ForeignKey('status.id'), nullable=True)
    chapter_current = db.Column(db.Integer, default=0)
    chapter_total = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tags = db.relationship('Tag', secondary=reading_material_tags, backref=db.backref('reading_materials', lazy='dynamic'))

    @property
    def status_display(self):
        return self.status_obj.display_name if self.status_obj else 'No Status'

    @property
    def status_color(self):
        return self.status_obj.color if self.status_obj else 'gray'

    @property
    def progress_percent(self):
        if self.chapter_total and self.chapter_total > 0:
            return int((self.chapter_current / self.chapter_total) * 100)
        return None


class Tag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)

    def __repr__(self):
        return self.name
