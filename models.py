from datetime import date, datetime, timedelta

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    habits = db.relationship("Habit", backref="owner", lazy=True,
                             cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Habit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    streak = db.Column(db.Integer, default=0)
    last_done = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    logs = db.relationship("HabitLog", backref="habit", lazy=True,
                           cascade="all, delete-orphan")

    @property
    def current_streak(self):
        """Streak shown to the user. It is 0 if the chain was broken."""
        if self.last_done and self.last_done >= date.today() - timedelta(days=1):
            return self.streak or 0
        return 0

    def recalculate(self):
        """Rebuild streak and last_done from the completion logs."""
        days = sorted({log.date_done for log in self.logs}, reverse=True)
        if not days:
            self.streak = 0
            self.last_done = None
            return
        streak = 1
        for newer, older in zip(days, days[1:]):
            if newer - older == timedelta(days=1):
                streak += 1
            else:
                break
        self.streak = streak
        self.last_done = days[0]

    def mark_done_today(self):
        today = date.today()
        if any(log.date_done == today for log in self.logs):
            return
        self.logs.append(HabitLog(date_done=today, completed_at=datetime.now()))
        self.recalculate()

    def undo_today(self):
        today = date.today()
        for log in list(self.logs):
            if log.date_done == today:
                self.logs.remove(log)  # delete-orphan removes the row
        self.recalculate()


class HabitLog(db.Model):
    """One row = one day on which a habit was completed."""
    id = db.Column(db.Integer, primary_key=True)
    habit_id = db.Column(db.Integer, db.ForeignKey("habit.id"), nullable=False)
    date_done = db.Column(db.Date, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)