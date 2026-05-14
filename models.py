"""
models.py — NutriPLAN AI
Database models (tables) defined using SQLAlchemy ORM.
Each class represents one table in the database.
"""

from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

# Shared SQLAlchemy instance — initialised in main.py via db.init_app(app)
db = SQLAlchemy()


class User(db.Model):
    """
    Represents a registered user.
    Stores authentication credentials and physical profile data
    needed to generate personalised meal plans.
    """
    __tablename__ = 'users'

    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(100), nullable=False)
    email      = db.Column(db.String(150), unique=True, nullable=False)  # must be unique across all users
    password   = db.Column(db.String(256), nullable=False)               # stored as a bcrypt hash, never plain text
    age        = db.Column(db.Integer, nullable=False)
    gender     = db.Column(db.String(10), nullable=False, default='male')
    height_cm  = db.Column(db.Integer, nullable=False)                   # always stored in cm (imperial input converted by JS)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)        # automatically set on registration

    # One-to-many: one user can have many meal plans
    # cascade='all, delete-orphan' means plans are deleted when the user is deleted
    meal_plans = db.relationship('MealPlan', backref='user', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        """String representation for debugging (e.g. in the Flask shell)."""
        return f'<User {self.email}>'


class MealPlan(db.Model):
    """
    Represents a saved weekly meal plan.
    The full plan (all 7 days, meals, calories) is stored as a JSON string
    in plan_data — this avoids needing separate tables for days and meals,
    keeping the schema simple for this project.
    """
    __tablename__ = 'meal_plans'

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)  # foreign key → users table
    title      = db.Column(db.String(150), nullable=False, default='My Meal Plan') # user-chosen plan name
    plan_data  = db.Column(db.Text, nullable=False)                                 # full plan serialised as JSON
    created_at = db.Column(db.DateTime, default=datetime.utcnow)                   # automatically set on save

    def __repr__(self):
        """String representation for debugging."""
        return f'<MealPlan {self.id} user={self.user_id}>'
