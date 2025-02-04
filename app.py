from flask import Flask, redirect, render_template, flash, session, g
from flask_debugtoolbar import DebugToolbarExtension
from sqlalchemy import exc
from forms import UserAddForm, UserLoginForm, EditUserForm, UserFavoritesForm
from handlers import handle_game_choices, handle_signup_errors, random_user
from models import Match, connect_db, db, User, Favorites, AcceptedMatches

CURR_USER_KEY = "curr_user"

app = Flask(__name__)

if app.config["ENV"] == "production":
    app.config.from_object('config.ProductionConfig')
elif app.config["ENV"] == "testing":
    app.config.from_object('config.TestingConfig')
else:
    app.config.from_object('config.DevelopmentConfig')
    
toolbar = DebugToolbarExtension(app)

connect_db(app)

########################################################
# User Signup/Login/Logout Routes:

@app.before_request
def add_user_to_g():
    """If logged in, add current user to Flask global."""

    if CURR_USER_KEY in session:
        g.user = User.query.get(session[CURR_USER_KEY])

    else:
        g.user = None


def do_login(user):
    """Log in user."""

    session[CURR_USER_KEY] = user.id


def do_logout():
    """Logout user."""

    if CURR_USER_KEY in session:
        del session[CURR_USER_KEY]

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    """Handle user signup"""

    form = UserAddForm()

    if form.validate_on_submit():
        # Attempt to create a user

        errors = handle_signup_errors(form.username.data, form.email.data, None)
        if errors:
            return render_template('users/signup.html', form=form)

        try:
            User.signup(
                username=form.username.data,
                email=form.email.data,
                password=form.password.data,
                first_name=form.first_name.data,
                last_name=form.last_name.data,
                image_url=form.image_url.data or User.image_url.default.arg
            )
            db.session.commit()

            return redirect('/login')
        # If db errors, redirect back to try again
        except exc.SQLAlchemyError as e:
            print(f'ERROR TYPE: {type(e)}')
            flash('Something went wrong. Please try again.', 'danger')
            return redirect('/signup')
    else:
        return render_template('users/signup.html', form=form)

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Handle user login"""

    form = UserLoginForm()

    if form.validate_on_submit():
        user = User.authenticate(form.username.data, form.password.data)

        if user:
            do_login(user)
            add_user_to_g()
            # If user hasn't setup their favorites then redirect to /favorites
            if not g.user.favorites_id:
                flash(f"Welcome, {user.first_name}! Please enter some of your gaming preferences so others can match with you better. 😊", "success")
                return redirect('/favorites')

            flash(f"Welcome Back, {user.first_name}!", "success")
            return redirect('/')
        
        flash("Invalid credentials.", "danger")

    return render_template('users/login.html', form=form)

@app.route('/logout')
def logout():
    """Handle logout of user"""

    do_logout()
    flash("You have been logged out", "success")
    return redirect('/login')

########################################################
# Set Favorites Route:

@app.route('/favorites')
def show_favorites_form():
    """Show form for user to add their favorites"""

    if g.user.favorites_id:
        return redirect('/')

    form = UserFavoritesForm()

    # Handle Favorite Game Choices
    form.game1.choices = handle_game_choices()
    form.game2.choices = handle_game_choices()
    form.game3.choices = handle_game_choices()

    return render_template('users/set_favorites.html', form=form)

@app.route('/favorites', methods=["POST"])
def set_user_favorites():
    """Handle initial setup of user favorites."""

    form = UserFavoritesForm()

    # Add user favorites to db
    try:
        favorites = Favorites(
            role=form.role.data,
            system=form.system.data,
            game1=form.game1.data,
            game2=form.game2.data,
            game3=form.game3.data,
            user_id=g.user.id
        )
        db.session.add(favorites)
        db.session.commit()

        g.user.favorites_id = favorites.id
        db.session.commit()

        flash("Your favorites have been saved! Edit them at anytime from your profile.", "success")
        return redirect('/')
    except exc.SQLAlchemyError as e:
        print(f'ERROR TYPE: {type(e)}')
        flash('Something went wrong. Please try again.', 'danger')
        return redirect('/favorites')

########################################################
# General User Routes:

@app.route('/users/<int:user_id>')
def show_user_profile(user_id):
    """Show user's profile"""

    if not g.user:
        return redirect("/")

    user = User.query.get_or_404(user_id)
    favorites = Favorites.query.filter_by(user_id=user.id).one_or_none()
    matches = user.all_matches()
    match_ids = []

    for u in matches:
        match_ids.append(u.id)

    return render_template('users/detail.html', user=user, favorites=favorites, matches=matches, match_ids=match_ids)

@app.route('/users/<int:user_id>/edit')
def show_edit_profile_form(user_id):
    """Show form to edit user's profile."""

    if not g.user:
        flash("Access unauthorized.", "danger")
        return redirect("/")

    user = User.query.get_or_404(user_id)
    favorites = Favorites.query.filter_by(user_id=user.id).one_or_none()

    form = EditUserForm()

    # Set user data into form for editing
    form.username.data = user.username
    form.email.data = user.email
    form.first_name.data = user.first_name
    form.last_name.data = user.last_name
    form.bio.data = user.bio
    form.discord_username.data = user.discord_username
    form.image_url.data = user.image_url
    if favorites:
        form.role.data = favorites.role
        form.system.data = favorites.system
        form.game1.data = favorites.game1
        form.game2.data = favorites.game2
        form.game3.data = favorites.game3

    # Handle Favorite Game Choices
    form.game1.choices = handle_game_choices()
    form.game2.choices = handle_game_choices()
    form.game3.choices = handle_game_choices()

    return render_template('users/edit.html', form=form, user=user)

@app.route('/users/<int:user_id>/edit', methods=["POST"])
def edit_user_profile(user_id):
    """Edit user's profile"""

    if not g.user:
        flash("Access unauthorized.", "danger")
        return redirect("/")

    user = User.query.get_or_404(user_id)
    favorites = Favorites.query.filter_by(user_id=user.id).one_or_none()

    form = EditUserForm()

    errors = handle_signup_errors(form.username.data, form.email.data, user.id)
    if errors:
        return redirect(f'/users/{user.id}/edit')

    if User.authenticate(user.username,form.password.data):
        # Update user account information
        user.username = form.username.data,
        user.email = form.email.data,
        user.first_name = form.first_name.data,
        user.last_name = form.last_name.data,
        user.bio = form.bio.data,
        user.discord_username = form.discord_username.data,
        user.image_url = form.image_url.data or User.image_url.default.arg,
                
        # If user hasn't set up their favorites yet, create a new Favorites Instance for the user
        if not favorites:
            new_favorites = Favorites(
                role=form.role.data,
                system=form.system.data,
                game1=form.game1.data,
                game2=form.game2.data,
                game3=form.game3.data,
                user_id=user.id
            )
            db.session.add(new_favorites)
            db.session.commit()
            user.favorites_id = new_favorites.id

        else:
            # Update user favorites
            favorites.role = form.role.data,
            favorites.system = form.system.data,
            favorites.game1 = form.game1.data,
            favorites.game2 = form.game2.data,
            favorites.game3 = form.game3.data,

        db.session.commit()
        return redirect(f"/users/{user.id}")
    else:        
        flash('Wrong password!', 'danger')
        return redirect(f'/users/{user.id}/edit')

@app.route('/users/delete', methods=["POST"])
def delete_user():
    """Delete user."""

    if not g.user:
        flash("Access unauthorized.", "danger")
        return redirect("/")

    do_logout()

    db.session.delete(g.user)
    db.session.commit()

    return redirect("/signup")

########################################################
# Homepage:

@app.route('/')
def show_homepage():
    """Show homepage"""

    # If not logged in, display homepage that links to signup
    if not g.user:
        return render_template('home-anon.html')

    # Pick a random, not matched, user to offer as a match
    other_user = random_user()[0]

    # Check if the random user is already matched with logged in user
    already_matched = AcceptedMatches.query.filter(g.user.id == AcceptedMatches.user1_id, other_user.id == AcceptedMatches.user2_id).one_or_none()

    # Make sure random user is... not the logged in user, has favorites already set, and not a previous match
    if other_user == g.user or other_user.favorites_id == None or other_user in g.user.matches or already_matched != None:
        return redirect('/')

    # Queries Favorites to display the random user's profile
    other_user_favorites = Favorites.query.filter_by(user_id=other_user.id).one_or_none()

    return render_template('home.html', other_user=other_user, other_user_favorites=other_user_favorites)

@app.route('/<int:other_user_id>', methods=["POST"])
def match_users(other_user_id):
    """Accept a match between 2 users"""

    user = g.user
    user2 = User.query.get_or_404(other_user_id)

    match = user.accepts_match(other_user_id)

    # If the second user accepts the match, then captures the accepted match in the AcceptedMatches table and notifies the user
    if match.user1_accepted == True and match.user2_accepted == True:
        flash("You are a match! Visit your matches page to view your new match! 😄", "success")
        accepted_match = AcceptedMatches(user1_id=user.id, user2_id=user2.id)
        db.session.add(accepted_match)
        db.session.commit()
    
    return redirect('/')

########################################################
# General Match Routes:

@app.route('/matches')
def show_matches():
    """Show user matches"""

    if not g.user:
        flash("Access unauthorized.", "danger")
        return redirect("/")

    all_matches = g.user.all_matches()

    if len(all_matches) == 0:
        flash("You don't have any matches yet, let's make some matches!", "success")
        return redirect('/')

    return render_template('users/matches.html', matches=all_matches)

@app.route('/matches/<int:other_user_id>/delete', methods=["POST"])
def delete_match(other_user_id):
    """Deletes the match between two users"""

    matched_user = User.query.get_or_404(other_user_id)

    potential_match = Match.query.filter(g.user.id == Match.user1_id, matched_user.id == Match.user2_id).one_or_none()
    if not potential_match:
        potential_match = Match.query.filter(g.user.id == Match.user2_id, matched_user.id == Match.user1_id).one_or_none()

    accepted_match = AcceptedMatches.query.filter(g.user.id == AcceptedMatches.user1_id, matched_user.id == AcceptedMatches.user2_id).one_or_none()
    if not accepted_match:
        accepted_match = AcceptedMatches.query.filter(g.user.id == AcceptedMatches.user2_id, matched_user.id == AcceptedMatches.user1_id).one_or_none()

    db.session.delete(potential_match)
    db.session.delete(accepted_match)
    db.session.commit()

    return redirect('/matches')