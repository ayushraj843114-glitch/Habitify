import calendar
import os
from datetime import date, datetime, timedelta

from flask import Flask, flash, redirect, render_template, request, url_for
from flask_login import (LoginManager, current_user, login_required,
                         login_user, logout_user)
from sqlalchemy import inspect, text

from models import Habit, HabitLog, User, db

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///habit_tracker.db"
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-in-production")
db.init_app(app)

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)

def ensure_habit_log_completed_at():
    inspector = inspect(db.engine)
    if "habit_log" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("habit_log")}
    if "completed_at" not in columns:
        db.session.execute(text("ALTER TABLE habit_log ADD COLUMN completed_at DATETIME"))
        db.session.commit()


with app.app_context():
    db.create_all()
    ensure_habit_log_completed_at()


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def find_user(username):
    return User.query.filter(db.func.lower(User.username) == username.lower()).first()


# ---------------------------------------------------------------- Auth

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if len(username) < 3:
            flash("Username must be at least 3 characters long.", "error")
        elif len(password) < 6:
            flash("Password must be at least 6 characters long.", "error")
        elif find_user(username):
            flash("That username is already taken. Please choose another.", "error")
        else:
            user = User(username=username)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash("Welcome to HabitFlow! Add your first habit to get started.", "success")
            return redirect(url_for("index"))
        return redirect(url_for("register"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = find_user(username)
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for("index"))
        flash("Incorrect username or password.", "error")
        return redirect(url_for("login"))
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been signed out.", "success")
    return redirect(url_for("login"))


# ---------------------------------------------------------------- Habits

@app.route("/")
@login_required
def index():
    today = date.today()
    habits = (Habit.query.filter_by(user_id=current_user.id)
              .order_by(Habit.id.asc()).all())

    # Last 7 days (oldest -> today) for the weekly strip on each habit.
    week = [today - timedelta(days=i) for i in range(6, -1, -1)]
    week_done = {}
    ids = [h.id for h in habits]
    if ids:
        logs = HabitLog.query.filter(HabitLog.habit_id.in_(ids),
                                     HabitLog.date_done >= week[0]).all()
        for log in logs:
            week_done.setdefault(log.habit_id, set()).add(log.date_done)

    hour = datetime.now().hour
    greeting = ("Good morning" if hour < 12
                else "Good afternoon" if hour < 17 else "Good evening")

    return render_template("index.html", habits=habits, today=today, week=week,
                           week_done=week_done, greeting=greeting)


@app.route("/add", methods=["GET", "POST"])
@login_required
def add_habit():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Please enter a habit name.", "error")
            return redirect(url_for("add_habit"))
        db.session.add(Habit(name=name[:100], user_id=current_user.id))
        db.session.commit()
        flash(f"Habit \u201c{name[:100]}\u201d added.", "success")
        return redirect(url_for("index"))
    return render_template("add_habit.html")


@app.route("/toggle/<int:habit_id>", methods=["POST"])
@login_required
def toggle_habit(habit_id):
    habit = Habit.query.filter_by(id=habit_id, user_id=current_user.id).first_or_404()
    if habit.last_done == date.today():
        habit.undo_today()
    else:
        habit.mark_done_today()
    db.session.commit()
    return redirect(url_for("index"))


@app.route("/delete/<int:habit_id>", methods=["POST"])
@login_required
def delete_habit(habit_id):
    habit = Habit.query.filter_by(id=habit_id, user_id=current_user.id).first_or_404()
    db.session.delete(habit)
    db.session.commit()
    flash("Habit deleted.", "success")
    return redirect(url_for("index"))


# ---------------------------------------------------------------- History

@app.route("/history")
@app.route("/history/<int:year>/<int:month>")
@login_required
def history(year=None, month=None):
    today = date.today()
    year = year or today.year
    month = month or today.month
    if not 1 <= month <= 12 or not 1900 <= year <= 3000:
        return redirect(url_for("history"))

    days_in_month = calendar.monthrange(year, month)[1]
    habits = (Habit.query.filter_by(user_id=current_user.id)
              .order_by(Habit.id.asc()).all())

    done = {}
    completion_times = {}
    ids = [h.id for h in habits]
    if ids:
        first = date(year, month, 1)
        last = date(year, month, days_in_month)
        logs = HabitLog.query.filter(HabitLog.habit_id.in_(ids),
                                     HabitLog.date_done >= first,
                                     HabitLog.date_done <= last).all()
        for log in logs:
            day = log.date_done.day
            done.setdefault(log.habit_id, set()).add(day)
            if log.completed_at:
                stamp = log.completed_at.strftime("%I:%M %p").lstrip("0")
            else:
                stamp = "Time not recorded"
            completion_times.setdefault(log.habit_id, {})[day] = stamp

    # Days that have already happened in the shown month (for the % rate).
    if (year, month) == (today.year, today.month):
        elapsed = today.day
    elif (year, month) < (today.year, today.month):
        elapsed = days_in_month
    else:
        elapsed = 0

    prev_year, prev_month = (year, month - 1) if month > 1 else (year - 1, 12)
    next_year, next_month = (year, month + 1) if month < 12 else (year + 1, 1)

    return render_template(
        "history.html",
        habits=habits,
        done=done,
        completion_times=completion_times,
        year=year,
        month=month,
        month_name=calendar.month_name[month], days=range(1, days_in_month + 1),
        today=today, elapsed=elapsed,
        prev_year=prev_year, prev_month=prev_month,
        next_year=next_year, next_month=next_month)


if __name__ == "__main__":
    app.run(debug=True, use_reloader=True)