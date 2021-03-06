from flask import *
from functools import wraps
from hashlib import sha256
from math import cos, asin, sqrt
import config
import database
import uuid
import requests

app = Flask(__name__)
app.config.from_object('config')

def login_required(f):
    @wraps(f)
    def with_login(*args, **kwargs):
        if session.get('username', None) is None:
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return with_login


def get_trip_obj(record):
    keys = [
        'id', 'username', 'origin', 'originLat', 'originLng',
        'destination', 'destinationLat', 'destinationLng',
        'seats', 'fare', 'date', 'time'
    ]
    return dict(zip(keys, record))


def distance(lat1, lon1, lat2, lon2):
    p = 0.017453292519943295     # pi/180
    a = 0.5 - cos((lat2 - lat1) * p) / 2 + cos(lat1 * p) * cos(lat2 * p) * (1 - cos((lon2 - lon1) * p)) / 2
    return 7917.5117 * asin(sqrt(a))


@app.route('/', methods=['GET'])
def index():
    if session.get('username', None) is not None:
        return redirect(url_for('my_trips'))

    return render_template('index.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        record = database.fetchone('SELECT password, salt FROM users WHERE username="{}";'.format(username))
        if not record:
            return render_template('login.html', error='Invalid username or password')

        correct_password, salt = record
        hashed_password = sha256((password + salt).encode()).hexdigest()

        if hashed_password != correct_password:
            return render_template('login.html', error='Invalid username or password')

        session['username'] = username
        return redirect(url_for('my_trips'))

    if session.get('username', None) is not None:
        return redirect(url_for('my_trips'))

    return render_template('login.html')


@app.route('/logout', methods=['GET'])
def logout():
    session.pop('username', None)
    return redirect(url_for('index'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        salt = uuid.uuid4().hex

        hashed_password = sha256((password + salt).encode()).hexdigest()

        database.execute('INSERT INTO users VALUES ("{}", "{}", "{}");'.format(username, hashed_password, salt))
        return render_template('register.html', success='User registered successfully')

    return render_template('register.html')


@app.route('/trips', methods=['GET', 'POST'])
@login_required
def trips():
    if request.method == 'POST':
        id = uuid.uuid4()
        username = session['username']
        origin = request.form['origin']
        originLat = request.form['originLat']
        originLng = request.form['originLng']
        destination = request.form['destination']
        destinationLat = request.form['destinationLat']
        destinationLng = request.form['destinationLng']
        seats = request.form['seats']
        fare = request.form['fare']
        date = request.form['date']
        time = request.form['time']

        database.execute(
            'INSERT INTO trips VALUES ("{}", "{}", "{}", "{}", "{}", "{}", "{}", "{}", "{}", "{}", "{}", "{}");'.format(
                id, username, origin, originLat, originLng, destination, destinationLat, destinationLng, seats, fare, date, time
            )
        )
        return redirect(url_for('trip', id=id))

    all_trips = database.fetchall('SELECT * FROM trips WHERE date >= date("now");')
    trips = list(map(get_trip_obj, all_trips))
    passenger_count = dict(database.fetchall('SELECT id, COUNT(*) FROM carpools GROUP BY id;'))

    radius = request.args.get('radius', 10)
    originLat = request.args.get('originLat', None)
    originLng = request.args.get('originLng', None)
    destinationLat = request.args.get('destinationLat', None)
    destinationLng = request.args.get('destinationLng', None)

    if originLat and originLng:
        trips = [trip for trip in trips if distance(trip['originLat'], trip['originLng'], float(originLat), float(originLng)) <= float(radius)]
    if destinationLat and destinationLng:
        trips = [trip for trip in trips if distance(trip['destinationLat'], trip['destinationLng'], float(destinationLat), float(destinationLng)) <= float(radius)]

    return render_template('trip_list.html', trips=trips, passenger_count=passenger_count, filter=request.args)


@app.route('/my_trips', methods=['GET'])
@login_required
def my_trips():
    username = session['username']

    driver_trips = database.fetchall('SELECT * FROM trips WHERE username="{}";'.format(username))
    driver_trips = list(map(get_trip_obj, driver_trips))

    rider_trip_ids = database.fetchall('SELECT id FROM carpools WHERE username="{}";'.format(username))
    rider_trip_ids = [t[0] for t in rider_trip_ids]
    rider_trips = database.fetchall('SELECT * FROM trips WHERE id IN ({})'.format('"' + '","'.join(rider_trip_ids) + '"'))
    rider_trips = list(map(get_trip_obj, rider_trips))

    passenger_count = dict(database.fetchall('SELECT id, COUNT(*) FROM carpools GROUP BY id;'))

    return render_template('my_trip_list.html', driver_trips=driver_trips, rider_trips=rider_trips, passenger_count=passenger_count)


@app.route('/trips/new', methods=['GET'])
@login_required
def new_trip():
    return render_template('trip_form.html')


@app.route('/trips/<uuid:id>', methods=['GET', 'POST'])
@login_required
def trip(id=None):
    trip = database.fetchone('SELECT * FROM trips WHERE id="{}";'.format(id))
    if not trip:
        return render_template('trips.html', error='Invalid trip ID')
    trip = get_trip_obj(trip)

    if request.method == 'POST':
        username = session['username']

        database.execute('INSERT INTO carpools VALUES ("{}", "{}");'.format(id, username))
        passengers = database.fetchall('SELECT username FROM carpools WHERE id="{}";'.format(id))
        passengers = [p[0] for p in passengers]
        return render_template('trip.html', trip=trip, passengers=passengers, success='Trip joined successfully')

    passengers = database.fetchall('SELECT username FROM carpools WHERE id="{}"'.format(id))
    passengers = [p[0] for p in passengers]
    return render_template('trip.html', trip=trip, passengers=passengers)


@app.route('/trips/<uuid:id>/leave', methods=['POST'])
@login_required
def leave_trip(id=None):
    username = session['username']
    trip = database.fetchone('SELECT * FROM trips WHERE id="{}";'.format(id))
    if not trip:
        return render_template('trips.html', error='Invalid trip ID')
    trip = get_trip_obj(trip)

    database.execute('DELETE FROM carpools WHERE id="{}" AND username="{}";'.format(id, username))
    return redirect(url_for('trip', id=id))


@app.route('/trips/<uuid:id>/delete', methods=['POST'])
@login_required
def delete_trip(id=None):
    trip = database.fetchone('SELECT * FROM trips WHERE id="{}";'.format(id))
    if not trip:
        return render_template('trips.html', error='Invalid trip ID')
    trip = get_trip_obj(trip)

    database.execute('DELETE FROM trips WHERE id="{}";'.format(id))
    database.execute('DELETE FROM carpools WHERE id="{}";'.format(id))
    return redirect(url_for('my_trips'))


@app.errorhandler(404)
def not_found(error):
    return render_template('not_found.html'), 404


@app.errorhandler(500)
def error(error):
    return render_template('error.html', message=error), 500
