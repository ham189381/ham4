from flask import Flask, request, render_template, redirect, url_for, send_from_directory
from twilio.twiml.messaging_response import MessagingResponse
from werkzeug.utils import secure_filename
from flask import jsonify
import psycopg2
import os
import cloudinary
import cloudinary.uploader
import cloudinary.api
from io import BytesIO
import traceback

app = Flask(__name__)

# -------------------------
# Cloudinary Configuration
# -------------------------
cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
    secure=True
)

# -------------------------
# Local File Upload Configuration (fallback)
# -------------------------
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def upload_to_cloudinary(file, prefix=""):
    """
    Upload image to Cloudinary and return the URL.
    Falls back to local storage if Cloudinary fails.
    """
    if not file or not file.filename:
        return ""
    
    if not allowed_file(file.filename):
        raise ValueError("File type not allowed")
    
    try:
        # Read file content
        file_content = file.read()
        
        # Create a BytesIO object to re-upload
        file_stream = BytesIO(file_content)
        file_stream.seek(0)
        
        # Create a filename for Cloudinary
        filename = secure_filename(file.filename)
        if prefix:
            name, ext = os.path.splitext(filename)
            filename = f"{prefix}_{name}{ext}"
        
        # Upload to Cloudinary
        upload_result = cloudinary.uploader.upload(
            file_stream,
            public_id=filename.replace('.', '_'),  # Remove extension for public_id
            folder="driver_app",  # Organize images in a folder
            resource_type="image"
        )
        
        # Return the secure URL
        return upload_result['secure_url']
    
    except Exception as e:
        print(f"Cloudinary upload failed: {e}. Falling back to local storage.")
        # Fallback to local storage
        file.seek(0)  # Reset file pointer
        return save_image_local(file, prefix)

def save_image_local(file, prefix=""):
    """Save uploaded file locally and return its URL path."""
    if not file or not file.filename:
        return ""
    if not allowed_file(file.filename):
        raise ValueError("File type not allowed")
    
    filename = secure_filename(file.filename)
    if prefix:
        name, ext = os.path.splitext(filename)
        filename = f"{prefix}_{name}{ext}"
    
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)
    return f"/uploads/{filename}"

# For backward compatibility
def save_image(file, prefix=""):
    """Upload to Cloudinary by default"""
    return upload_to_cloudinary(file, prefix)

# -------------------------
# Database connection (local)
# -------------------------
def get_db_connection():
    """Return a PostgreSQL connection for local development or production."""
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        return psycopg2.connect(database_url)
    else:
        return psycopg2.connect(
            host="127.0.0.1",
            database="drivers_db",
            user="postgres",
            password="1234",
            port="5432"
        )

# -------------------------
# Create all tables (with location columns)
# -------------------------
def create_drivers_table():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS drivers (
            id SERIAL PRIMARY KEY,
            name TEXT,
            district TEXT,
            town TEXT,
            phone TEXT,
            truck_name TEXT,
            location TEXT,
            image1 TEXT,
            image2 TEXT,
            image3 TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    cursor.close()
    conn.close()

def create_deals_table():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS deals (
            id SERIAL PRIMARY KEY,
            suppliername TEXT,
            materialname TEXT,
            tippername TEXT,
            location TEXT,
            live_latitude DOUBLE PRECISION,
            live_longitude DOUBLE PRECISION,
            phone TEXT,
            imageone TEXT,
            imagetwo TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    cursor.close()
    conn.close()

def create_orders_table():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            district TEXT,
            town TEXT,
            truck_name TEXT,
            material_service TEXT,
            location TEXT,
            phone TEXT,
            image1 TEXT,
            image2 TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    cursor.close()
    conn.close()

def create_tracking_table():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS deal_tracking (
            id SERIAL PRIMARY KEY,
            deal_id INTEGER REFERENCES deals(id),
            latitude DOUBLE PRECISION,
            longitude DOUBLE PRECISION,
            accuracy DOUBLE PRECISION,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    cursor.close()
    conn.close()


# Create all tables when app starts
create_drivers_table()
create_deals_table()
create_orders_table()
create_tracking_table()

# Fix existing tables - add missing columns
def fix_existing_tables():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Check if location column exists in drivers table
        cursor.execute("""
            SELECT EXISTS (
                SELECT 1 
                FROM information_schema.columns 
                WHERE table_name='drivers' AND column_name='location'
            )
        """)
        if not cursor.fetchone()[0]:
            cursor.execute("ALTER TABLE drivers ADD COLUMN location TEXT")
            conn.commit()
            print("Added location column to drivers table")
    except Exception as e:
        print(f"Migration note: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

# Migrate deals table to add live location columns
def migrate_deals_table():
    """Add live location columns to deals table if they don't exist"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Check and add live_latitude column
        cursor.execute("""
            SELECT EXISTS (
                SELECT 1 
                FROM information_schema.columns 
                WHERE table_name='deals' AND column_name='live_latitude'
            )
        """)
        if not cursor.fetchone()[0]:
            cursor.execute("ALTER TABLE deals ADD COLUMN live_latitude DOUBLE PRECISION")
            conn.commit()
            print("Added live_latitude column to deals table")
        
        # Check and add live_longitude column
        cursor.execute("""
            SELECT EXISTS (
                SELECT 1 
                FROM information_schema.columns 
                WHERE table_name='deals' AND column_name='live_longitude'
            )
        """)
        if not cursor.fetchone()[0]:
            cursor.execute("ALTER TABLE deals ADD COLUMN live_longitude DOUBLE PRECISION")
            conn.commit()
            print("Added live_longitude column to deals table")
            
    except Exception as e:
        print(f"Migration note: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

fix_existing_tables()
migrate_deals_table()

# -------------------------
# Serve uploaded files (for local fallback)
# -------------------------
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

# -------------------------
# Routes
# -------------------------

@app.route("/")
def home():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM drivers")
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    drivers = [dict(zip(columns, row)) for row in rows]
    cursor.close()
    conn.close()
    return render_template("sofery.html", drivers=drivers)


# UPDATE LIVE LOCATION FOR DEALS

@app.route('/update_live_location/<int:deal_id>', methods=['POST'])
def update_live_location(deal_id):
    """Receive live location updates from the user's phone"""
    try:
        data = request.get_json()
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        accuracy = data.get('accuracy', 0)
        
        # Save to tracking table
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO deal_tracking (deal_id, latitude, longitude, accuracy)
            VALUES (%s, %s, %s, %s)
        """, (deal_id, latitude, longitude, accuracy))
        
        # Also update the main deals table with latest location
        cursor.execute("""
            UPDATE deals 
            SET live_latitude = %s, live_longitude = %s 
            WHERE id = %s
        """, (latitude, longitude, deal_id))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({"status": "success"}), 200
    except Exception as e:
        print(f"Error updating location: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/get_deal_location/<int:deal_id>')
def get_deal_location(deal_id):
    """Get the latest location for a specific deal"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT latitude, longitude, timestamp, accuracy 
        FROM deal_tracking 
        WHERE deal_id = %s 
        ORDER BY timestamp DESC 
        LIMIT 1
    """, (deal_id,))
    location = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if location:
        return jsonify({
            "latitude": location[0],
            "longitude": location[1],
            "timestamp": location[2],
            "accuracy": location[3]
        })
    return jsonify({"error": "No location found"}), 404

@app.route('/get_deal_tracking_history/<int:deal_id>')
def get_deal_tracking_history(deal_id):
    """Get full movement history for a deal"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT latitude, longitude, timestamp, accuracy 
        FROM deal_tracking 
        WHERE deal_id = %s 
        ORDER BY timestamp ASC
    """, (deal_id,))
    history = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return jsonify([{
        "latitude": h[0],
        "longitude": h[1],
        "timestamp": h[2],
        "accuracy": h[3]
    } for h in history])

# API endpoints for admin live tracking
@app.route("/api/deal_locations")
def get_all_deal_locations():
    """API endpoint to get all active deals with their latest locations"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT d.id, d.suppliername, d.materialname, d.tippername, d.phone,
               d.live_latitude, d.live_longitude,
               dt.latitude as last_latitude, 
               dt.longitude as last_longitude,
               dt.timestamp as last_update
        FROM deals d
        LEFT JOIN (
            SELECT DISTINCT ON (deal_id) deal_id, latitude, longitude, timestamp
            FROM deal_tracking
            ORDER BY deal_id, timestamp DESC
        ) dt ON d.id = dt.deal_id
        WHERE d.live_latitude IS NOT NULL OR dt.latitude IS NOT NULL
        ORDER BY d.created_at DESC
    """)
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    deals = [dict(zip(columns, row)) for row in rows]
    cursor.close()
    conn.close()
    return jsonify(deals)

@app.route("/api/deal_tracking/<int:deal_id>")
def get_deal_tracking_api(deal_id):
    """API endpoint to get tracking history for a specific deal"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT latitude, longitude, timestamp, accuracy 
        FROM deal_tracking 
        WHERE deal_id = %s 
        ORDER BY timestamp ASC
    """, (deal_id,))
    history = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return jsonify([{
        "latitude": h[0],
        "longitude": h[1],
        "timestamp": h[2],
        "accuracy": h[3]
    } for h in history])

@app.route("/track_deal/<int:deal_id>")
def track_deal(deal_id):
    """Dedicated tracking page for a specific deal"""
    return render_template("deal_tracking.html", deal_id=deal_id)

@app.route('/prospect')
def prospect():
    return render_template('prospect.html')

@app.route('/process', methods=['POST'])
def process():
    choice = request.form.get('option')
    if choice in ['supplire', 'driver', 'both']:
        return render_template("driverdetails.html")
    else:
        return '<h1>Result</h1><p>No option was selected.</p>'

@app.route("/drivers")
def view_drivers():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM drivers")
    drivers = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template("driverstable.html", drivers=drivers)

@app.route("/alldrivercards")
def alldrivercards():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM drivers")
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    drivers = [dict(zip(columns, row)) for row in rows]
    cursor.close()
    conn.close()
    return render_template("alldrivercards.html", drivers=drivers)

@app.route("/showdrivers")
def driverpage():
    return render_template("driver.html")

def get_drivers_by_town(town):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM drivers WHERE LOWER(town) LIKE LOWER(%s)",
        ('%' + town + '%',)
    )
    drivers = cursor.fetchall()
    cursor.close()
    conn.close()
    return drivers

@app.route("/drivers/<town>")
def show_drivers_by_town(town):
    drivers = get_drivers_by_town(town)
    return render_template("spacifictowndrivers.html", drivers=drivers, town=town)

# Static pages (unchanged)
@app.route('/kampaladistrict')
def kampaladistrict():
    return render_template('kampaladivisions.html')

@app.route('/wakisodistricttowns')
def wakisodistricttowns():
    return render_template('wakisodistricttowns.html')

@app.route('/mukonodistricttowns')
def mukonodistricttowns():
    return render_template('mukonodistricttowns.html')

@app.route('/nakawadivision')
def nakawadivision():
    return render_template('nakawadivisionparishes.html')

@app.route('/kawempedivision')
def kawempedivision():
    return render_template('kawempedivisionparishes.html')

@app.route('/kampalacentralsupplires')
def kampalacentralsupplires():
    return render_template('kampalacentralsupplires.html')

@app.route('/makindyedivision')
def makindyedivision():
    return render_template('makindyedivisionparishes.html')

@app.route('/rubagadivision')
def rubagadivision():
    return render_template('rubagadivisionparishes.html')

@app.route("/supplirenearyou")
def supplirenearyou():
    return render_template("supplirenearyou.html")

@app.route("/drivers_tables_by_town")
def drivers_tables_by_town():
    return render_template("drivers_by_town_table.html")

@app.route("/kampala_ntinda")
def kampala_ntinda():
    return render_template("kampala_ntinda_supplires.html")

# -------------------------
# Driver Registration (UPDATED for Cloudinary)
# -------------------------
@app.route("/driverdetails")
def driverdetails():
    return render_template("driverdetails.html")

@app.route("/driver", methods=["GET", "POST"])
def driver():
    if request.method == "POST":
        try:
            name = request.form["name"]
            district = request.form["district"]
            town = request.form["town"]
            phone = request.form["phone"]
            truck_name = request.form["truck_name"]
            location = request.form["location"]

            image1 = request.files.get("image1")
            image2 = request.files.get("image2")
            image3 = request.files.get("image3")

            # These will now upload to Cloudinary automatically
            url1 = save_image(image1, f"driver_{name}_1")
            url2 = save_image(image2, f"driver_{name}_2")
            url3 = save_image(image3, f"driver_{name}_3")

            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO drivers (name, district, town, phone, truck_name,
                                     location, image1, image2, image3)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (name, district, town, phone, truck_name,
                  location, url1, url2, url3))
            conn.commit()
            cursor.close()
            conn.close()

            return "Driver information saved successfully"
        except Exception as e:
            print(f"ERROR in driver registration: {str(e)}")
            print(traceback.format_exc())
            return f"Error: {str(e)}", 500
    else:
        return render_template("driverdetails.html")

@app.route("/registereddrivers")
def registereddrivers():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM drivers")
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    data = [dict(zip(columns, row)) for row in rows]
    cursor.close()
    conn.close()
    return render_template("registereddriversview.html", data=data)

@app.route("/alldrivers")
def alldrivers():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM drivers")
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    data = [dict(zip(columns, row)) for row in rows]
    cursor.close()
    conn.close()
    return render_template("alldriversview.html", data=data)

# -------------------------
# Deals Section (UPDATED for Cloudinary with Live Location)
# -------------------------
@app.route("/deals")
def deals():
    return render_template("dealsform.html")

@app.route("/save", methods=["POST"])
def save():
    try:
        suppliername = request.form["suppliername"]
        materialname = request.form["materialname"]
        tippername = request.form["tippername"]
        location = request.form["location"]
        phone = request.form["phone"]
        
        # Get live location from form (sent from frontend)
        live_latitude = request.form.get("live_latitude")
        live_longitude = request.form.get("live_longitude")
        
        # Convert to None if empty string
        if live_latitude == "" or live_latitude is None:
            live_latitude = None
        else:
            live_latitude = float(live_latitude)
            
        if live_longitude == "" or live_longitude is None:
            live_longitude = None
        else:
            live_longitude = float(live_longitude)

        image1 = request.files.get("imageone")
        image2 = request.files.get("image2")

        url1 = save_image(image1, f"deal_{suppliername}_1")
        url2 = save_image(image2, f"deal_{suppliername}_2")

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO deals (suppliername, materialname, tippername, location, live_latitude, live_longitude, phone, imageone, imagetwo)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (suppliername, materialname, tippername, location, live_latitude, live_longitude, phone, url1, url2))
        conn.commit()
        
        # Get the ID of the newly created deal
        cursor.execute("SELECT LASTVAL()")
        deal_id = cursor.fetchone()[0]
        
        cursor.close()
        conn.close()

        # Return success with deal ID for tracking
        return f"""Your deal has been uploaded successfully!
        
        Tracking URL: {request.url_root}track_deal/{deal_id}
        Share this link to track this deal live!"""
    except Exception as e:
        print(f"ERROR in save deal: {str(e)}")
        print(traceback.format_exc())
        return f"Error: {str(e)}", 500

@app.route("/table")
def table():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM deals")
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    data = [dict(zip(columns, row)) for row in rows]
    cursor.close()
    conn.close()
    return render_template("table.html", data=data)

@app.route("/dealstocustomer")
def dealstocustomer():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM deals")
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    data = [dict(zip(columns, row)) for row in rows]
    cursor.close()
    conn.close()
    return render_template("customerdealsview.html", data=data)

@app.route("/dealstoadmin")
def dealstoadmin():
    """Admin view with live map tracking"""
    conn = get_db_connection()
    cursor = conn.cursor()
    # Get deals with their latest tracking info
    cursor.execute("""
        SELECT d.*, 
               dt.latitude as last_latitude, 
               dt.longitude as last_longitude,
               dt.timestamp as last_update,
               dt.accuracy as last_accuracy
        FROM deals d
        LEFT JOIN (
            SELECT DISTINCT ON (deal_id) deal_id, latitude, longitude, timestamp, accuracy
            FROM deal_tracking
            ORDER BY deal_id, timestamp DESC
        ) dt ON d.id = dt.deal_id
        ORDER BY d.created_at DESC
    """)
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    data = [dict(zip(columns, row)) for row in rows]
    cursor.close()
    conn.close()
    return render_template("admindealsview.html", data=data)

@app.route("/dealspage")
def dealspage():
    return render_template("dealspage.html")

# -------------------------
# Orders Table (UPDATED for Cloudinary)
# -------------------------
@app.route("/order")
def order_form():
    return render_template("order_form.html")

@app.route("/submit_order", methods=["POST"])
def submit_order():
    try:
        name = request.form["name"]
        district = request.form["district"]
        town = request.form["town"]
        truck_name = request.form["truck_name"]
        material_service = request.form["material_service"]
        location = request.form["location"]
        phone = request.form["phone"]

        image1 = request.files.get("image1")
        image2 = request.files.get("image2")

        # These will now upload to Cloudinary automatically
        url1 = save_image(image1, f"order_{name}_1")
        url2 = save_image(image2, f"order_{name}_2")

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO orders (name, district, town, truck_name, material_service, location, phone, image1, image2)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (name, district, town, truck_name, material_service, location, phone, url1, url2))
        conn.commit()
        cursor.close()
        conn.close()

        return "Your order has been placed successfully! We will contact you soon."
    except Exception as e:
        print(f"ERROR in submit order: {str(e)}")
        print(traceback.format_exc())
        return f"Error: {str(e)}", 500

@app.route("/view_orders")
def view_orders():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM orders ORDER BY created_at DESC")
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    orders = [dict(zip(columns, row)) for row in rows]
    cursor.close()
    conn.close()
    return render_template("view_orders.html", orders=orders)

@app.route("/edit_order/<int:order_id>")
def edit_order_form(order_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
    row = cursor.fetchone()
    if not row:
        cursor.close()
        conn.close()
        return "Order not found", 404
    columns = [desc[0] for desc in cursor.description]
    order = dict(zip(columns, row))
    cursor.close()
    conn.close()
    return render_template("edit_order.html", order=order)

@app.route("/update_order/<int:order_id>", methods=["POST"])
def update_order(order_id):
    try:
        name = request.form["name"]
        district = request.form["district"]
        town = request.form["town"]
        truck_name = request.form["truck_name"]
        material_service = request.form["material_service"]
        location = request.form["location"]
        phone = request.form["phone"]

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT image1, image2 FROM orders WHERE id = %s", (order_id,))
        old = cursor.fetchone()
        if not old:
            cursor.close()
            conn.close()
            return "Order not found", 404
        old_image1, old_image2 = old

        image1 = request.files.get("image1")
        image2 = request.files.get("image2")

        url1 = old_image1
        if image1 and image1.filename:
            url1 = save_image(image1, f"order_{name}_1")

        url2 = old_image2
        if image2 and image2.filename:
            url2 = save_image(image2, f"order_{name}_2")

        cursor.execute("""
            UPDATE orders
            SET name=%s, district=%s, town=%s, truck_name=%s, material_service=%s, location=%s, phone=%s, image1=%s, image2=%s
            WHERE id=%s
        """, (name, district, town, truck_name, material_service, location, phone, url1, url2, order_id))
        conn.commit()
        cursor.close()
        conn.close()
        return redirect(url_for('view_orders'))
    except Exception as e:
        print(f"ERROR in update order: {str(e)}")
        print(traceback.format_exc())
        return f"Error: {str(e)}", 500

@app.route("/delete_order/<int:order_id>")
def delete_order(order_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM orders WHERE id = %s", (order_id,))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for('view_orders'))

# -------------------------
# WhatsApp Webhook (unchanged)
# -------------------------
@app.route('/whatsapp', methods=['POST'])
def whatsapp_reply():
    incoming_msg = request.values.get('Body', '').lower()
    resp = MessagingResponse()
    msg = resp.message()

    if 'hello' in incoming_msg:
        msg.body("Hi there! 👋 send us your shopping items?")
    elif 'how are you' in incoming_msg:
        msg.body("I'm doing great, thanks for asking! 😊")
    elif 'bye' in incoming_msg:
        msg.body("Goodbye! Have a wonderful day! 👋")
    else:
        msg.body("Thanks for your message! I'm a simple bot. Try saying 'hello', 'how are you', or 'bye'.")

    return str(resp)

# -------------------------
# Search drivers by district & town (unchanged)
# -------------------------
@app.route("/searchdriverbydt")
def searchdriverbydt():
    return render_template("search_driver_by.html")

@app.route('/search_driversby', methods=['GET', 'POST'])
def search_driversby():
    district = request.form['district'].strip()
    town = request.form['town'].strip()

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM drivers
        WHERE LOWER(district) = LOWER(%s)
        AND LOWER(town) = LOWER(%s)
    """, (district, town))

    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    drivers = [dict(zip(columns, row)) for row in rows]

    cursor.close()
    conn.close()

    return render_template("drivers_results.html", drivers=drivers)

# Route that creates a link to a particular driver card details
@app.route('/driver_details/<int:driver_id>')
def driver_details(driver_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM drivers WHERE id = %s", (driver_id,))
    row = cursor.fetchone()
    
    if not row:
        cursor.close()
        conn.close()
        return "Driver not found", 404
    
    columns = [desc[0] for desc in cursor.description]
    driver = dict(zip(columns, row))
    
    cursor.close()
    conn.close()
    
    return render_template("driver_details.html", driver=driver)

# -------------------------
# Run the app
# -------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
