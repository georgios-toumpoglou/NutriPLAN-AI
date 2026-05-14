"""
main.py — NutriPLAN AI
Core Flask application: configuration, routes, and Anthropic API integration.
"""

import os
import anthropic
import json
from dotenv import load_dotenv
from flask import Flask, render_template, redirect, url_for, flash, session, request
from flask_wtf.csrf import CSRFProtect
from models import db, User, MealPlan
from forms import SignUpForm, LoginForm
from werkzeug.security import generate_password_hash, check_password_hash

# Load environment variables from .env file (API key, secret key, etc.)
load_dotenv()

app = Flask(__name__)

# ── APP CONFIGURATION ──────────────────────────────────────────────────────────

# SQLite database file stored locally
app.config['SQLALCHEMY_DATABASE_URI']        = 'sqlite:///nutriplan.db'
# Disable event tracking — not needed and wastes memory
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Secret key for session signing and CSRF protection — loaded from .env
app.config['SECRET_KEY']                     = os.getenv('SECRET_KEY', 'fallback-secret')

# ── EXTENSIONS ─────────────────────────────────────────────────────────────────

# Enable CSRF protection on all POST forms
csrf = CSRFProtect(app)
# Bind SQLAlchemy to this Flask app
db.init_app(app)

# ── JINJA2 CUSTOM FILTER ───────────────────────────────────────────────────────

@app.template_filter('from_json')
def from_json_filter(value):
    """
    Custom Jinja2 filter that parses a JSON string into a Python dict.
    Used in templates to access plan_data fields directly.
    Returns an empty dict if parsing fails.
    """
    try:
        return json.loads(value)
    except Exception:
        return {}

# Create all database tables on startup if they don't exist yet
with app.app_context():
    db.create_all()


# ── ROUTES ─────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    """Render the public landing page."""
    return render_template('index.html')


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    """
    Handle user registration.
    GET  — display the sign-up form.
    POST — validate input, create a new user, redirect to home with a success message.
    Note: height_cm is a plain hidden input (not a WTForms field) because the
    visible inputs (metric/imperial) are handled by JavaScript before submission.
    """
    form = SignUpForm()

    if form.validate_on_submit():

        # Validate height_cm separately (plain hidden input, bypasses WTForms)
        try:
            height_cm = int(request.form.get('height_cm', 0))
            if height_cm < 50 or height_cm > 250:
                raise ValueError
        except (ValueError, TypeError):
            flash('Please enter a valid height.', 'error')
            return render_template('signup.html', form=form)

        # Prevent duplicate registrations
        if User.query.filter_by(email=form.email.data).first():
            flash('This e-mail is already registered. Please log in.', 'error')
            return render_template('signup.html', form=form)

        # Hash the password before storing — never store plain text passwords
        new_user = User(
            name      = form.name.data,
            email     = form.email.data,
            password  = generate_password_hash(form.password.data),
            age       = form.age.data,
            gender    = form.gender.data,
            height_cm = height_cm,
        )
        db.session.add(new_user)
        db.session.commit()

        flash('Your account was created successfully! You can now log in.', 'success')
        return redirect(url_for('index'))

    return render_template('signup.html', form=form)


@app.route('/login', methods=['GET', 'POST'])
def login():
    """
    Handle user login.
    GET  — display the login form.
    POST — verify credentials, start a session, redirect to Generate Plan page.
    Stores user_id and user_name in session for use across all protected routes.
    """
    form = LoginForm()

    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()

        # check_password_hash compares the submitted password against the stored hash
        if user and check_password_hash(user.password, form.password.data):
            session['user_id']   = user.id
            session['user_name'] = user.name
            flash(f'Welcome back, {user.name}!', 'success')
            return redirect(url_for('generate_plan'))
        else:
            flash('Incorrect e-mail or password.', 'error')

    return render_template('login.html', form=form)


@app.route('/logout')
def logout():
    """Clear the session and redirect to the landing page."""
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('index'))


@app.route('/dashboard')
def dashboard():
    """
    Dashboard route — reserved for future use.
    Currently redirects authenticated users elsewhere.
    """
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    return render_template('dashboard.html', user=user)


@app.route('/generate-plan', methods=['GET', 'POST'])
def generate_plan():
    """
    Handle the meal plan generation form.
    GET  — display the form (diet, goal, activity, weight).
    POST — collect form data, call the Anthropic API via call_claude(),
           store the result in the session, redirect to the result page.
    Plan parameters are also stored in session so Regenerate can reuse them.
    """
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        user = User.query.get(session['user_id'])

        # Collect user choices from the form
        diet     = request.form.get('diet', 'anything')
        goal     = request.form.get('goal', 'keep')
        activity = request.form.get('activity', 'moderate')
        weight   = request.form.get('weight_kg', '70')

        # Save params in session so Regenerate can reuse them with modifications
        session['plan_params'] = {
            'diet': diet, 'goal': goal,
            'activity': activity, 'weight': weight
        }

        plan = call_claude(user, diet, goal, activity, weight)
        if plan:
            session['current_plan'] = plan
            return redirect(url_for('plan_result'))
        else:
            flash('Something went wrong. Please try again.', 'error')

    return render_template('generate_plan.html')


def call_claude(user, diet, goal, activity, weight, changes=None):
    """
    Call the Anthropic Claude API to generate a 7-day meal plan.

    Builds a detailed prompt using the user's profile (age, gender, height,
    weight, goal, diet preference, activity level) and requests a strictly
    formatted JSON response.

    If 'changes' is provided (Regenerate flow), the prompt instructs Claude
    to modify the previous plan accordingly.

    Returns a parsed Python dict on success, or None on failure.
    """
    # Human-readable mappings for the prompt
    goal_map = {
        'lose': 'lose weight',
        'keep': 'maintain weight',
        'gain': 'gain muscle'
    }
    activity_map = {
        'sedentary': 'sedentary (little or no exercise)',
        'light':     'lightly active (1-3 days/week)',
        'moderate':  'moderately active (3-5 days/week)',
        'active':    'very active (6-7 days/week)'
    }

    # Build the nutritionist prompt with the user's full profile
    prompt = f"""You are a professional nutritionist. Create a 7-day meal plan for:
- Name: {user.name}
- Gender: {user.gender}
- Age: {user.age} years
- Height: {user.height_cm} cm
- Weight: {weight} kg
- Goal: {goal_map.get(goal, goal)}
- Diet preference: {diet}
- Activity level: {activity_map.get(activity, activity)}
"""
    # If this is a Regenerate request, append the user's requested changes
    if changes:
        prompt += f"\nModify the previous plan with these changes: {changes}\n"

    # Strict JSON format instruction — prevents markdown or explanation in response
    prompt += """
Return ONLY a valid JSON object (no markdown, no explanation) in this exact format:
{
  "calories_per_day": 2000,
  "diet": "mediterranean",
  "days": [
    {
      "day": "Day 1",
      "breakfast": {"name": "...", "description": "..."},
      "lunch":     {"name": "...", "description": "..."},
      "dinner":    {"name": "...", "description": "..."},
      "snack":     {"name": "...", "description": "..."}
    }
  ]
}
Include all 7 days. calories_per_day should be the recommended daily caloric intake based on the user's profile and goal."""

    try:
        # Initialise the Anthropic client using the API key from .env
        client  = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
        message = client.messages.create(
            model      = "claude-sonnet-4-5",
            max_tokens = 4000,
            messages   = [{"role": "user", "content": prompt}]
        )
        raw = message.content[0].text.strip()

        # Strip markdown code fences if Claude wraps the JSON in ```json ... ```
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        return json.loads(raw.strip())

    except Exception as e:
        print(f"Claude API error: {e}")
        return None


@app.route('/plan-result')
def plan_result():
    """
    Display the generated meal plan stored in the session.
    Redirects to Generate Plan if no plan exists in session.
    """
    if 'user_id' not in session:
        return redirect(url_for('login'))
    plan = session.get('current_plan')
    if not plan:
        return redirect(url_for('generate_plan'))
    return render_template('plan_result.html', plan=plan)


@app.route('/regenerate', methods=['POST'])
def regenerate():
    """
    Regenerate the meal plan with user-requested modifications.
    Retrieves the original plan parameters from the session,
    appends the user's change instructions, and calls Claude again.
    """
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user    = User.query.get(session['user_id'])
    params  = session.get('plan_params', {})
    changes = request.form.get('changes', '')

    plan = call_claude(
        user,
        params.get('diet', 'anything'),
        params.get('goal', 'keep'),
        params.get('activity', 'moderate'),
        params.get('weight', '70'),
        changes=changes
    )
    if plan:
        session['current_plan'] = plan
    else:
        flash('Something went wrong. Please try again.', 'error')

    return redirect(url_for('plan_result'))


@app.route('/save-plan', methods=['POST'])
def save_plan():
    """
    Save the current plan from session to the database.
    Stores the user's chosen diet (not Claude's interpretation) and
    the goal/weight used so the My Plans card can display them.
    Clears the plan from session after saving.
    """
    if 'user_id' not in session:
        return redirect(url_for('login'))

    plan   = session.get('current_plan')
    title  = request.form.get('plan_title', 'My Meal Plan').strip()
    params = session.get('plan_params', {})

    if not plan:
        flash('No plan to save.', 'error')
        return redirect(url_for('generate_plan'))

    # Attach metadata to the plan before saving
    plan['meta'] = {
        'weight': params.get('weight'),
        'goal':   params.get('goal'),
        'diet':   params.get('diet', 'anything'),
    }
    # Always use the user's chosen diet — not Claude's interpretation
    plan['diet'] = params.get('diet', 'anything')

    new_plan = MealPlan(
        user_id   = session['user_id'],
        title     = title or 'My Meal Plan',
        plan_data = json.dumps(plan)   # Serialise the full plan as JSON text
    )
    db.session.add(new_plan)
    db.session.commit()

    # Remove plan from session — it has been persisted to the database
    session.pop('current_plan', None)
    flash(f'"{title}" saved successfully!', 'success')
    return redirect(url_for('my_plans'))


@app.route('/my-plans')
def my_plans():
    """
    Display all saved meal plans for the logged-in user,
    ordered by most recently created first.
    """
    if 'user_id' not in session:
        return redirect(url_for('login'))
    plans = MealPlan.query.filter_by(
        user_id=session['user_id']
    ).order_by(MealPlan.created_at.desc()).all()
    return render_template('my_plans.html', plans=plans)


@app.route('/delete-plan/<int:plan_id>', methods=['POST'])
def delete_plan(plan_id):
    """
    Delete a saved plan by ID.
    Verifies ownership (user_id) before deleting to prevent
    one user from deleting another user's plans.
    """
    if 'user_id' not in session:
        return redirect(url_for('login'))
    plan = MealPlan.query.filter_by(id=plan_id, user_id=session['user_id']).first()
    if plan:
        db.session.delete(plan)
        db.session.commit()
        flash('Plan deleted.', 'success')
    return redirect(url_for('my_plans'))


@app.route('/view-plan/<int:plan_id>')
def view_plan(plan_id):
    """
    View a previously saved plan.
    Deserialises the JSON plan_data from the database and passes
    the title and ID to the template so it can show the correct
    buttons (Back / Delete instead of Save / Regenerate).
    """
    if 'user_id' not in session:
        return redirect(url_for('login'))
    plan = MealPlan.query.filter_by(id=plan_id, user_id=session['user_id']).first()
    if not plan:
        flash('Plan not found.', 'error')
        return redirect(url_for('my_plans'))
    plan_data = json.loads(plan.plan_data)
    return render_template(
        'plan_result.html',
        plan             = plan_data,
        saved_plan_title = plan.title,
        saved_plan_id    = plan.id
    )


@app.route('/profile', methods=['GET', 'POST'])
def profile():
    """
    Display and update the user's profile.
    GET  — show current profile data (name, email, age, gender, height).
    POST — validate and save changes to name, age, and height.
           Email and gender cannot be changed after registration.
    Also updates the session user_name if the name changes.
    """
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])

    if request.method == 'POST':
        try:
            new_name   = request.form.get('name', '').strip()
            new_age    = int(request.form.get('age', 0))
            new_height = int(request.form.get('height_cm', 0))

            # Server-side validation (mirrors the front-end checks)
            if not new_name or len(new_name) < 2:
                flash('Name must be at least 2 characters.', 'error')
            elif new_age < 10 or new_age > 120:
                flash('Please enter a valid age.', 'error')
            elif new_height < 50 or new_height > 250:
                flash('Please enter a valid height.', 'error')
            else:
                user.name      = new_name
                user.age       = new_age
                user.height_cm = new_height
                # Keep session name in sync with the updated name
                session['user_name'] = new_name
                db.session.commit()
                flash('Profile updated successfully!', 'success')

        except (ValueError, TypeError):
            flash('Invalid input. Please check your values.', 'error')

    return render_template('profile.html', user=user)


# ── ENTRY POINT ────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    # host='0.0.0.0' makes the app accessible on the local network (mobile testing)
    # debug=True enables auto-reload and detailed error pages — disable in production
    app.run(debug=True, host='0.0.0.0')
