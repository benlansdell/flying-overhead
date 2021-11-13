from flask import Flask, render_template, request
import requests
import pandas as pd
import numpy as np

from private_keys import IPSTACK_KEY, MAPBOX_KEY

app = Flask(__name__)
app.flights = pd.DataFrame({'Distance': []})

HEADERS = {'Content-Type': 'application/json'}
OPENSKY_URL = 'https://opensky-network.org/api/states/all'
IPSTACK_URL = 'http://api.ipstack.com/check'

PM_MILES = 50                          # flight search radius for the table
UPDATE_INTERVAL = 5000                 # update webpage this many milliseconds
DEFAULT_LOCATION = [51.505, -0.09]     # London
OVERHEAD_RADIUS = 4                    # alert when plane is within this distance
EARTH_RADIUS = 6371e3                  # radius of earth, in metres

#All OpenSky column names
col_names = ['icao24', 'callsign', 'origin_country', 'time_position', 
             'last_contact', 'longitude', 'latitude', 'baro_altitude', 
             'on_ground', 'velocity', 'true_track', 'vertical_rate', 
             'sensors', 'geo_altitude', 'squawk', 'spi', 'position_source', 'o']

#Only the OpenSky column names we'll display
select_col_names = ['callsign', 'origin_country', 'longitude', 
                    'latitude', 'baro_altitude', 'on_ground', 'velocity', 
                    'true_track', 'vertical_rate']

renamed_col_names = ['Callsign', 'Origin country', 'Longitude', 
                    'Latitude', 'Barometric altitude', 'On ground', 'Velocity', 
                    'True track', 'Vertical rate']

renamer = {k:v for k,v in zip(select_col_names, renamed_col_names)}

column_keys = pd.DataFrame([["Callsign", "Callsign of the vehicle (8 chars)."],
                            ["Origin country", "Country name inferred from the ICAO 24-bit address."],
                            ["Longitude", "WGS-84 longitude in decimal degrees."],
                            ["Latitude", "WGS-84 latitude in decimal degrees."],
                            ["Barometric altitude", "Barometric altitude in meters."],
                            ["On ground", "Boolean value which indicates if the position was retrieved from a surface position report."],
                            ["Velocity", "Velocity over ground in m/s."],
                            ["True track", "True track in decimal degrees clockwise from north (north=0°)."],
                            ["Vertical rate", "Vertical rate in m/s. A positive value indicates that the airplane is climbing, a negative value indicates that it descends."],
                            ["Distance", "Distance plane is from you (in miles)"]],
                            columns = ['Key', 'Description'])
column_keys = column_keys.set_index('Key')

# Use IPStack to get an approximate location
def get_location():
    params = {'access_key': IPSTACK_KEY}
    response = requests.get(IPSTACK_URL, params=params)
    assert response.status_code == 200
    ipstack_resp = response.json()
    try:
        lat = ipstack_resp['latitude']
        long = ipstack_resp['longitude']
    except KeyError:
        print("Failed to get location from IP address")
        lat = DEFAULT_LOCATION[0]
        long = DEFAULT_LOCATION[1]
    return lat, long

def get_flights_opensky(location = None):

    if location is None:
        #If location data wasn't pulled from the browser, then just use IP (not as accurate)
        lat, long = get_location()
    else:
        lat, long = location

    miles_per_deg_lat = 69.1
    miles_per_deg_lng = 69.1*np.cos(lat/180*np.pi)
    lat_pm = PM_MILES/miles_per_deg_lat
    lng_pm = PM_MILES/miles_per_deg_lng

    params = {
          'lamin': lat-lat_pm,
          'lomin': long-lng_pm,
          'lamax': lat+lat_pm,
          'lomax': long+lng_pm
          }

    #Get planes from open sky API    
    response = requests.get(OPENSKY_URL, params=params, headers=HEADERS)
    assert response.status_code == 200
    states = response.json()['states']
    if hasattr(states, '__len__'):
        if len(states[0]) != 18:
            print(f"{len(states[0])} columns returned, generally 18 columns expected from OpenSky REST API")
        these_col_names = col_names[:len(states[0])]
    else:
        these_col_names = col_names
    df = pd.DataFrame(states, columns = these_col_names)
    df = df[select_col_names]
    df = df.rename(columns = renamer)
    df = df.set_index('Callsign')
    return df, (lat, long)

def distance_in_miles(lat1, lon1, lat2, lon2):
    phi1 = lat1*np.pi/180           # φ, λ in radians
    phi2 = lat2*np.pi/180
    del_phi = (lat2 - lat1)*np.pi/180
    del_lambda = (lon2 - lon1)*np.pi/180

    a = np.sin(del_phi/2)*np.sin(del_phi/2) + \
        np.cos(phi1)*np.cos(phi2)*np.sin(del_lambda/2)*np.sin(del_lambda/2)

    c = 2*np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    d = EARTH_RADIUS*c;            # in meters
    return d/1600                  # convert to miles

def get_flights(location = None):
    df, (browser_lat, browser_long) = get_flights_opensky(location)
    #Add distance from current position as column
    lats = df['Latitude']
    longs = df['Longitude']
    distances = [distance_in_miles(la, lo, browser_lat, browser_long) for la,lo in zip(lats, longs)]
    df['Distance'] = distances
    df = df[df['Distance'] < PM_MILES] 
    return df, (browser_lat, browser_long)

@app.route('/')
def index():
    flights, location = get_flights()
    app.flights = flights
    app.location = location
    return render_template('index.html', 
                           table = flights.to_html(), 
                           location = location,
                           column_keys = column_keys.to_html(), 
                           pm_miles = PM_MILES,
                           update_interval = UPDATE_INTERVAL,
                           default_location = DEFAULT_LOCATION, 
                           overhead_radius = OVERHEAD_RADIUS, 
                           mapbox_key = MAPBOX_KEY)

@app.route('/flights')
def flights():
    location = float(request.args.get('lat')), float(request.args.get('lng'))
    flights, _ = get_flights(location = location)
    app.flights = flights
    app.location = location
    return flights.to_html()

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/check_overhead')
def check_overhead():
    is_overhead = False
    if any(app.flights.Distance < OVERHEAD_RADIUS):
        is_overhead = True
    min_distance = np.min(app.flights.Distance)
    return {'overhead': is_overhead, 'min_dist': min_distance}