import os
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from functools import wraps
from werkzeug.utils import secure_filename
from datetime import datetime

# Import database and models
from config import Config, allowed_file
from models import db, User, Crop, Order, ChatMessage

app = Flask(__name__)
app.config.from_object(Config)

# Ensure upload folders exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'crops'), exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'diseases'), exist_ok=True)

# Initialize Database
db.init_app(app)

# Create database tables and auto-seed if empty
with app.app_context():
    db.create_all()
    # Check if empty, seed if necessary
    if User.query.first() is None:
        from seed import seed_database
        try:
            seed_database()
        except Exception as e:
            print(f"Error seeding database: {e}")

# ==========================================
# AUTHENTICATION DECORATORS
# ==========================================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def role_required(roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_role' not in session or session['user_role'] not in roles:
                flash('Access Denied. Insufficient permissions.', 'danger')
                # Redirect based on user's active role if any
                role = session.get('user_role')
                if role == 'farmer':
                    return redirect(url_for('farmer_dashboard'))
                elif role == 'buyer':
                    return redirect(url_for('buyer_dashboard'))
                elif role == 'admin':
                    return redirect(url_for('admin_dashboard'))
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# ==========================================
# AUTHENTICATION ROUTES
# ==========================================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        role = session.get('user_role')
        if role == 'farmer': return redirect(url_for('farmer_dashboard'))
        elif role == 'buyer': return redirect(url_for('buyer_dashboard'))
        elif role == 'admin': return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        username_or_email = request.form.get('username')
        password = request.form.get('password')
        role = request.form.get('role')  # Optional role confirmation if wanted
        
        # Query user by username or email
        user = User.query.filter(
            (User.username == username_or_email) | (User.email == username_or_email)
        ).first()
        
        if user and user.check_password(password):
            # Verify role if specific role login requested
            if role and user.role != role:
                flash(f'Account exists, but it is not registered as a {role.capitalize()}.', 'danger')
                return render_template('login.html')
                
            session['user_id'] = user.id
            session['user_name'] = user.username
            session['user_role'] = user.role
            session['cart'] = []  # Initialize empty shopping cart for buyers
            
            flash(f'Welcome back, {user.username}!', 'success')
            
            if user.role == 'farmer':
                return redirect(url_for('farmer_dashboard'))
            elif user.role == 'buyer':
                return redirect(url_for('buyer_dashboard'))
            elif user.role == 'admin':
                return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid username/email or password.', 'danger')
            
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        role = request.form.get('role')
        phone = request.form.get('phone')
        address = request.form.get('address')
        city = request.form.get('city')
        state = request.form.get('state')
        
        # Validation checks
        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('register.html')
            
        existing_user = User.query.filter((User.username == username) | (User.email == email)).first()
        if existing_user:
            flash('Username or Email already registered.', 'danger')
            return render_template('register.html')
            
        # Create and Save User
        user = User(
            username=username,
            email=email,
            role=role,
            phone=phone,
            address=address,
            city=city,
            state=state
        )
        user.set_password(password)
        
        db.session.add(user)
        db.session.commit()
        
        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))
        
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('index'))

# ==========================================
# PUBLIC ROUTES
# ==========================================
@app.route('/')
def index():
    # Fetch 4 featured crops for the marketplace sneak peek
    featured_crops = Crop.query.filter_by(is_approved=True).limit(4).all()
    return render_template('index.html', featured_crops=featured_crops)

# ==========================================
# FARMER DASHBOARD & CROP MANAGEMENT
# ==========================================
@app.route('/farmer/dashboard')
@login_required
@role_required(['farmer'])
def farmer_dashboard():
    farmer_id = session['user_id']
    
    # Calculate statistics
    crops = Crop.query.filter_by(farmer_id=farmer_id).all()
    total_crops = len(crops)
    
    orders = Order.query.filter_by(farmer_id=farmer_id).all()
    total_orders = len(orders)
    
    pending_orders = sum(1 for o in orders if o.status == 'Pending')
    shipped_orders = sum(1 for o in orders if o.status == 'Shipped')
    delivered_orders = sum(1 for o in orders if o.status == 'Delivered')
    
    # Total earnings from paid/delivered orders
    total_earnings = sum(o.total_price for o in orders if o.payment_status == 'Paid' or o.status == 'Delivered')
    
    recent_orders = Order.query.filter_by(farmer_id=farmer_id).order_by(Order.created_at.desc()).limit(5).all()
    
    return render_template(
        'farmer_dashboard.html',
        total_crops=total_crops,
        total_orders=total_orders,
        pending_orders=pending_orders,
        shipped_orders=shipped_orders,
        delivered_orders=delivered_orders,
        total_earnings=total_earnings,
        recent_orders=recent_orders
    )

@app.route('/farmer/crops', methods=['GET'])
@login_required
@role_required(['farmer'])
def farmer_crops():
    farmer_id = session['user_id']
    crops = Crop.query.filter_by(farmer_id=farmer_id).all()
    return render_template('farmer_crops.html', crops=crops)

@app.route('/farmer/crop/add', methods=['POST'])
@login_required
@role_required(['farmer'])
def add_crop():
    farmer_id = session['user_id']
    name = request.form.get('name')
    category = request.form.get('category')
    price = float(request.form.get('price'))
    quantity = float(request.form.get('quantity'))
    min_order_qty = float(request.form.get('min_order_qty', 1.0))
    description = request.form.get('description')
    
    # Farmer details for location defaults
    farmer = User.query.get(farmer_id)
    location = request.form.get('location') or farmer.city or 'Unknown'
    state = request.form.get('state') or farmer.state or 'Unknown'

    # Handle Crop Image Upload
    image_filename = 'default_crop.png'
    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename != '' and allowed_file(file.filename):
            sec_filename = secure_filename(file.filename)
            unique_filename = f"crop_{farmer_id}_{int(datetime.utcnow().timestamp())}_{sec_filename}"
            upload_path = os.path.join(app.config['UPLOAD_FOLDER'], 'crops', unique_filename)
            file.save(upload_path)
            image_filename = f"uploads/crops/{unique_filename}"

    new_crop = Crop(
        farmer_id=farmer_id,
        name=name,
        category=category,
        price=price,
        quantity=quantity,
        min_order_qty=min_order_qty,
        description=description,
        image_url=image_filename,
        location=location,
        state=state,
        is_approved=True # Auto approved for ease of use
    )
    
    db.session.add(new_crop)
    db.session.commit()
    
    flash('Crop listed successfully!', 'success')
    return redirect(url_for('farmer_crops'))

@app.route('/farmer/crop/edit/<int:crop_id>', methods=['POST'])
@login_required
@role_required(['farmer'])
def edit_crop(crop_id):
    crop = Crop.query.get_or_404(crop_id)
    
    # Security check: Ensure crop belongs to this farmer
    if crop.farmer_id != session['user_id']:
        flash('Unauthorized action.', 'danger')
        return redirect(url_for('farmer_crops'))
        
    crop.name = request.form.get('name')
    crop.category = request.form.get('category')
    crop.price = float(request.form.get('price'))
    crop.quantity = float(request.form.get('quantity'))
    crop.min_order_qty = float(request.form.get('min_order_qty'))
    crop.description = request.form.get('description')
    crop.location = request.form.get('location')
    crop.state = request.form.get('state')

    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename != '' and allowed_file(file.filename):
            sec_filename = secure_filename(file.filename)
            unique_filename = f"crop_{crop.farmer_id}_{int(datetime.utcnow().timestamp())}_{sec_filename}"
            upload_path = os.path.join(app.config['UPLOAD_FOLDER'], 'crops', unique_filename)
            file.save(upload_path)
            crop.image_url = f"uploads/crops/{unique_filename}"

    db.session.commit()
    flash('Crop updated successfully.', 'success')
    return redirect(url_for('farmer_crops'))

@app.route('/farmer/crop/delete/<int:crop_id>', methods=['POST'])
@login_required
@role_required(['farmer'])
def delete_crop(crop_id):
    crop = Crop.query.get_or_404(crop_id)
    if crop.farmer_id != session['user_id']:
        flash('Unauthorized action.', 'danger')
        return redirect(url_for('farmer_crops'))
        
    db.session.delete(crop)
    db.session.commit()
    flash('Crop removed successfully.', 'success')
    return redirect(url_for('farmer_crops'))

@app.route('/farmer/orders')
@login_required
@role_required(['farmer'])
def farmer_orders():
    farmer_id = session['user_id']
    orders = Order.query.filter_by(farmer_id=farmer_id).order_by(Order.created_at.desc()).all()
    return render_template('farmer_orders.html', orders=orders)

@app.route('/farmer/order/update/<int:order_id>', methods=['POST'])
@login_required
@role_required(['farmer'])
def update_order_status(order_id):
    order = Order.query.get_or_404(order_id)
    if order.farmer_id != session['user_id']:
        flash('Unauthorized action.', 'danger')
        return redirect(url_for('farmer_orders'))
        
    status = request.form.get('status')
    payment_status = request.form.get('payment_status')
    
    if status:
        order.status = status
    if payment_status:
        order.payment_status = payment_status
        
    db.session.commit()
    flash(f"Order #{order_id} updated successfully.", "success")
    return redirect(url_for('farmer_orders'))

# ==========================================
# BUYER DASHBOARD, MARKETPLACE & ORDERS
# ==========================================
@app.route('/marketplace')
def marketplace():
    # Filters
    search_query = request.args.get('search', '')
    category = request.args.get('category', '')
    location = request.args.get('location', '')
    
    query = Crop.query.filter_by(is_approved=True)
    
    if search_query:
        query = query.filter(Crop.name.ilike(f"%{search_query}%") | Crop.description.ilike(f"%{search_query}%"))
    if category:
        query = query.filter_by(category=category)
    if location:
        query = query.filter(Crop.location.ilike(f"%{location}%") | Crop.state.ilike(f"%{location}%"))
        
    crops = query.all()
    
    # Extract unique categories and locations for filter select lists
    categories = db.session.query(Crop.category).distinct().all()
    categories = [c[0] for c in categories]
    
    locations = db.session.query(Crop.location).distinct().all()
    locations = [l[0] for l in locations]

    return render_template(
        'marketplace.html',
        crops=crops,
        categories=categories,
        locations=locations,
        selected_category=category,
        selected_location=location,
        search_query=search_query
    )

@app.route('/buyer/dashboard')
@login_required
@role_required(['buyer'])
def buyer_dashboard():
    buyer_id = session['user_id']
    orders = Order.query.filter_by(buyer_id=buyer_id).order_by(Order.created_at.desc()).all()
    
    total_spent = sum(o.total_price for o in orders if o.payment_status == 'Paid')
    active_orders = sum(1 for o in orders if o.status in ['Pending', 'Shipped'])
    
    # Recommended crops based on user city/state
    buyer = User.query.get(buyer_id)
    local_crops = Crop.query.filter(
        (Crop.is_approved == True) & 
        ((Crop.location.ilike(f"%{buyer.city}%")) | (Crop.state.ilike(f"%{buyer.state}%")))
    ).limit(3).all()
    
    if not local_crops:
        local_crops = Crop.query.filter_by(is_approved=True).limit(3).all()

    return render_template(
        'buyer_dashboard.html',
        orders=orders,
        total_spent=total_spent,
        active_orders=active_orders,
        local_crops=local_crops
    )

@app.route('/buyer/cart/add/<int:crop_id>', methods=['POST'])
@login_required
@role_required(['buyer'])
def cart_add(crop_id):
    quantity = float(request.form.get('quantity', 1.0))
    crop = Crop.query.get_or_404(crop_id)
    
    if quantity < crop.min_order_qty:
        flash(f"Minimum order quantity for this crop is {crop.min_order_qty} kg.", "warning")
        return redirect(url_for('marketplace'))
        
    if quantity > crop.quantity:
        flash(f"Available stock is only {crop.quantity} kg.", "danger")
        return redirect(url_for('marketplace'))
        
    # Check if already in cart
    cart = session.get('cart', [])
    updated = False
    for item in cart:
        if item['crop_id'] == crop_id:
            item['quantity'] = quantity
            updated = True
            break
            
    if not updated:
        cart.append({
            'crop_id': crop_id,
            'name': crop.name,
            'price': crop.price,
            'image_url': crop.image_url,
            'quantity': quantity,
            'farmer_id': crop.farmer_id,
            'farmer_name': crop.farmer.username
        })
        
    session['cart'] = cart
    session.modified = True
    flash(f"Added {crop.name} ({quantity} kg) to cart.", "success")
    return redirect(url_for('cart_view'))

@app.route('/buyer/cart')
@login_required
@role_required(['buyer'])
def cart_view():
    cart = session.get('cart', [])
    total = sum(item['price'] * item['quantity'] for item in cart)
    return render_template('buyer_orders.html', cart=cart, total=total)

@app.route('/buyer/cart/remove/<int:crop_id>', methods=['POST'])
@login_required
@role_required(['buyer'])
def cart_remove(crop_id):
    cart = session.get('cart', [])
    session['cart'] = [item for item in cart if item['crop_id'] != crop_id]
    session.modified = True
    flash("Item removed from cart.", "info")
    return redirect(url_for('cart_view'))

@app.route('/buyer/checkout', methods=['POST'])
@login_required
@role_required(['buyer'])
def checkout():
    buyer_id = session['user_id']
    cart = session.get('cart', [])
    shipping_address = request.form.get('shipping_address')
    contact_phone = request.form.get('contact_phone')
    
    if not cart:
        flash("Your cart is empty.", "warning")
        return redirect(url_for('marketplace'))
        
    if not shipping_address or not contact_phone:
        flash("Please provide shipping address and contact phone.", "danger")
        return redirect(url_for('cart_view'))
        
    # Place individual orders for each farmer's crop
    for item in cart:
        crop = Crop.query.get(item['crop_id'])
        if not crop:
            continue
            
        qty = item['quantity']
        if qty > crop.quantity:
            flash(f"Sorry, stock for {crop.name} is no longer sufficient.", "danger")
            return redirect(url_for('cart_view'))
            
        total_price = crop.price * qty
        
        # Deduct quantity from crop inventory
        crop.quantity -= qty
        
        order = Order(
            buyer_id=buyer_id,
            farmer_id=crop.farmer_id,
            crop_id=crop.id,
            quantity=qty,
            total_price=total_price,
            status='Pending',
            payment_status='Paid',  # Mock successful online payment
            shipping_address=shipping_address,
            contact_phone=contact_phone
        )
        db.session.add(order)
        
    db.session.commit()
    
    # Clear cart
    session['cart'] = []
    session.modified = True
    
    flash("Orders placed successfully! Thank you.", "success")
    return redirect(url_for('buyer_dashboard'))

# ==========================================
# ADMIN DASHBOARD
# ==========================================
@app.route('/admin/dashboard')
@login_required
@role_required(['admin'])
def admin_dashboard():
    users = User.query.all()
    farmers = User.query.filter_by(role='farmer').all()
    crops = Crop.query.all()
    orders = Order.query.order_by(Order.created_at.desc()).all()
    
    total_users = len(users)
    total_crops = len(crops)
    total_orders = len(orders)
    total_sales = sum(o.total_price for o in orders if o.payment_status == 'Paid')
    
    return render_template(
        'admin_dashboard.html',
        users=users,
        farmers=farmers,
        crops=crops,
        orders=orders,
        total_users=total_users,
        total_crops=total_crops,
        total_orders=total_orders,
        total_sales=total_sales
    )

@app.route('/admin/user/add', methods=['POST'])
@login_required
@role_required(['admin'])
def admin_add_user():
    username = request.form.get('username')
    email = request.form.get('email')
    password = request.form.get('password')
    role = request.form.get('role')
    phone = request.form.get('phone')
    address = request.form.get('address')
    city = request.form.get('city')
    state = request.form.get('state')

    if not username or not email or not password or not role:
        flash('Please provide username, email, password, and role.', 'danger')
        return redirect(url_for('admin_dashboard'))

    existing_user = User.query.filter(
        (User.username == username) | (User.email == email)
    ).first()
    if existing_user:
        flash('Username or email already exists.', 'danger')
        return redirect(url_for('admin_dashboard'))

    user = User(
        username=username,
        email=email,
        role=role,
        phone=phone,
        address=address,
        city=city,
        state=state
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    flash(f'User {username} added successfully.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/user/toggle/<int:user_id>', methods=['POST'])
@login_required
@role_required(['admin'])
def toggle_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == session['user_id']:
        flash("You cannot delete your own admin account.", "danger")
        return redirect(url_for('admin_dashboard'))

    if user.crops or user.buyer_orders or user.farmer_orders:
        flash('Cannot remove a user who has active crops or orders.', 'warning')
        return redirect(url_for('admin_dashboard'))
        
    db.session.delete(user)
    db.session.commit()
    flash(f"User {user.username} deleted successfully.", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/crop/toggle/<int:crop_id>', methods=['POST'])
@login_required
@role_required(['admin'])
def toggle_crop(crop_id):
    crop = Crop.query.get_or_404(crop_id)
    crop.is_approved = not crop.is_approved
    db.session.commit()
    status = "Approved" if crop.is_approved else "Disapproved"
    flash(f"Crop {crop.name} has been {status}.", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/crop/add', methods=['POST'])
@login_required
@role_required(['admin'])
def admin_add_crop():
    name = request.form.get('name')
    category = request.form.get('category')
    price = float(request.form.get('price', 0) or 0)
    quantity = float(request.form.get('quantity', 0) or 0)
    min_order_qty = float(request.form.get('min_order_qty', 1) or 1)
    description = request.form.get('description')
    location = request.form.get('location') or 'Unknown'
    state = request.form.get('state') or 'Unknown'
    farmer_id = request.form.get('farmer_id')

    if farmer_id:
        farmer = User.query.get(int(farmer_id))
        if not farmer:
            farmer = User.query.get(session['user_id'])
    else:
        farmer = User.query.get(session['user_id'])

    image_filename = 'default_crop.png'
    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename != '' and allowed_file(file.filename):
            sec_filename = secure_filename(file.filename)
            unique_filename = f"crop_admin_{int(datetime.utcnow().timestamp())}_{sec_filename}"
            upload_path = os.path.join(app.config['UPLOAD_FOLDER'], 'crops', unique_filename)
            file.save(upload_path)
            image_filename = f"uploads/crops/{unique_filename}"

    new_crop = Crop(
        farmer_id=farmer.id,
        name=name,
        category=category,
        price=price,
        quantity=quantity,
        min_order_qty=min_order_qty,
        description=description,
        image_url=image_filename,
        location=location,
        state=state,
        is_approved=True
    )

    db.session.add(new_crop)
    db.session.commit()

    flash('New crop added successfully.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/crop/delete/<int:crop_id>', methods=['POST'])
@login_required
@role_required(['admin'])
def admin_delete_crop(crop_id):
    crop = Crop.query.get_or_404(crop_id)
    if crop.orders:
        flash('Cannot delete a crop that is linked to orders.', 'warning')
        return redirect(url_for('admin_dashboard'))

    db.session.delete(crop)
    db.session.commit()

    flash(f'Crop {crop.name} removed successfully.', 'success')
    return redirect(url_for('admin_dashboard'))

# ==========================================
# HIGH-FIDELITY AI HUB ENDPOINTS
# ==========================================
@app.route('/ai-tools')
@login_required
def ai_tools():
    return render_template('ai_tools.html')

@app.route('/api/ai/recommend', methods=['POST'])
@login_required
def api_recommend_crops():
    data = request.json or {}
    try:
        n = float(data.get('n', 50))
        p = float(data.get('p', 50))
        k = float(data.get('k', 50))
        ph = float(data.get('ph', 6.5))
        temp = float(data.get('temp', 25.0))
        rainfall = float(data.get('rainfall', 800.0))
    except ValueError:
        return jsonify({'error': 'Invalid parameter types'}), 400

    # Dynamic soil suitability database
    soil_db = [
        {
            'crop': 'Premium Basmati Rice',
            'optimal': {'n': 80, 'p': 45, 'k': 40, 'ph': 6.0, 'temp': 28, 'rainfall': 1200},
            'sowing': 'June - July (Kharif)',
            'advice': 'Requires stagnant water. Best suited for clayey soil with good water retention.',
            'yield': '3.5 - 4.5 tons/hectare'
        },
        {
            'crop': 'Sharbati Wheat',
            'optimal': {'n': 90, 'p': 50, 'k': 40, 'ph': 6.8, 'temp': 18, 'rainfall': 400},
            'sowing': 'October - November (Rabi)',
            'advice': 'Prefers loamy soils. Requires cooler temperatures during growth and 3-4 irrigation cycles.',
            'yield': '4.0 - 5.0 tons/hectare'
        },
        {
            'crop': 'Nashik Red Onions',
            'optimal': {'n': 60, 'p': 40, 'k': 60, 'ph': 6.5, 'temp': 22, 'rainfall': 600},
            'sowing': 'October or June',
            'advice': 'Demands sandy-loam soils with high organic content. Keep drainage systems active.',
            'yield': '15 - 20 tons/hectare'
        },
        {
            'crop': 'Organic Cotton',
            'optimal': {'n': 70, 'p': 45, 'k': 50, 'ph': 7.5, 'temp': 30, 'rainfall': 800},
            'sowing': 'May - June',
            'advice': 'Grows extremely well in deep black soils (regur) with excellent aeration.',
            'yield': '2.0 - 2.5 tons/hectare'
        },
        {
            'crop': 'High-yield Potatoes',
            'optimal': {'n': 100, 'p': 60, 'k': 80, 'ph': 5.5, 'temp': 20, 'rainfall': 500},
            'sowing': 'October - November',
            'advice': 'Prefers slightly acidic, highly aerated sandy loam. Avoid waterlogged fields to prevent rot.',
            'yield': '25 - 30 tons/hectare'
        },
        {
            'crop': 'Golden Mustard',
            'optimal': {'n': 50, 'p': 30, 'k': 30, 'ph': 7.0, 'temp': 16, 'rainfall': 300},
            'sowing': 'September - October',
            'advice': 'Extremely drought resistant. Performs well on sandy soils. Provide sulfur fertilizers.',
            'yield': '1.5 - 2.0 tons/hectare'
        }
    ]

    # Calculate distance score
    scored_crops = []
    for c in soil_db:
        # Distance calculation
        opt = c['optimal']
        dist = (
            ((n - opt['n'])/120)**2 + 
            ((p - opt['p'])/80)**2 + 
            ((k - opt['k'])/100)**2 + 
            ((ph - opt['ph'])/4)**2 + 
            ((temp - opt['temp'])/25)**2 + 
            ((rainfall - opt['rainfall'])/1500)**2
        ) ** 0.5
        
        # Convert distance to matching percentage (confidence)
        confidence = max(0, min(100, round((1.0 - (dist / 1.5)) * 100, 1)))
        
        scored_crops.append({
            'crop_name': c['crop'],
            'confidence': confidence,
            'sowing_time': c['sowing'],
            'advice': c['advice'],
            'expected_yield': c['yield']
        })

    # Sort by confidence
    scored_crops.sort(key=lambda x: x['confidence'], reverse=True)
    return jsonify(scored_crops[:3])

@app.route('/api/ai/price-prediction', methods=['GET'])
@login_required
def api_price_prediction():
    crop_name = request.args.get('crop', 'Premium Basmati Rice')
    
    # Base prices
    bases = {
        'Premium Basmati Rice': 65,
        'Sharbati Organic Wheat': 32,
        'Nashik Red Onions': 22,
        'Alphonso Mangoes': 150,
        'Yellow Split Pigeon Peas (Toor Dal)': 110
    }
    
    base_price = bases.get(crop_name, 45)
    
    # Dynamic price generation (seasonal variations for next 6 months)
    months = ['Jun 2026', 'Jul 2026', 'Aug 2026', 'Sep 2026', 'Oct 2026', 'Nov 2026']
    
    # Define a custom trend factor for each crop
    trends = {
        'Premium Basmati Rice': [1.0, 1.03, 1.05, 1.08, 1.04, 1.02],
        'Sharbati Organic Wheat': [1.0, 1.02, 1.04, 1.07, 1.11, 1.15],
        'Nashik Red Onions': [1.0, 1.12, 1.25, 1.35, 1.18, 0.95],
        'Alphonso Mangoes': [1.0, 1.20, 1.45, 1.80, 2.00, 2.10], # Skyrockets off-season
        'Yellow Split Pigeon Peas (Toor Dal)': [1.0, 1.01, 1.03, 1.04, 1.06, 1.08]
    }
    
    multipliers = trends.get(crop_name, [1.0, 1.02, 1.03, 1.05, 1.04, 1.01])
    
    predicted_prices = [round(base_price * m, 2) for m in multipliers]
    
    return jsonify({
        'crop': crop_name,
        'months': months,
        'prices': predicted_prices
    })

@app.route('/api/ai/disease-detect', methods=['POST'])
@login_required
def api_disease_detect():
    plant_type = request.form.get('plant_type', 'Tomato')
    
    # Pre-coded high-fidelity diagnoses
    diagnoses = {
        'Tomato': {
            'disease': 'Tomato Early Blight (Alternaria solani)',
            'confidence': '94.2%',
            'description': 'Early blight is caused by the fungus Alternaria solani. It manifests as dark, concentric spots (target-like) on older leaves. Can lead to major defoliation and yield loss.',
            'symptoms': 'Concentric brown circles on lower leaves, yellow ring surrounding dark brown spots, dark sunken lesions at stem joints.',
            'treatment_organic': 'Apply organic Neem Oil sprays, copper-based organic fungicides, prune lower infected branches, and mulch soil to prevent fungal spores from splashing up.',
            'treatment_chemical': 'Apply Chlorothalonil or Mancozeb sprays at first sign of infection.'
        },
        'Potato': {
            'disease': 'Potato Late Blight (Phytophthora infestans)',
            'confidence': '91.7%',
            'description': 'Late blight is a destructive disease caused by an oomycete pathogen. Historically responsible for the Irish Potato Famine, it thrives in wet and cool conditions.',
            'symptoms': 'Water-soaked grey-green spots on leaves, white cottony mold growing on leaf undersides in high humidity, rotting tubers with brown skin lesions.',
            'treatment_organic': 'Choose disease-resistant potato seeds, practice strict crop rotations, spray compost tea, and harvest on dry sunny days.',
            'treatment_chemical': 'Spray Metalaxyl or copper oxychloride at 10-day intervals during highly humid periods.'
        },
        'Rice': {
            'disease': 'Rice Leaf Blast (Magnaporthe oryzae)',
            'confidence': '89.5%',
            'description': 'One of the most devastating fungal diseases of cultivated rice globally. Thrives in dry, warm climates with high nitrogen fertilizers.',
            'symptoms': 'Spindle-shaped (diamond) lesions on leaves with white/grey centers and reddish-brown borders, grey felt-like mold on leaf undersides, choking of neck joints.',
            'treatment_organic': 'Avoid excessive nitrogen fertilization. Apply organic Trichoderma liquid bio-fungicides. Use silicon fertilizers to strengthen cell walls.',
            'treatment_chemical': 'Foliar spray of Tricyclazole or Azoxystrobin immediately upon detecting spindle spots.'
        },
        'Apple': {
            'disease': 'Apple Scab (Venturia inaequalis)',
            'confidence': '93.1%',
            'description': 'Apple scab is a severe disease affecting leaves and fruits, caused by Venturia inaequalis. Renders fruits unsellable due to corky brown scabs.',
            'symptoms': 'Olive-green velvet spots on leaves turning dark brown, scabby brown lesions on fruits, premature leaf drop.',
            'treatment_organic': 'Rake and burn all fallen leaves in autumn to disrupt overwintering spores. Spray organic sulfur or copper sulfate pre-bloom.',
            'treatment_chemical': 'Apply Captan or Myclobutanil fungicides during bud-break and bloom.'
        }
    }
    
    # Extract diagnosis
    diag = diagnoses.get(plant_type, diagnoses['Tomato'])
    
    # Save simulated image if provided
    image_filename = 'mock_disease.png'
    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename != '' and allowed_file(file.filename):
            sec_filename = secure_filename(file.filename)
            unique_filename = f"disease_{session['user_id']}_{int(datetime.utcnow().timestamp())}_{sec_filename}"
            upload_path = os.path.join(app.config['UPLOAD_FOLDER'], 'diseases', unique_filename)
            file.save(upload_path)
            image_filename = f"uploads/diseases/{unique_filename}"
            
    diag_res = diag.copy()
    diag_res['uploaded_image'] = image_filename
    
    return jsonify(diag_res)

@app.route('/api/ai/chatbot', methods=['POST'])
def api_chatbot():
    data = request.json or {}
    message = data.get('message', '').lower().strip()
    
    # Custom intelligent keyword parser for AgriBot
    response = ""
    
    if any(k in message for k in ['hello', 'hi', 'hey', 'greetings']):
        response = "Hello! I am **AgriBot**, your AI farming assistant. How can I help you today? You can ask me about soil suggestions, crop pricing trends, plant diseases, or how to buy/sell crops on AgriConnect!"
    
    elif any(k in message for k in ['recommend', 'soil', 'grow', 'plant', 'sowing']):
        response = "I can definitely help recommend crops! Simply navigate to our **AI Tools** page from the top navbar. Enter your soil's Nitrogen (N), Phosphorus (P), Potassium (K), pH, and climate conditions, and our soil matching algorithm will give you the top 3 high-yield crops!"
        
    elif any(k in message for k in ['price', 'forecast', 'predict', 'market', 'cost']):
        response = "Market pricing is key! Under **AI Tools -> Price Prediction**, we use seasonal forecasting models to project crop wholesale values 6 months out. For instance, Nashik Red Onions generally hit peak prices in September/October before the winter harvest."
        
    elif any(k in message for k in ['disease', 'blight', 'spot', 'leaf', 'sick', 'insect', 'pest', 'fungus']):
        response = "Oh no, crop diseases must be treated quickly! On the **AI Tools** hub, click **Disease Detection** to upload a photo of your infected leaf. I will immediately analyze the visual cues, identify the disease (like Late Blight or Apple Scab), and provide organic and chemical treatments."
        
    elif any(k in message for k in ['sell', 'upload', 'list', 'farmer', 'earn']):
        response = "To sell crops on AgriConnect:\n1. Register or Log in as a **Farmer**.\n2. Go to your **Farmer Dashboard** and select **My Crops**.\n3. Click **Add Crop**, fill in the price, available quantity, description, and upload a crop photo.\nOnce saved, it is immediately listed in the public **Marketplace**!"
        
    elif any(k in message for k in ['buy', 'cart', 'order', 'purchase', 'buyer']):
        response = "Buying crops is simple:\n1. Log in as a **Buyer**.\n2. Click on **Browse Marketplace** at the top.\n3. Search or filter crops by category (Grains, Fruits, etc.) and location.\n4. Enter the desired quantity and click **Add to Cart**.\n5. View your cart and press **Checkout** to finalize your order!"
        
    elif any(k in message for k in ['admin', 'approve', 'moderate']):
        response = "Administrators have exclusive control to manage users, monitor all transactions, and approve or restrict crops. If you are logged in as admin, the top navbar will display **Admin Panel**."
        
    elif any(k in message for k in ['organic', 'chemical', 'natural']):
        response = "AgriConnect highly encourages organic farming! Organic crops generally fetch 20-30% premium pricing in the marketplace. We support natural pesticides like Neem Oil and organic compost mixes."
        
    else:
        response = "That is a great question! For specific soil conditions, check out our **AI Crop Recommendation** tab. For leaf problems, try the **Disease Detection** uploader. If you are looking to purchase or sell, the **Marketplace** has real-time stock listings!"
        
    return jsonify({'response': response})

# ==========================================
# CHAT API ENDPOINTS
# ==========================================
@app.route('/api/chat/history/<int:other_id>')
@login_required
def get_chat_history(other_id):
    my_id = session['user_id']
    
    messages = ChatMessage.query.filter(
        ((ChatMessage.sender_id == my_id) & (ChatMessage.receiver_id == other_id)) |
        ((ChatMessage.sender_id == other_id) & (ChatMessage.receiver_id == my_id))
    ).order_by(ChatMessage.timestamp.asc()).all()
    
    return jsonify([m.to_dict() for m in messages])

@app.route('/api/chat/send', methods=['POST'])
@login_required
def send_chat_message():
    data = request.json or {}
    receiver_id = data.get('receiver_id')
    msg_text = data.get('message')
    
    if not receiver_id or not msg_text:
        return jsonify({'error': 'Missing recipient or message'}), 400
        
    new_msg = ChatMessage(
        sender_id=session['user_id'],
        receiver_id=receiver_id,
        message=msg_text
    )
    db.session.add(new_msg)
    db.session.commit()
    
    return jsonify(new_msg.to_dict())

if __name__ == '__main__':
    app.run(debug=True, port=5000)
