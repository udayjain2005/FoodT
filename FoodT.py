from flask import Flask, render_template, redirect, url_for, request, session, flash, Response, abort
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import calendar
import random
import json
import os
import csv
import io
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key_here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///foodt.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB upload limit

# Ensure static/food_images directory exists at startup
STATIC_IMAGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'food_images')
if not os.path.exists(STATIC_IMAGE_DIR):
    os.makedirs(STATIC_IMAGE_DIR)

db = SQLAlchemy(app)

# User model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

# Food item model
class FoodItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    calories = db.Column(db.Integer, default=0)
    image_filename = db.Column(db.String(200), nullable=True)  # New field for image
    category = db.Column(db.String(50), nullable=True)  # New field
    rating = db.Column(db.Float, default=0.0)           # New field
    comments = db.relationship('FoodComment', backref='food', lazy=True)

class FoodComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    food_id = db.Column(db.Integer, db.ForeignKey('food_item.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    content = db.Column(db.Text, nullable=False)
    rating = db.Column(db.Float, nullable=True)  # New field for rating
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User')

# User preferences (many-to-many)
user_food = db.Table('user_food',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('food_id', db.Integer, db.ForeignKey('food_item.id'))
)

# Meal plan model
class MealPlan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    month = db.Column(db.String(20), nullable=False)
    plan = db.Column(db.Text, nullable=False)  # JSON or CSV string of meals

# Initial route
@app.route('/')
def index():
    return redirect(url_for('login'))

# Register route
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            flash('Username already exists.')
            return redirect(url_for('register'))
        hashed_pw = generate_password_hash(password)
        user = User(username=username, password=hashed_pw)
        db.session.add(user)
        db.session.commit()
        flash('Registration successful. Please log in.')
        return redirect(url_for('login'))
    return render_template('register.html')

# Login route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['is_admin'] = user.is_admin
            return redirect(url_for('dashboard'))
        flash('Invalid credentials.')
    return render_template('login.html')

# Dashboard route
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html')

# Logout route
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/planner', methods=['GET', 'POST'])
def planner():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    now = datetime.now()
    month = request.form.get('month') or request.args.get('month') or now.strftime('%Y-%m')
    year, month_num = map(int, month.split('-'))
    days_in_month = calendar.monthrange(year, month_num)[1]
    plan = MealPlan.query.filter_by(user_id=user.id, month=month).first()
    
    # Get all food items for displaying images
    all_food_items = FoodItem.query.all()
    meals = []
    
    if request.method == 'POST':
        preferred = user.food_items
        if not preferred or len(preferred) == 0:
            flash('Please select your preferred food items first.')
            return redirect(url_for('food_items'))
        
        food_names = [item.name for item in preferred]
        meals = []
        recent_lunch = []
        recent_dinner = []
        
        if len(food_names) == 1:
            # If only one food item, use it for all meals
            for _ in range(days_in_month):
                meals.append({'lunch': food_names[0], 'dinner': food_names[0]})
        else:
            # Generate meals with variety
            for _ in range(days_in_month):
                available_lunch = [n for n in food_names if n not in recent_lunch[-5:]] or food_names
                lunch = random.choice(available_lunch)
                
                available_dinner = [n for n in food_names if n != lunch and n not in recent_dinner[-5:]] or [n for n in food_names if n != lunch] or food_names
                dinner = random.choice(available_dinner)
                
                meals.append({'lunch': lunch, 'dinner': dinner})
                recent_lunch.append(lunch)
                recent_dinner.append(dinner)
        
        plan_data = json.dumps(meals)
        if plan:
            plan.plan = plan_data
        else:
            plan = MealPlan(user_id=user.id, month=month, plan=plan_data)
            db.session.add(plan)
        db.session.commit()
        flash('Meal plan generated!')
    elif plan:
        meals = json.loads(plan.plan)
    
    days = [f"{year}-{month_num:02d}-{day:02d}" for day in range(1, days_in_month + 1)]
    first_day = datetime(year, month_num, 1).weekday()
    first_day = (first_day + 1) % 7  # Adjust to 0=Sunday
    
    return render_template('planner.html',
                         month=month,
                         days=days,
                         meals=meals,
                         first_day=first_day,
                         food_items=all_food_items)

@app.route('/food_items', methods=['GET', 'POST'])
def food_items():
    try:
        if 'user_id' not in session:
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        all_items = FoodItem.query.order_by(FoodItem.name).all()
        edit_id = request.args.get('edit_id', type=int)
        delete_id = request.args.get('delete_id', type=int)
        edit_item = FoodItem.query.get(edit_id) if edit_id else None
        image_dir = STATIC_IMAGE_DIR
        # Handle delete via GET param (for delete link)
        if delete_id:
            item = FoodItem.query.get(delete_id)
            if item:
                if item.image_filename:
                    file_path = os.path.join(image_dir, item.image_filename)
                    if os.path.exists(file_path):
                        try:
                            os.remove(file_path)
                        except Exception as ex:
                            app.logger.error(f"Error deleting image file: {ex}")
                            flash('Error deleting image file.')
                db.session.delete(item)
                db.session.commit()
                flash('Food item deleted!')
            else:
                flash('Food item not found.')
            return redirect(url_for('food_items'))
        if request.method == 'POST':
            action = request.form.get('action')
            if action == 'add':
                name = request.form.get('food_name', '').strip()
                category = request.form.get('category', '').strip()
                rating = float(request.form.get('rating', 0))
                file = request.files.get('food_image')
                filename = None
                if file and file.filename:
                    filename = secure_filename(file.filename)
                    file_path = os.path.join(image_dir, filename)
                    try:
                        file.save(file_path)
                    except Exception as ex:
                        app.logger.error(f"Error saving image file: {ex}")
                        flash('Error saving image file.')
                        filename = None
                if name and not FoodItem.query.filter_by(name=name).first():
                    db.session.add(FoodItem(name=name, category=category, rating=rating, image_filename=filename))
                    db.session.commit()
                    flash('Food item added!')
                else:
                    flash('Item exists or invalid.')
                return redirect(url_for('food_items'))
            elif action == 'edit' and edit_id:
                new_name = request.form.get('name', '').strip()
                if new_name and (new_name == edit_item.name or not FoodItem.query.filter_by(name=new_name).first()):
                    edit_item.name = new_name
                edit_item.calories = int(request.form['calories'])
                edit_item.category = request.form.get('category', '').strip()
                edit_item.rating = float(request.form.get('rating', edit_item.rating))
                file = request.files.get('food_image')
                if file and file.filename:
                    filename = secure_filename(file.filename)
                    file_path = os.path.join(image_dir, filename)
                    try:
                        file.save(file_path)
                        # Remove old image if exists and is different
                        if edit_item.image_filename and edit_item.image_filename != filename:
                            old_path = os.path.join(image_dir, edit_item.image_filename)
                            if os.path.exists(old_path):
                                try:
                                    os.remove(old_path)
                                except Exception as ex:
                                    app.logger.error(f"Error deleting old image file: {ex}")
                                    flash('Error deleting old image file.')
                        edit_item.image_filename = filename
                    except Exception as ex:
                        app.logger.error(f"Error saving image file: {ex}")
                        flash('Error saving image file.')
                db.session.commit()
                flash('Food item updated!')
                return redirect(url_for('food_items'))
            elif action == 'select':
                selected_ids = request.form.getlist('selected_food_ids')
                selected_items = FoodItem.query.filter(FoodItem.id.in_(selected_ids)).all()
                user.food_items = selected_items
                db.session.commit()
                flash('Preferred food items saved!')
                return redirect(url_for('food_items'))
            elif 'delete_id' in request.form:
                food_id = int(request.form['delete_id'])
                item = FoodItem.query.get(food_id)
                if item:
                    if item.image_filename:
                        file_path = os.path.join(image_dir, item.image_filename)
                        if os.path.exists(file_path):
                            try:
                                os.remove(file_path)
                            except Exception as ex:
                                app.logger.error(f"Error deleting image file: {ex}")
                                flash('Error deleting image file.')
                    db.session.delete(item)
                    db.session.commit()
                    flash('Food item deleted!')
                else:
                    flash('Food item not found.')
                return redirect(url_for('food_items'))
        selected_ids = [item.id for item in getattr(user, 'food_items', [])]
        return render_template('food_items.html', food_items=all_items, selected_ids=selected_ids, edit_item=edit_item)
    except Exception as e:
        app.logger.error(f"Error in food_items: {e}")
        flash('An error occurred. Please try again.')
        return redirect(url_for('dashboard'))

@app.route('/export_food_items', methods=['POST'])
def export_food_items():
    all_items = FoodItem.query.order_by(FoodItem.name).all()
    def generate():
        data = [['Name', 'Calories', 'Rating']]
        for item in all_items:
            data.append([item.name, item.calories, item.rating])
        output = []
        writer = csv.writer(output)
        for row in data:
            writer.writerow(row)
        return '\n'.join(output)
    # Use csv.writer with StringIO for compatibility
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['Name', 'Calories', 'Rating'])
    for item in all_items:
        cw.writerow([item.name, item.calories, item.rating])
    output = si.getvalue()
    return Response(
        output,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment;filename=food_items.csv'}
    )

# Add relationship to User for food_items
User.food_items = db.relationship('FoodItem', secondary=user_food, backref='users')

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    if request.method == 'POST':
        new_pw = request.form.get('new_password')
        if new_pw:
            user.password = generate_password_hash(new_pw)
            db.session.commit()
            flash('Password updated!')
    return render_template('profile.html', user=user)

@app.route('/food/<int:food_id>', methods=['GET', 'POST'])
def food_detail(food_id):
    food = FoodItem.query.get_or_404(food_id)
    if request.method == 'POST':
        if request.form.get('action') == 'edit':
            # Edit food name, calories, and image
            new_name = request.form.get('name', '').strip()
            if new_name and (new_name == food.name or not FoodItem.query.filter_by(name=new_name).first()):
                food.name = new_name
            food.calories = int(request.form['calories'])
            food.category = request.form.get('category', '').strip()
            food.rating = float(request.form.get('rating', food.rating))
            file = request.files.get('food_image')
            if file and file.filename:
                filename = secure_filename(file.filename)
                file.save(os.path.join('static/food_images', filename))
                food.image_filename = filename
            db.session.commit()
            flash('Food attributes updated!')
        if 'comment' in request.form and 'user_id' in session:
            rating = request.form.get('comment_rating')
            comment = FoodComment(food_id=food.id, user_id=session['user_id'], content=request.form['comment'], rating=float(rating) if rating else None)
            db.session.add(comment)
            # Update average rating for food item
            all_ratings = [c.rating for c in food.comments if c.rating is not None]
            if all_ratings:
                food.rating = sum(all_ratings) / len(all_ratings)
            db.session.commit()
            flash('Comment posted!')
    comments = FoodComment.query.filter_by(food_id=food.id).order_by(FoodComment.created_at.desc()).all()
    return render_template('food_detail.html', food=food, comments=comments)

@app.template_filter('datetime')
def _jinja2_filter_datetime(value, format='%Y-%m-%d'):
    if isinstance(value, str):
        return datetime.strptime(value, format)
    return value

# Add default admin user if not exists
def create_default_admin():
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        admin = User(username='admin', password=generate_password_hash('admin'), is_admin=True)
        db.session.add(admin)
        db.session.commit()

@app.route('/dashboard_data')
def dashboard_data():
    # Get food items and aggregate category and rating data
    items = FoodItem.query.all()
    # Category aggregation
    category_counts = {}
    for item in items:
        cat = item.category or 'Uncategorized'
        category_counts[cat] = category_counts.get(cat, 0) + 1
    categories = {
        'labels': list(category_counts.keys()),
        'counts': list(category_counts.values())
    }
    # Ratings aggregation
    ratings = {
        'labels': [item.name for item in items],
        'values': [item.rating or 0 for item in items]
    }
    return app.response_class(
        response=json.dumps({'categories': categories, 'ratings': ratings}),
        mimetype='application/json'
    )

@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('500.html'), 500

if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # Always ensure tables exist
        create_default_admin()  # Ensure default admin exists
    app.run(debug=True)

































































































































