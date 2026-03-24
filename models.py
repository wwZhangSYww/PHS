from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

user_admin_m2m = db.Table('user_admin_m2m',
                          db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
                          db.Column('admin_id', db.Integer, db.ForeignKey('admin.id'), primary_key=True)
                          )


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(20), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    name = db.Column(db.String(50), nullable=True)
    gender = db.Column(db.String(10), nullable=True)
    province = db.Column(db.String(50), nullable=True)
    city = db.Column(db.String(50), nullable=True)
    community = db.Column(db.String(100), nullable=True)
    address = db.Column(db.String(200), nullable=True)
    height = db.Column(db.Float, nullable=True)
    weight = db.Column(db.Float, nullable=True)
    blood_type = db.Column(db.String(10), nullable=True)
    is_info_complete = db.Column(db.Boolean, default=False)

    is_frozen = db.Column(db.Boolean, default=False)
    frozen_by_name = db.Column(db.String(50), nullable=True)
    frozen_by_role = db.Column(db.String(20), nullable=True)
    is_locked = db.Column(db.Boolean, default=False)
    locked_by_name = db.Column(db.String(50), nullable=True)
    locked_by_role = db.Column(db.String(20), nullable=True)

    family_members = db.relationship('FamilyMember', backref='user', lazy=True, cascade="all, delete-orphan")
    managers = db.relationship('Admin', secondary=user_admin_m2m, backref=db.backref('managed_users', lazy=True))
    reports = db.relationship('PublicHealthEvent', backref='reporter', lazy=True)

    def set_password(self, password): self.password_hash = generate_password_hash(password)

    def check_password(self, password): return check_password_hash(self.password_hash, password)


class FamilyMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(50), nullable=False)
    relation = db.Column(db.String(20), nullable=False)
    gender = db.Column(db.String(10), nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    age = db.Column(db.Integer, nullable=True)
    province = db.Column(db.String(50), nullable=True)
    city = db.Column(db.String(50), nullable=True)
    community = db.Column(db.String(100), nullable=True)
    address = db.Column(db.String(200), nullable=True)
    height = db.Column(db.Float, nullable=True)
    weight = db.Column(db.Float, nullable=True)
    blood_pressure_systolic = db.Column(db.Integer, nullable=True)
    blood_pressure_diastolic = db.Column(db.Integer, nullable=True)
    disease_info = db.Column(db.Text, nullable=True)
    is_public_health_risk = db.Column(db.Boolean, default=False)

    # 核心新增：管理员针对该成员的专属健康指导/医嘱
    admin_advice = db.Column(db.Text, nullable=True)

    medical_reports = db.relationship('MedicalReport', backref='member', lazy=True, cascade="all, delete-orphan")


class MedicalReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey('family_member.id'), nullable=False)
    uploader_role = db.Column(db.String(20), nullable=False)  # 'user' or 'admin'
    file_path = db.Column(db.String(200), nullable=False)
    upload_time = db.Column(db.DateTime, default=datetime.utcnow)
    is_read_by_admin = db.Column(db.Boolean, default=False)


class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    role = db.Column(db.String(20), nullable=False)
    province = db.Column(db.String(50), nullable=True)
    city = db.Column(db.String(50), nullable=True)
    community = db.Column(db.String(100), nullable=True)
    medical_org = db.Column(db.String(100), nullable=True)
    is_frozen = db.Column(db.Boolean, default=False)
    frozen_by_name = db.Column(db.String(50), nullable=True)
    frozen_by_role = db.Column(db.String(20), nullable=True)

    def set_password(self, password): self.password_hash = generate_password_hash(password)

    def check_password(self, password): return check_password_hash(self.password_hash, password)


class PublicHealthEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    disease_category = db.Column(db.String(50), nullable=False)
    disease_sub_category = db.Column(db.String(50), nullable=True)
    disease_specific = db.Column(db.String(100), nullable=True)
    province = db.Column(db.String(50), nullable=False)
    city = db.Column(db.String(50), nullable=False)
    community = db.Column(db.String(100), nullable=False)
    specific_location = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    contact = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), default='pending')
    is_severe = db.Column(db.Boolean, default=False)
    is_locked = db.Column(db.Boolean, default=False)
    escalation_note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Notice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    target_audience = db.Column(db.String(20), default='all')
    target_province = db.Column(db.String(50), nullable=True)
    target_city = db.Column(db.String(50), nullable=True)
    target_community = db.Column(db.String(100), nullable=True)
    sender_name = db.Column(db.String(50), nullable=True)
    sender_role = db.Column(db.String(20), nullable=True)
    is_pinned = db.Column(db.Boolean, default=False)
    is_locked = db.Column(db.Boolean, default=False)
    create_time = db.Column(db.DateTime, default=datetime.utcnow)
    is_hidden = db.Column(db.Boolean, default=False)


class DiseaseKnowledge(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50), nullable=False)
    sub_category = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False, unique=True)
    cause = db.Column(db.Text, nullable=True)
    symptoms = db.Column(db.Text, nullable=True)
    prevention = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)