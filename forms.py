"""
forms.py — NutriPLAN AI
WTForms form definitions for Sign Up and Log In.
WTForms handles validation, CSRF protection, and HTML field rendering.
"""

from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, IntegerField, RadioField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, NumberRange


class SignUpForm(FlaskForm):
    """
    Registration form.
    Collects the user's name, email, age, gender, and password.
    Note: height_cm is NOT included here — it is handled as a plain
    hidden HTML input so that JavaScript can convert imperial to metric
    before submission. It is validated manually in the signup route.
    """

    name = StringField('Name', validators=[
        DataRequired(message='Name is required.'),
        Length(min=2, max=100, message='Name must be between 2 and 100 characters.')
    ])

    email = StringField('E-mail', validators=[
        DataRequired(message='E-mail is required.'),
        Email(message='Please enter a valid e-mail address.')     # requires email-validator package
    ])

    age = IntegerField('Age', validators=[
        DataRequired(message='Age is required.'),
        NumberRange(min=10, max=120, message='Please enter a valid age.')
    ])

    # Radio buttons with two options — default is 'male'
    gender = RadioField(
        'Gender',
        choices   = [('male', 'Male'), ('female', 'Female')],
        default   = 'male',
        validators= [DataRequired()]
    )

    # height_cm intentionally omitted — handled as a hidden input in the template

    password = PasswordField('Password', validators=[
        DataRequired(message='Password is required.'),
        Length(min=6, message='Password must be at least 6 characters.')
    ])

    # EqualTo checks that this field matches the 'password' field above
    confirm_password = PasswordField('Confirm Password', validators=[
        DataRequired(message='Please confirm your password.'),
        EqualTo('password', message='Passwords must match.')
    ])

    submit = SubmitField('Create Account')


class LoginForm(FlaskForm):
    """
    Login form.
    Only requires email and password — all other validation
    (checking the hash, verifying the user exists) is done in the route.
    """

    email = StringField('E-mail', validators=[
        DataRequired(message='E-mail is required.'),
        Email(message='Please enter a valid e-mail address.')
    ])

    password = PasswordField('Password', validators=[
        DataRequired(message='Password is required.')
    ])

    submit = SubmitField('Log In')
