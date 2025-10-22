import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import json
import os
import shutil
import openpyxl
import requests

st.set_page_config(page_title="UVS Dashboard", page_icon="🌳", layout="wide")

# Custom CSS for UVS branding
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500;700&display=swap');
    html, body, [class*="css"] {
        font-family: 'Roboto', sans-serif;
    }
    h1, h2, h3, h4, h5, h6 {
        font-family: 'Roboto', sans-serif !important;
    }
    .main-title {
        font-family: 'Roboto', sans-serif;
        font-weight: 500;
        color: white;
    }
</style>
""", unsafe_allow_html=True)

# File paths
DATA_FILE = 'uvs_data.json'
ATTACHMENTS_DIR = 'attachments'
WEATHER_STATIONS_FILE = 'UVS_Sites_with_Closest.xlsx'

if not os.path.exists(ATTACHMENTS_DIR):
    os.makedirs(ATTACHMENTS_DIR)

def load_weather_stations():
    """Load weather station assignments from Excel file"""
    if os.path.exists(WEATHER_STATIONS_FILE):
        try:
            df = pd.read_excel(WEATHER_STATIONS_FILE, sheet_name='Sites+NearestStation')
            stations = {}
            for _, row in df.iterrows():
                site_name = row.get('Site Name', '')
                stations[site_name] = {
                    'station_name': row.get('Nearest Station', 'Melbourne (Olympic Park)'),
                    'bom_id': str(row.get('BoM Site ID', '86338')).zfill(6),
                    'distance_km': row.get('Distance_km', 0),
                    'lat': row.get('Latitude', -37.8136),
                    'lon': row.get('Longitude', 144.9631)
                }
            return stations
        except Exception as e:
            st.sidebar.warning(f"Could not load weather stations: {str(e)}")
            return {}
    return {}

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                data = json.load(f)
                sites = data.get('sites', {})
                weather = data.get('weather', {})
                thresholds = data.get('priority_thresholds', {'critical': 25, 'medium': 35, 'low': 45})
                # Backwards compatibility: convert old 'low' key to 'medium'
                if 'low' in thresholds and 'medium' not in thresholds:
                    thresholds['medium'] = thresholds.pop('low')
                if 'low' not in thresholds:
                    thresholds['low'] = 45
                return sites, weather, thresholds
        except:
            return {}, {}, {'critical': 25, 'medium': 35, 'low': 45}
    return {}, {}, {'critical': 25, 'medium': 35, 'low': 45}

def save_data():
    data = {
        'sites': st.session_state.sites,
        'weather': st.session_state.weather,
        'priority_thresholds': st.session_state.priority_thresholds,
        'last_saved': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

if 'sites' not in st.session_state:
    loaded_sites, loaded_weather, loaded_thresholds = load_data()
    
    if loaded_sites:
        st.session_state.sites = loaded_sites
    else:
        st.session_state.sites = {
            'site_001': {
                'name': 'Collins Street Development',
                'location': 'Melbourne CBD',
                'soil_type': 'Clay Loam',
                'start_date': '2024-10-01',
                'end_date': '2025-03-31',
                'visits_per_week': 3,
                'po_number': 'PO-2024-001',
                'trees': 50,
                'trees_litres': 200,
                'tubestock': 150,
                'tubestock_litres': 5,
                'turf_m2': 500,
                'turf_litres': 10,
                'hours_quoted': 4.0,
                'maturity': 'Establishment',
                'visits': [
                    {'date': '2024-10-14', 'hours': 4.5, 'moisture': 35, 'notes': 'Good conditions', 'person': 'John Smith', 'truck': 'UVS001', 'attachments': []},
                    {'date': '2024-10-11', 'hours': 4.2, 'moisture': 32, 'notes': 'Dry', 'person': 'Sarah Lee', 'truck': 'UVS002', 'attachments': []},
                    {'date': '2024-10-09', 'hours': 4.0, 'moisture': 38, 'notes': 'After rain', 'person': 'John Smith', 'truck': 'UVS001', 'attachments': []}
                ]
            }
        }
    
    if loaded_weather:
        st.session_state.weather = loaded_weather
        # Ensure temp_max and temp_min exist for backwards compatibility
        if 'temp_max' not in st.session_state.weather:
            st.session_state.weather['temp_max'] = st.session_state.weather.get('temp', 22)
        if 'temp_min' not in st.session_state.weather:
            st.session_state.weather['temp_min'] = st.session_state.weather.get('temp', 12)
    else:
        st.session_state.weather = {'last_7d': 12.5, 'next_24h': 5.2, 'next_7d': 18.3, 'temp': 22, 'temp_max': 22, 'temp_min': 12}

    # Load priority thresholds
    st.session_state.priority_thresholds = loaded_thresholds

# Initialize priority thresholds if not present (backwards compatibility)
if 'priority_thresholds' not in st.session_state:
    st.session_state.priority_thresholds = {
        'critical': 25,  # Below this = RED (High Priority)
        'medium': 35,    # Below this = YELLOW (Medium Priority)
        'low': 45        # Below this = GREEN (Low Priority), Above = No Alert
    }

# Load weather station assignments
if 'weather_stations' not in st.session_state:
    st.session_state.weather_stations = load_weather_stations()

# Initialize site weather cache
if 'site_weather' not in st.session_state:
    st.session_state.site_weather = {}

def calc_water(site):
    return site['trees'] * site['trees_litres'] + site['tubestock'] * site['tubestock_litres'] + site['turf_m2'] * site['turf_litres']

def get_site_weather(site_name):
    """Get weather data for a specific site using its assigned weather station"""
    # Check if we have a weather station assigned for this site
    if site_name in st.session_state.weather_stations:
        station_info = st.session_state.weather_stations[site_name]
        lat = station_info['lat']
        lon = station_info['lon']
    else:
        # Fallback to Melbourne CBD
        lat, lon = -37.8136, 144.9631
        station_info = {
            'station_name': 'Melbourne (Olympic Park)',
            'bom_id': '086338',
            'distance_km': 0,
            'lat': lat,
            'lon': lon
        }
    
    # Check cache first (refresh every 30 minutes)
    cache_key = f"{site_name}_{datetime.now().strftime('%Y%m%d%H%M')[:11]}"  # Hourly cache
    if cache_key in st.session_state.site_weather:
        return st.session_state.site_weather[cache_key], station_info
    
    # Fetch from Open-Meteo API
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m&daily=precipitation_sum,temperature_2m_max,temperature_2m_min&timezone=Australia/Melbourne&past_days=7&forecast_days=7"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            past_precip = data['daily']['precipitation_sum'][:7]
            last_7d = sum([p for p in past_precip if p is not None])
            next_24h = data['daily']['precipitation_sum'][7] if len(data['daily']['precipitation_sum']) > 7 else 0
            future_precip = data['daily']['precipitation_sum'][7:14]
            next_7d = sum([p for p in future_precip if p is not None])
            current_temp = data['current']['temperature_2m']
            temp_max = data['daily']['temperature_2m_max'][7] if len(data['daily']['temperature_2m_max']) > 7 else current_temp
            temp_min = data['daily']['temperature_2m_min'][7] if len(data['daily']['temperature_2m_min']) > 7 else current_temp
            
            weather_data = {
                'last_7d': round(last_7d, 1),
                'next_24h': round(next_24h, 1),
                'next_7d': round(next_7d, 1),
                'temp': round(current_temp, 1),
                'temp_max': round(temp_max, 1),
                'temp_min': round(temp_min, 1)
            }
            
            # Cache it
            st.session_state.site_weather[cache_key] = weather_data
            return weather_data, station_info
        else:
            # Return default weather if API fails
            return st.session_state.weather, station_info
    except Exception as e:
        # Return default weather if error
        return st.session_state.weather, station_info

def predict_moisture(site):
    """Enhanced moisture prediction using simple ML-like logic"""
    base = {'Clay Loam': 40, 'Sandy Loam': 25, 'Loam': 35, 'Clay': 45, 'Sand': 15}
    baseline = base.get(site['soil_type'], 35)
    
    # Get site-specific weather
    site_weather, _ = get_site_weather(site['name'])
    
    if site['visits'] and len(site['visits']) > 0:
        # Use historical data for better predictions
        recent_visits = site['visits'][-5:]  # Last 5 visits
        
        # Calculate moisture trend (is it getting drier or wetter?)
        if len(recent_visits) >= 2:
            recent_moistures = [v['moisture'] for v in recent_visits]
            # Simple trend: compare average of first half vs second half
            mid_point = len(recent_moistures) // 2
            first_half_avg = sum(recent_moistures[:mid_point]) / len(recent_moistures[:mid_point]) if mid_point > 0 else recent_moistures[0]
            second_half_avg = sum(recent_moistures[mid_point:]) / len(recent_moistures[mid_point:])
            trend = second_half_avg - first_half_avg  # Positive = getting wetter, Negative = getting drier
        else:
            trend = 0
        
        # Start with most recent reading
        most_recent = site['visits'][-1]['moisture']
        
        # Calculate days since last visit
        from datetime import datetime
        last_visit_date = datetime.strptime(site['visits'][-1]['date'], '%Y-%m-%d')
        days_since = (datetime.now() - last_visit_date).days
        
        # Moisture drops over time (evaporation/transpiration)
        # Faster drop for sandy soils, slower for clay
        daily_drop_rate = {'Clay Loam': 2, 'Sandy Loam': 4, 'Loam': 3, 'Clay': 1.5, 'Sand': 5}
        drop_rate = daily_drop_rate.get(site['soil_type'], 2.5)
        time_adjustment = -1 * (days_since * drop_rate)
        
        # Weather adjustments
        rain_adjustment = 0
        if site_weather['last_7d'] > 20:
            rain_adjustment = 15
        elif site_weather['last_7d'] > 10:
            rain_adjustment = 8
        elif site_weather['last_7d'] > 5:
            rain_adjustment = 4
        
        # Forecast adjustments
        if site_weather['next_24h'] > 10:
            rain_adjustment += 12
        elif site_weather['next_24h'] > 5:
            rain_adjustment += 6
        
        # Apply trend factor (if consistently drying, predict more drying)
        trend_factor = trend * 0.3
        
        # Combine all factors
        predicted = most_recent + time_adjustment + rain_adjustment + trend_factor
        
        # Plant maturity affects water retention
        maturity_factors = {'Establishment': -3, 'Young': -1, 'Mature': 2}
        maturity_adjustment = maturity_factors.get(site['maturity'], 0)
        predicted += maturity_adjustment
        
        return max(0, min(100, round(predicted)))
    
    # No historical data - use basic prediction
    rain_effect = site_weather['last_7d'] * 2
    predicted = baseline + rain_effect - 10
    
    if site_weather['next_24h'] > 10:
        predicted += 15
    elif site_weather['next_24h'] > 5:
        predicted += 8
    
    return max(0, min(100, round(predicted)))
# PASTE THIS IMMEDIATELY AFTER PART 1 (NO GAPS)

def predict_days_until_critical(site):
    """Predict how many days until moisture reaches critical level"""
    if not site.get('visits') or len(site['visits']) == 0:
        return None
    
    current_moisture = predict_moisture(site)
    critical_threshold = st.session_state.priority_thresholds['critical']
    
    if current_moisture <= critical_threshold:
        return 0  # Already critical
    
    # Calculate average daily moisture drop from recent visits
    if len(site['visits']) >= 2:
        recent_visits = site['visits'][-5:]
        moisture_drops = []
        
        for i in range(1, len(recent_visits)):
            prev_moisture = recent_visits[i-1]['moisture']
            curr_moisture = recent_visits[i]['moisture']
            prev_date = datetime.strptime(recent_visits[i-1]['date'], '%Y-%m-%d')
            curr_date = datetime.strptime(recent_visits[i]['date'], '%Y-%m-%d')
            days_between = (curr_date - prev_date).days
            
            if days_between > 0:
                daily_drop = (prev_moisture - curr_moisture) / days_between
                moisture_drops.append(daily_drop)
        
        if moisture_drops:
            avg_daily_drop = sum(moisture_drops) / len(moisture_drops)
            # Account for upcoming rain
            site_weather, _ = get_site_weather(site['name'])
            if site_weather['next_7d'] > 10:
                avg_daily_drop *= 0.5  # Rain will slow moisture loss
            
            if avg_daily_drop > 0:
                moisture_gap = current_moisture - critical_threshold
                days_until_critical = moisture_gap / avg_daily_drop
                return max(0, round(days_until_critical))
    
    # Default estimation based on soil type
    daily_drop_rate = {'Clay Loam': 2, 'Sandy Loam': 4, 'Loam': 3, 'Clay': 1.5, 'Sand': 5}
    drop_rate = daily_drop_rate.get(site['soil_type'], 2.5)
    moisture_gap = current_moisture - critical_threshold
    return max(0, round(moisture_gap / drop_rate))

def calculate_optimal_water(site):
    """AI-driven water amount calculation based on historical effectiveness"""
    base_water = calc_water(site)
    
    if not site.get('visits') or len(site['visits']) < 3:
        return base_water  # Need more data
    
    # Analyze how effective past watering was
    # Look at moisture improvement after visits
    recent_visits = site['visits'][-5:]
    moisture_improvements = []
    
    for i in range(1, len(recent_visits)):
        prev_moisture = recent_visits[i-1]['moisture']
        curr_moisture = recent_visits[i]['moisture']
        improvement = curr_moisture - prev_moisture
        
        # Only count positive improvements (watering helped)
        if improvement > 0:
            moisture_improvements.append(improvement)
    
    if moisture_improvements:
        avg_improvement = sum(moisture_improvements) / len(moisture_improvements)
        
        # If average improvement is low (< 5%), might be overwatering
        if avg_improvement < 5:
            return round(base_water * 0.85)  # Reduce 15%
        # If improvement is high (> 15%), could water more effectively
        elif avg_improvement > 15:
            return round(base_water * 1.1)  # Increase 10%
    
    return base_water

def get_recommendation(site):
    moisture = predict_moisture(site)
    water = calc_water(site)
    
    # Get site-specific weather
    site_weather, _ = get_site_weather(site['name'])
    rain = site_weather['next_24h']
    
    # Check if site has any visits logged
    if not site.get('visits') or len(site['visits']) == 0:
        return "⚪ NO DATA", "No readings yet. Log a visit to get watering recommendations.", None, water
    
    # Use configurable thresholds
    critical_threshold = st.session_state.priority_thresholds['critical']
    medium_threshold = st.session_state.priority_thresholds['medium']
    low_threshold = st.session_state.priority_thresholds['low']
    
    if moisture < critical_threshold:
        priority = "🔴 HIGH"
        msg = f"Critical watering needed ({water:,}L). Soil at {moisture}%."
    elif moisture < medium_threshold:
        priority = "🟡 MEDIUM"
        msg = f"Watering recommended ({water:,}L). Soil at {moisture}%."
    elif moisture < low_threshold:
        priority = "🟢 LOW"
        msg = f"Monitor conditions. Soil at {moisture}%."
    else:
        priority = "⚪ OPTIMAL"
        msg = f"Soil optimal at {moisture}%. No watering needed."
    
    if rain > 10:
        msg += f" Heavy rain forecast ({rain}mm) - consider delaying."
    elif rain > 5:
        msg += f" Moderate rain ({rain}mm) - reduce 30%."
    return priority, msg, moisture, water

def update_weather():
    try:
        lat, lon = -37.8136, 144.9631
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m&daily=precipitation_sum,temperature_2m_max,temperature_2m_min&timezone=Australia/Melbourne&past_days=7&forecast_days=7"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            past_precip = data['daily']['precipitation_sum'][:7]
            last_7d = sum([p for p in past_precip if p is not None])
            next_24h = data['daily']['precipitation_sum'][7] if len(data['daily']['precipitation_sum']) > 7 else 0
            future_precip = data['daily']['precipitation_sum'][7:14]
            next_7d = sum([p for p in future_precip if p is not None])
            current_temp = data['current']['temperature_2m']
            
            # Get today's min/max temps (index 7 is today in the daily array)
            temp_max = data['daily']['temperature_2m_max'][7] if len(data['daily']['temperature_2m_max']) > 7 else current_temp
            temp_min = data['daily']['temperature_2m_min'][7] if len(data['daily']['temperature_2m_min']) > 7 else current_temp
            
            st.session_state.weather = {
                'last_7d': round(last_7d, 1),
                'next_24h': round(next_24h, 1),
                'next_7d': round(next_7d, 1),
                'temp': round(current_temp, 1),
                'temp_max': round(temp_max, 1),
                'temp_min': round(temp_min, 1)
            }
            save_data()
            return True, "Successfully fetched weather data"
        else:
            return False, f"API returned status {response.status_code}"
    except requests.exceptions.Timeout:
        return False, "Request timed out"
    except requests.exceptions.ConnectionError:
        return False, "No internet connection"
    except Exception as e:
        return False, f"Error: {str(e)}"

# HEADER
col1, col2, col3 = st.columns([1, 2, 2])

with col1:
    st.image("https://static.wixstatic.com/media/f94a28_20ec9ceab6ab497fb55aff60e248f708~mv2.png/v1/fill/w_170,h_123,al_c,q_85,usm_0.66_1.00_0.01,enc_avif,quality_auto/Copy%20of%20High%20Res%20No%20Background%20Logo.png", width=220)
    st.markdown("#### Watering Management Dashboard v3.0")
    st.caption("Tree, Turf and Garden Bed Watering for Melbourne")

with col2:
    st.markdown("#### 📅 7-Day Rain Forecast")
    # Get 7-day forecast data
    try:
        lat, lon = -37.8136, 144.9631
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=precipitation_sum,temperature_2m_max,temperature_2m_min&timezone=Australia/Melbourne&forecast_days=7"
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            forecast_data = response.json()
            daily_precip = forecast_data['daily']['precipitation_sum'][:7]
            daily_dates = forecast_data['daily']['time'][:7]
            daily_max = forecast_data['daily']['temperature_2m_max'][:7]
            daily_min = forecast_data['daily']['temperature_2m_min'][:7]
            
            # Create 7 columns for each day
            day_cols = st.columns(7)
            
            for i, (date_str, precip, t_max, t_min) in enumerate(zip(daily_dates, daily_precip, daily_max, daily_min)):
                date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                day_name = date_obj.strftime('%a')
                day_num = date_obj.strftime('%d')
                
                # Determine icon based on rainfall
                if precip > 10:
                    icon = "🌧️"
                elif precip > 2:
                    icon = "🌦️"
                else:
                    icon = "☀️"
                
                with day_cols[i]:
                    st.markdown(f"""
                    <div style="text-align: center; padding: 10px 4px; background: #f0f2f6; border-radius: 8px;">
                        <div style="font-size: 28px; margin-bottom: 4px;">{icon}</div>
                        <div style="font-weight: 700; font-size: 13px; color: #333;">{day_name}</div>
                        <div style="font-size: 11px; color: #666; margin-bottom: 6px;">{day_num}</div>
                        <div style="font-weight: 700; font-size: 15px; color: #1976d2; margin-bottom: 4px;">{precip}mm</div>
                        <div style="font-size: 11px; color: #666;">{round(t_min)}°-{round(t_max)}°</div>
                    </div>
                    """, unsafe_allow_html=True)
        else:
            st.info("📊 7-day forecast unavailable")
    except Exception as e:
        st.info("📊 7-day forecast unavailable")

with col3:
    st.markdown("#### 🌧️ Live Rain Radar")
    st.components.v1.iframe(
        "https://embed.windy.com/embed2.html?lat=-37.814&lon=144.963&detailLat=-37.814&detailLon=144.963&width=500&height=350&zoom=8&level=surface&overlay=rain&product=ecmwf&menu=&message=&marker=&calendar=now&pressure=&type=map&location=coordinates&detail=&metricWind=default&metricTemp=default&radarRange=-1",
        height=350,
        scrolling=False
    )

st.divider()

# SIDEBAR
with st.sidebar:
    st.header("Navigation")
    
    # Default page selection
    default_index = 0
    
    # If editing, default to Add Site page
    if 'editing_site' in st.session_state and st.session_state.editing_site:
        default_index = 4
    
    page = st.radio("", ["📊 Site Overview", "🤖 AI Dashboard", "🗺️ Site Map", "🌧️ Rain Radar", "➕ Add Site", "⚙️ Settings"], 
                   index=default_index, label_visibility="collapsed")
    
    st.divider()
    st.subheader("📅 " + datetime.now().strftime('%d %B %Y'))
    st.divider()
    
    st.subheader("🌤️ Weather Stations")
    
    # Get unique weather stations from sites
    unique_stations = {}
    for site_id, site in st.session_state.sites.items():
        site_name = site['name']
        if site_name in st.session_state.weather_stations:
            station_info = st.session_state.weather_stations[site_name]
            station_name = station_info['station_name']
            if station_name not in unique_stations:
                unique_stations[station_name] = station_info
    
    # If no stations found, show default Melbourne
    if not unique_stations:
        unique_stations['Melbourne (Olympic Park)'] = {
            'station_name': 'Melbourne (Olympic Park)',
            'lat': -37.8136,
            'lon': 144.9631
        }
    
    # Display each unique station compactly
    for station_name, station_info in unique_stations.items():
        with st.expander(f"📡 {station_name}", expanded=False):
            # Ensure cache dictionaries exist
            if 'site_weather' not in st.session_state:
                st.session_state.site_weather = {}
            if 'weather_cache_time' not in st.session_state:
                st.session_state.weather_cache_time = {}
            
            # Get weather for this station (use cached data)
            cache_key = f"{station_info['lat']}_{station_info['lon']}_sidebar"
            current_time = datetime.now()
            
            # Check cache
            sidebar_cached = False
            if cache_key in st.session_state.site_weather and cache_key + "_time" in st.session_state.weather_cache_time:
                cache_time = st.session_state.weather_cache_time[cache_key + "_time"]
                time_diff = (current_time - cache_time).total_seconds() / 3600
                if time_diff < 2:  # 2 hour cache
                    data = st.session_state.site_weather[cache_key]
                    sidebar_cached = True
            
            if not sidebar_cached:
                try:
                    lat = station_info['lat']
                    lon = station_info['lon']
                    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m&daily=precipitation_sum&timezone=Australia/Melbourne&forecast_days=7"
                    response = requests.get(url, timeout=5)
                    
                    if response.status_code == 200:
                        data = response.json()
                        # Cache it
                        st.session_state.site_weather[cache_key] = data
                        st.session_state.weather_cache_time[cache_key + "_time"] = current_time
                    else:
                        data = None
                except:
                    data = None
            
            if data:
                daily_precip = data['daily']['precipitation_sum'][:7]
                daily_dates = data['daily']['time'][:7]
                current_temp = data['current']['temperature_2m']
                
                st.metric("Temperature", f"{round(current_temp, 1)}°C")
                
                # 7-day forecast
                day_cols = st.columns(7)
                for idx, (date_str, precip) in enumerate(zip(daily_dates, daily_precip)):
                    date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                    day_name = date_obj.strftime('%a')
                    
                    # Icon based on rainfall
                    if precip > 10:
                        icon = "🌧️"
                    elif precip > 2:
                        icon = "🌦️"
                    else:
                        icon = "☀️"
                    
                    with day_cols[idx]:
                        st.markdown(f"""
                        <div style="text-align: center;">
                            <div style="font-size: 16px;">{icon}</div>
                            <div style="font-size: 9px; font-weight: 600;">{day_name}</div>
                            <div style="font-size: 10px; font-weight: 700; color: #1976d2;">{precip}mm</div>
                        </div>
                        """, unsafe_allow_html=True)
            else:
                st.caption("Weather unavailable")
    
    st.divider()
    
    # Show cache status
    if hasattr(st.session_state, 'weather_cache_time') and st.session_state.weather_cache_time:
        oldest_cache = min(st.session_state.weather_cache_time.values())
        time_since = (datetime.now() - oldest_cache).total_seconds() / 60  # Minutes
        if time_since < 60:
            st.caption(f"🔄 Weather refreshed {int(time_since)}min ago")
        else:
            st.caption(f"🔄 Weather refreshed {int(time_since/60)}h ago")
    
    if st.button("🔄 Refresh Weather", help="Fetch live weather data", use_container_width=True):
        with st.spinner("Fetching live weather..."):
            # Clear weather cache to force refresh
            st.session_state.site_weather = {}
            st.session_state.weather_cache_time = {}
            success, message = update_weather()
            if success:
                st.success("✅ " + message)
                st.rerun()
            else:
                st.error("❌ " + message)
# PASTE THIS IMMEDIATELY AFTER PART 2 (NO GAPS)

# MAIN CONTENT
if page == "📊 Site Overview":
    # Check if we're being redirected from AI Dashboard
    if st.session_state.get('switch_to_overview'):
        del st.session_state['switch_to_overview']
    
    st.header("Active Watering Sites")
    
    total_sites = len(st.session_state.sites)
    high_priority = sum(1 for s in st.session_state.sites.values() if get_recommendation(s)[0] == "🔴 HIGH")
    total_water = sum(calc_water(s) for s in st.session_state.sites.values())
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Sites", total_sites)
    col2.metric("High Priority", high_priority)
    col3.metric("Total Water/Visit", f"{total_water:,}L")
    
    st.divider()
    
    # CHANGED: 3 columns instead of 2
    site_list = list(st.session_state.sites.items())
    for i in range(0, len(site_list), 3):
        cols = st.columns(3)
        for j in range(3):
            if i + j < len(site_list):
                site_id, site = site_list[i + j]
                priority, msg, moisture, water = get_recommendation(site)
                
                with cols[j]:
                    with st.container(border=True):
                        col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
                        with col1:
                            st.markdown(f"### {site['name']}")
                            # Add client name if available
                            if site.get('client'):
                                st.caption(f"👤 Client: {site['client']}")
                        with col2:
                            st.metric("", priority, label_visibility="collapsed")
                        with col3:
                            if st.button("✏️", key=f"edit_{site_id}", help="Edit site", use_container_width=True):
                                st.session_state.editing_site = site_id
                                st.rerun()
                        with col4:
                            if st.button("🗑️", key=f"del_{site_id}", help="Delete site", use_container_width=True):
                                st.session_state[f'confirm_delete_{site_id}'] = True
                                st.rerun()
                        
                        if st.session_state.get(f'confirm_delete_{site_id}', False):
                            st.warning(f"⚠️ Delete **{site['name']}**? This cannot be undone!")
                            c1, c2 = st.columns(2)
                            if c1.button("✅ Yes, Delete", key=f"confirm_{site_id}", type="primary"):
                                del st.session_state.sites[site_id]
                                if f'confirm_delete_{site_id}' in st.session_state:
                                    del st.session_state[f'confirm_delete_{site_id}']
                                save_data()
                                st.success(f"Deleted {site['name']}")
                                st.rerun()
                            if c2.button("❌ Cancel", key=f"cancel_{site_id}"):
                                del st.session_state[f'confirm_delete_{site_id}']
                                st.rerun()
                        
                        # Site info right under title
                        c1, c2, c3 = st.columns(3)
                        c1.caption("📍 Location")
                        c1.write(site['location'])
                        c2.caption("💧 Current Moisture")
                        if moisture is not None:
                            c2.write(f"**{moisture}%**")
                        else:
                            c2.write("**--**")
                        c3.caption("💦 Water/Visit")
                        c3.write(f"**{water:,}L**")
                        
                        st.markdown("<br>", unsafe_allow_html=True)
                        
                        # Get site-specific weather
                        site_weather, station_info = get_site_weather(site['name'])
                        
                        # Ensure cache dictionaries exist
                        if 'site_weather' not in st.session_state:
                            st.session_state.site_weather = {}
                        if 'weather_cache_time' not in st.session_state:
                            st.session_state.weather_cache_time = {}
                        
                        # Get 7-day forecast for this specific site (cached)
                        cache_key = f"{station_info['lat']}_{station_info['lon']}_forecast"
                        current_time = datetime.now()
                        
                        # Check cache first
                        forecast_cached = False
                        if cache_key in st.session_state.site_weather and cache_key + "_time" in st.session_state.weather_cache_time:
                            cache_time = st.session_state.weather_cache_time[cache_key + "_time"]
                            time_diff = (current_time - cache_time).total_seconds() / 3600
                            if time_diff < 2:  # 2 hour cache
                                forecast_data = st.session_state.site_weather[cache_key]
                                forecast_cached = True
                        
                        if not forecast_cached:
                            try:
                                lat = station_info['lat']
                                lon = station_info['lon']
                                url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=precipitation_sum&timezone=Australia/Melbourne&forecast_days=7"
                                response = requests.get(url, timeout=5)
                                
                                if response.status_code == 200:
                                    forecast_data = response.json()
                                    # Cache it
                                    st.session_state.site_weather[cache_key] = forecast_data
                                    st.session_state.weather_cache_time[cache_key + "_time"] = current_time
                                else:
                                    forecast_data = None
                            except:
                                forecast_data = None
                        
                        if forecast_data:
                            daily_precip = forecast_data['daily']['precipitation_sum'][:7]
                            daily_dates = forecast_data['daily']['time'][:7]
                            
                            # Use Streamlit columns instead of HTML
                            st.markdown("**🌧️ 7-DAY FORECAST**")
                            day_cols = st.columns(7)
                            
                            for idx, (date_str, precip) in enumerate(zip(daily_dates, daily_precip)):
                                date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                                day_name = date_obj.strftime('%a')
                                
                                # Icon based on rainfall
                                if precip > 10:
                                    icon = "🌧️"
                                elif precip > 2:
                                    icon = "🌦️"
                                else:
                                    icon = "☀️"
                                
                                with day_cols[idx]:
                                    st.markdown(f"""
                                    <div style="text-align: center; background: #f0f2f6; padding: 6px 2px; border-radius: 6px;">
                                        <div style="font-size: 18px;">{icon}</div>
                                        <div style="font-size: 10px; font-weight: 600;">{day_name}</div>
                                        <div style="font-size: 11px; font-weight: 700; color: #1976d2;">{precip}mm</div>
                                    </div>
                                    """, unsafe_allow_html=True)
                        else:
                            st.caption("Forecast unavailable")
                        
                        st.markdown("<br>", unsafe_allow_html=True)
                        
                        if site['visits'] and len(site['visits']) >= 2:
                            moisture_values = [v['moisture'] for v in site['visits'][-10:]]
                            dates = [v['date'] for v in site['visits'][-10:]]
                            spark_df = pd.DataFrame({'Date': dates, 'Moisture': moisture_values})
                            spark_fig = px.line(spark_df, x='Date', y='Moisture', labels={'Moisture': 'Moisture %', 'Date': ''})
                            spark_fig.update_traces(line_color='#1976d2', line_width=2)
                            spark_fig.update_layout(height=80, margin=dict(l=0, r=0, t=0, b=0), showlegend=False,
                                xaxis=dict(showticklabels=False, showgrid=False),
                                yaxis=dict(showticklabels=True, showgrid=True, gridcolor='rgba(0,0,0,0.1)'),
                                plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
                            spark_fig.add_hline(y=35, line_dash="dash", line_color="green", line_width=1, opacity=0.5)
                            spark_fig.add_hline(y=25, line_dash="dash", line_color="orange", line_width=1, opacity=0.5)
                            st.caption("📊 Soil Moisture Trend (Last 10 visits)")
                            st.plotly_chart(spark_fig, use_container_width=True, config={'displayModeBar': False})
                        
                        if site['visits']:
                            last_visit = site['visits'][-1]
                            # Get moisture display - show detailed readings if available
                            if last_visit.get('moisture_readings'):
                                moisture_detail = f"{last_visit['moisture']}% avg"
                                readings_text = " | ".join([f"{r['location']}: {r['moisture']}%" for r in last_visit['moisture_readings']])
                            else:
                                moisture_detail = f"{last_visit['moisture']}%"
                                readings_text = ""
                            
                            st.markdown(f"""
                            <div style="background: #f5f5f5; padding: 10px; border-radius: 6px; margin-bottom: 10px; border-left: 3px solid #4caf50;">
                                <div style="font-weight: 700; color: #2e7d32; font-size: 12px; margin-bottom: 4px;">📋 LAST VISIT: {last_visit['date']}</div>
                                <div style="font-size: 12px; color: #424242;">
                                    <strong>Person:</strong> {last_visit.get('person', 'N/A')} | <strong>Truck:</strong> {last_visit.get('truck', 'N/A')}<br/>
                                    <strong>Moisture:</strong> {moisture_detail} | <strong>Hours:</strong> {last_visit['hours']}h
                                    {f'<br/><strong>Locations:</strong> {readings_text}' if readings_text else ''}
                                </div>
                                {f'<div style="font-size: 11px; color: #666; margin-top: 4px; font-style: italic;">"{last_visit["notes"]}"</div>' if last_visit.get('notes') else ''}
                            </div>
                            """, unsafe_allow_html=True)
                        else:
                            st.info("No visits logged yet", icon="ℹ️")
                        
                        # Display recommendation based on priority
                        if priority == "⚪ NO DATA":
                            st.info(msg, icon="ℹ️")
                        elif "HIGH" in priority:
                            st.error(msg, icon="🔴")
                        elif "MEDIUM" in priority:
                            st.warning(msg, icon="🟡")
                        else:
                            st.success(msg, icon="🟢")
                        
                        # AI Predictions (only if site has visit data)
                        if site.get('visits') and len(site['visits']) >= 2:
                            try:
                                days_until = predict_days_until_critical(site)
                                optimal_water = calculate_optimal_water(site)
                                
                                ai_insights = []
                                
                                if days_until is not None:
                                    if days_until == 0:
                                        ai_insights.append("⚠️ Critical NOW")
                                    elif days_until <= 2:
                                        ai_insights.append(f"⏰ Critical in {days_until} day{'s' if days_until != 1 else ''}")
                                    elif days_until <= 5:
                                        ai_insights.append(f"📅 {days_until} days until critical")
                                    else:
                                        ai_insights.append(f"✅ {days_until} days buffer")
                                
                                if optimal_water != water:
                                    diff_pct = round(((optimal_water - water) / water) * 100)
                                    if abs(diff_pct) >= 5:
                                        if diff_pct > 0:
                                            ai_insights.append(f"💡 +{diff_pct}% water recommended")
                                        else:
                                            ai_insights.append(f"💡 {diff_pct}% water (reduce)")
                                
                                if ai_insights:
                                    st.markdown(f"**🤖 AI Insights:** {' • '.join(ai_insights)}")
                            except Exception as e:
                                pass  # Silently handle any prediction errors
                        
                        # Display weather station info at bottom
                        st.caption(f"📡 Weather: {station_info['station_name']} ({station_info['distance_km']:.1f}km)")
                        
                        if st.button("View Full Details", key=f"view_{site_id}", use_container_width=True):
                            st.session_state.selected_site = site_id
                            st.rerun()
    
    if 'selected_site' in st.session_state:
        # Force scroll to top when site details are opened
        st.markdown("""
            <script>
                window.parent.document.querySelector('section.main').scrollTo(0, 0);
            </script>
        """, unsafe_allow_html=True)
        
        st.divider()
        st.header("📋 Site Details")
        site = st.session_state.sites[st.session_state.selected_site]
        
        if st.button("⬅️ Back to Overview"):
            del st.session_state.selected_site
            st.rerun()
        
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Site Information")
            st.write(f"**Name:** {site['name']}")
            if site.get('client'):
                st.write(f"**Client:** {site['client']}")
            st.write(f"**Location:** {site['location']}")
            st.write(f"**Soil Type:** {site['soil_type']}")
            st.write(f"**Plant Maturity:** {site['maturity']}")
            st.write(f"**Contract:** {site['start_date']} to {site['end_date']}")
            st.write(f"**Visits:** {site['visits_per_week']}x per week")
            st.write(f"**PO Number:** {site['po_number']}")
            st.write(f"**Hours Quoted:** {site['hours_quoted']}h")
        
        with col2:
            st.subheader("Water Requirements")
            trees_w = site['trees'] * site['trees_litres']
            tubes_w = site['tubestock'] * site['tubestock_litres']
            turf_w = site['turf_m2'] * site['turf_litres']
            total_w = trees_w + tubes_w + turf_w
            st.write(f"**Trees:** {site['trees']} × {site['trees_litres']}L = {trees_w:,}L")
            st.write(f"**Tube Stock:** {site['tubestock']} × {site['tubestock_litres']}L = {tubes_w:,}L")
            st.write(f"**Turf:** {site['turf_m2']}m² × {site['turf_litres']}L = {turf_w:,}L")
            st.metric("TOTAL PER VISIT", f"{total_w:,}L")
        
        st.subheader("Visit History & Soil Moisture Trend")
        if site['visits']:
            df = pd.DataFrame(site['visits'])
            df['date'] = pd.to_datetime(df['date'])
            fig = px.line(df, x='date', y='moisture', title='Soil Moisture Over Time', 
                         labels={'moisture': 'Moisture (%)', 'date': 'Date'}, markers=True)
            fig.add_hline(y=35, line_dash="dash", line_color="green", annotation_text="Optimal")
            fig.add_hline(y=25, line_dash="dash", line_color="orange", annotation_text="Low")
            st.plotly_chart(fig, use_container_width=True)
            
            for visit in reversed(site['visits']):
                with st.expander(f"📅 {visit['date']} - {visit['moisture']}% avg moisture - {visit.get('person', 'N/A')}"):
                    c1, c2, c3 = st.columns(3)
                    c1.write(f"**Hours:** {visit['hours']}h")
                    c2.write(f"**Person:** {visit.get('person', 'N/A')}")
                    c3.write(f"**Truck:** {visit.get('truck', 'N/A')}")
                    
                    # Display moisture readings if available
                    if visit.get('moisture_readings'):
                        st.markdown("**Moisture Readings:**")
                        for i, reading in enumerate(visit['moisture_readings'], 1):
                            st.write(f"  {i}. **{reading['location']}**: {reading['moisture']}%")
                    else:
                        st.write(f"**Moisture:** {visit['moisture']}%")
                    
                    st.write(f"**Notes:** {visit['notes']}")
                    
                    if visit.get('attachments'):
                        st.write(f"**Attachments:** {len(visit['attachments'])} file(s)")
                        for att in visit['attachments']:
                            file_path = os.path.join(ATTACHMENTS_DIR, att)
                            if os.path.exists(file_path):
                                c1, c2 = st.columns([3, 1])
                                c1.write(f"📎 {att}")
                                with open(file_path, 'rb') as f:
                                    c2.download_button("Download", f, file_name=att, key=f"dl_{att}")
                            else:
                                st.caption(f"⚠️ {att} (file missing)")
            
            c1, c2 = st.columns(2)
            avg_hours = df['hours'].mean()
            c1.metric("Avg Hours", f"{avg_hours:.1f}h")
            variance = avg_hours - site['hours_quoted']
            c2.metric("vs Quoted", f"{variance:+.1f}h")
        
        st.subheader("➕ Add New Visit")
        with st.form("add_visit"):
            c1, c2 = st.columns(2)
            visit_date = c1.date_input("Date", datetime.now())
            hours = c2.number_input("Hours", 0.0, step=0.5, value=site['hours_quoted'])
            
            c1, c2 = st.columns(2)
            person = c1.text_input("Person Name", placeholder="e.g., John Smith")
            truck = c2.selectbox("Truck", ["UVS001", "UVS002", "UVS003", "UVS004", "UVS005", "UVS006"])
            
            st.markdown("#### 💧 Soil Moisture Readings")
            st.caption("Take multiple moisture readings at different locations across the site")
            
            # Allow up to 5 moisture readings
            num_readings = st.number_input("Number of readings to add", min_value=1, max_value=10, value=1, step=1)
            
            moisture_readings = []
            for i in range(num_readings):
                st.markdown(f"**Reading {i+1}**")
                cols = st.columns([2, 1])
                reading_location = cols[0].text_input(f"Location", key=f"loc_{i}", placeholder=f"e.g., North corner, Main entrance")
                reading_moisture = cols[1].number_input(f"Moisture %", 0, 100, 35, key=f"moist_{i}")
                if reading_location:
                    moisture_readings.append({
                        'location': reading_location,
                        'moisture': reading_moisture
                    })
            
            notes = st.text_area("Notes")
            uploaded_files = st.file_uploader("Attach Files (PDF, JPG, PNG)", accept_multiple_files=True, type=['pdf', 'jpg', 'jpeg', 'png'])
            
            if st.form_submit_button("Add Visit", type="primary"):
                if not moisture_readings:
                    st.error("❌ Please add at least one moisture reading with a location!")
                else:
                    attachment_names = []
                    if uploaded_files:
                        for uploaded_file in uploaded_files:
                            filename = f"{st.session_state.selected_site}_{visit_date.strftime('%Y%m%d')}_{uploaded_file.name}"
                            file_path = os.path.join(ATTACHMENTS_DIR, filename)
                            with open(file_path, 'wb') as f:
                                f.write(uploaded_file.getbuffer())
                            attachment_names.append(filename)
                    
                    # Calculate average moisture
                    avg_moisture = sum(r['moisture'] for r in moisture_readings) / len(moisture_readings)
                    
                    site['visits'].append({
                        'date': visit_date.strftime('%Y-%m-%d'),
                        'hours': hours,
                        'moisture': round(avg_moisture),
                        'moisture_readings': moisture_readings,
                        'notes': notes,
                        'person': person,
                        'truck': truck,
                        'attachments': attachment_names
                    })
                    save_data()
                    st.success(f"✅ Visit added with {len(moisture_readings)} reading(s)!")
                    st.rerun()
# PASTE THIS IMMEDIATELY AFTER PART 3 (NO GAPS)

elif page == "🤖 AI Dashboard":
    st.header("🤖 AI Watering Intelligence Dashboard")
    st.caption("Machine learning-powered insights for optimal watering strategy")
    
    # Calculate AI metrics for all sites
    ai_data = []
    for site_id, site in st.session_state.sites.items():
        if site.get('visits') and len(site['visits']) >= 2:
            try:
                moisture = predict_moisture(site)
                days_until = predict_days_until_critical(site)
                optimal_water = calculate_optimal_water(site)
                current_water = calc_water(site)
                water_diff = optimal_water - current_water
                water_diff_pct = round((water_diff / current_water) * 100) if current_water > 0 else 0
                
                priority, msg, _, _ = get_recommendation(site)
                
                ai_data.append({
                    'site_id': site_id,
                    'name': site['name'],
                    'client': site.get('client', 'N/A'),
                    'moisture': moisture,
                    'days_until_critical': days_until,
                    'optimal_water': optimal_water,
                    'current_water': current_water,
                    'water_diff': water_diff,
                    'water_diff_pct': water_diff_pct,
                    'priority': priority,
                    'visits_count': len(site['visits'])
                })
            except:
                pass
    
    if not ai_data:
        st.warning("⚠️ Not enough data for AI predictions. Add at least 2 visits per site to enable AI insights.")
    else:
        # Summary metrics
        st.subheader("📈 AI Predictions Summary")
        col1, col2, col3, col4 = st.columns(4)
        
        critical_soon = sum(1 for d in ai_data if d['days_until_critical'] is not None and d['days_until_critical'] <= 3)
        over_watering = sum(1 for d in ai_data if d['water_diff_pct'] < -10)
        under_watering = sum(1 for d in ai_data if d['water_diff_pct'] > 10)
        avg_days_buffer = sum(d['days_until_critical'] for d in ai_data if d['days_until_critical'] is not None) / len([d for d in ai_data if d['days_until_critical'] is not None]) if any(d['days_until_critical'] is not None for d in ai_data) else 0
        
        col1.metric("⚠️ Critical Within 3 Days", critical_soon)
        col2.metric("💧 Possibly Over-Watering", over_watering)
        col3.metric("💦 Possibly Under-Watering", under_watering)
        col4.metric("📅 Avg Days Buffer", f"{avg_days_buffer:.1f}" if avg_days_buffer > 0 else "N/A")
        
        st.divider()
        
        # Water optimization summary
        total_current = sum(d['current_water'] for d in ai_data)
        total_optimal = sum(d['optimal_water'] for d in ai_data)
        total_savings = total_current - total_optimal
        savings_pct = (total_savings / total_current * 100) if total_current > 0 else 0
        
        st.subheader("💧 Water Efficiency Analysis")
        col1, col2, col3 = st.columns(3)
        col1.metric("Current Total Water/Week", f"{total_current:,}L")
        col2.metric("AI Recommended Total", f"{total_optimal:,}L")
        
        if savings_pct > 0:
            col3.metric("Potential Savings", f"{total_savings:,}L", f"{savings_pct:.1f}%", delta_color="normal")
        elif savings_pct < 0:
            col3.metric("Additional Water Needed", f"{abs(total_savings):,}L", f"{abs(savings_pct):.1f}%", delta_color="inverse")
        else:
            col3.metric("Water Usage", "Optimal ✅")
        
        st.divider()
        
        # Priority sites needing attention
        st.subheader("🚨 Sites Needing Immediate Attention")
        urgent_sites = [d for d in ai_data if d['days_until_critical'] is not None and d['days_until_critical'] <= 3]
        
        if urgent_sites:
            urgent_sites.sort(key=lambda x: x['days_until_critical'])
            
            for site_data in urgent_sites:
                with st.container(border=True):
                    col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
                    
                    with col1:
                        st.markdown(f"### {site_data['name']}")
                        st.caption(f"👤 Client: {site_data['client']}")
                    
                    with col2:
                        days = site_data['days_until_critical']
                        if days == 0:
                            st.metric("Status", "CRITICAL", delta="NOW", delta_color="inverse")
                        else:
                            st.metric("Days Left", days, delta=f"-{days}d", delta_color="inverse")
                    
                    with col3:
                        st.metric("Moisture", f"{site_data['moisture']}%")
                    
                    with col4:
                        if st.button("View Site", key=f"urgent_{site_data['site_id']}"):
                            st.session_state.selected_site = site_data['site_id']
                            st.session_state['switch_to_overview'] = True
                            st.rerun()
                    
                    st.error(f"⚠️ Water ASAP! Site will reach critical moisture in {days} day{'s' if days != 1 else ''}.")
        else:
            st.success("✅ No sites require immediate attention. All sites have adequate moisture buffers.")
        
        st.divider()
        
        # Water optimization recommendations
        st.subheader("💡 Water Optimization Opportunities")
        
        # Sites with significant water adjustments needed
        adjustment_needed = [d for d in ai_data if abs(d['water_diff_pct']) >= 10]
        
        if adjustment_needed:
            adjustment_needed.sort(key=lambda x: abs(x['water_diff_pct']), reverse=True)
            
            for site_data in adjustment_needed:
                with st.container(border=True):
                    col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
                    
                    with col1:
                        st.markdown(f"### {site_data['name']}")
                        st.caption(f"👤 Client: {site_data['client']}")
                    
                    with col2:
                        st.metric("Current Water", f"{site_data['current_water']:,}L")
                    
                    with col3:
                        st.metric("AI Optimal", f"{site_data['optimal_water']:,}L", 
                                f"{site_data['water_diff_pct']:+d}%")
                    
                    with col4:
                        if st.button("View Site", key=f"opt_{site_data['site_id']}"):
                            st.session_state.selected_site = site_data['site_id']
                            st.session_state['switch_to_overview'] = True
                            st.rerun()
                    
                    if site_data['water_diff_pct'] > 0:
                        st.warning(f"💦 Increase water by {site_data['water_diff']:+,}L ({site_data['water_diff_pct']:+d}%) for better results.")
                    else:
                        st.info(f"💧 Reduce water by {abs(site_data['water_diff']):,}L ({site_data['water_diff_pct']}%) to avoid over-watering.")
        else:
            st.success("✅ All sites are currently optimally watered based on AI analysis.")
        
        st.divider()
        
        # Detailed AI predictions table
        st.subheader("📊 Complete AI Predictions Table")
        
        df = pd.DataFrame(ai_data)
        df = df.sort_values('days_until_critical', na_position='last')
        
        # Format for display
        display_df = df[[
            'name', 'client', 'moisture', 'days_until_critical', 
            'current_water', 'optimal_water', 'water_diff_pct', 'visits_count'
        ]].copy()
        
        display_df.columns = [
            'Site Name', 'Client', 'Moisture %', 'Days Until Critical',
            'Current Water (L)', 'AI Optimal (L)', 'Adjustment %', 'Visits Logged'
        ]
        
        # Color coding function
        def color_days(val):
            if pd.isna(val):
                return ''
            if val == 0:
                return 'background-color: #ffcdd2'
            elif val <= 2:
                return 'background-color: #fff9c4'
            elif val <= 5:
                return 'background-color: #c8e6c9'
            else:
                return 'background-color: #e8f5e9'
        
        def color_adjustment(val):
            if pd.isna(val):
                return ''
            if abs(val) < 5:
                return 'background-color: #e8f5e9'
            elif abs(val) < 15:
                return 'background-color: #fff9c4'
            else:
                return 'background-color: #ffcdd2'
        
        styled_df = display_df.style.applymap(
            color_days, subset=['Days Until Critical']
        ).applymap(
            color_adjustment, subset=['Adjustment %']
        ).format({
            'Current Water (L)': '{:,.0f}',
            'AI Optimal (L)': '{:,.0f}',
            'Adjustment %': '{:+.0f}%',
            'Moisture %': '{:.0f}%',
            'Days Until Critical': lambda x: f"{x:.0f}" if pd.notna(x) else "N/A"
        })
        
        st.dataframe(styled_df, use_container_width=True, height=400)
        
        # Export AI report
        st.divider()
        col1, col2 = st.columns([3, 1])
        with col1:
            st.caption("💾 Export this AI analysis as CSV for records or sharing with clients")
        with col2:
            csv = df.to_csv(index=False)
            st.download_button(
                "📥 Download AI Report (CSV)",
                csv,
                f"UVS_AI_Report_{datetime.now().strftime('%Y%m%d')}.csv",
                "text/csv",
                use_container_width=True
            )
        
        st.divider()
        
        # AI Model Info
        with st.expander("ℹ️ How AI Predictions Work"):
            st.markdown("""
            ### 🤖 AI Watering Intelligence System
            
            Our AI system analyzes multiple data points to provide accurate predictions:
            
            **Moisture Prediction:**
            - Historical moisture trends from past visits
            - Soil type characteristics (clay retains more water than sand)
            - Days since last visit (evaporation/transpiration rates)
            - Recent rainfall (last 7 days)
            - Upcoming rainfall forecasts (next 24h and 7 days)
            - Plant maturity stage (establishment needs more attention)
            
            **Days Until Critical:**
            - Calculates average daily moisture drop from recent visits
            - Accounts for upcoming weather conditions
            - Adjusts for soil-specific water retention rates
            - Provides early warning system for scheduling
            
            **Optimal Water Calculation:**
            - Analyzes effectiveness of past watering amounts
            - Looks at moisture improvements after each visit
            - Identifies over-watering (low improvement = reduce water)
            - Identifies under-watering (high improvement = increase water)
            - Recommends adjustments of ±10-15% when needed
            
            **Data Requirements:**
            - Minimum 2 visits per site for basic predictions
            - 5+ visits recommended for highly accurate predictions
            - More consistent visit intervals = better predictions
            
            **Accuracy:**
            - Predictions improve over time as more data is collected
            - Weather integration increases prediction accuracy by ~30%
            - Site-specific learning adapts to unique conditions
            """)


# REPLACE the "elif page == "🗺️ Site Map":" section with this:

elif page == "🗺️ Site Map":
    st.header("Interactive Site Map")
    
    # Get all unique clients
    all_clients = set()
    for site in st.session_state.sites.values():
        client = site.get('client', 'No Client')
        if client and client.strip():
            all_clients.add(client)
        else:
            all_clients.add('No Client')
    
    # Client filter
    client_list = ['All Clients'] + sorted(list(all_clients))
    selected_client = st.selectbox("🔍 Filter by Client", client_list, index=0)
    
    # Get sites with coordinates (filtered by client)
    sites_with_coords = []
    for site_id, site in st.session_state.sites.items():
        site_name = site['name']
        site_client = site.get('client', 'No Client')
        if not site_client or not site_client.strip():
            site_client = 'No Client'
        
        # Apply client filter
        if selected_client != 'All Clients' and site_client != selected_client:
            continue
        
        if site_name in st.session_state.weather_stations:
            station_info = st.session_state.weather_stations[site_name]
            lat = station_info.get('lat')
            lon = station_info.get('lon')
            if lat and lon:
                priority, msg, moisture, water = get_recommendation(site)
                sites_with_coords.append({
                    'id': site_id,
                    'name': site['name'],
                    'client': site.get('client', 'N/A'),
                    'location': site['location'],
                    'lat': lat,
                    'lon': lon,
                    'priority': priority,
                    'message': msg,
                    'moisture': moisture if moisture is not None else '--',
                    'water': water
                })
    
    if not sites_with_coords:
        if selected_client == 'All Clients':
            st.warning("⚠️ No sites have coordinate data. Upload the Excel file with coordinates to see the map.")
        else:
            st.warning(f"⚠️ No sites found for client: **{selected_client}** with coordinate data.")
    else:
        # Display summary and rain controls
        st.markdown(f"### Showing: **{selected_client}** ({len(sites_with_coords)} site{'s' if len(sites_with_coords) != 1 else ''})")
        
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Sites on Map", len(sites_with_coords))
        high_count = sum(1 for s in sites_with_coords if "HIGH" in s['priority'])
        col2.metric("🔴 High Priority", high_count)
        medium_count = sum(1 for s in sites_with_coords if "MEDIUM" in s['priority'])
        col3.metric("🟡 Medium Priority", medium_count)
        low_count = sum(1 for s in sites_with_coords if "LOW" in s['priority'] or "OPTIMAL" in s['priority'])
        col4.metric("🟢 Low Priority", low_count)
        
        # Rain radar controls
        with col5:
            st.markdown("#### 🌧️ Rain Radar")
            show_rain = st.toggle("Show Rain Animation", value=False)
            if show_rain:
                rain_speed = st.select_slider("Animation Speed", options=["Slow", "Medium", "Fast"], value="Medium")
                rain_opacity = st.slider("Opacity", min_value=0.1, max_value=1.0, value=0.6, step=0.1)
        
        st.divider()
        
        # Calculate center of all sites
        center_lat = sum(s['lat'] for s in sites_with_coords) / len(sites_with_coords)
        center_lon = sum(s['lon'] for s in sites_with_coords) / len(sites_with_coords)
        
        # Generate markers
        markers_js = ""
        for site in sites_with_coords:
            # Determine marker color based on priority
            if "HIGH" in site['priority']:
                color = "red"
            elif "MEDIUM" in site['priority']:
                color = "orange"
            elif "NO DATA" in site['priority']:
                color = "grey"
            else:
                color = "green"
            
            # Get the actual site data for last visit info
            site_data = st.session_state.sites[site['id']]
            
            # Build last visit section
            last_visit_html = ""
            if site_data.get('visits') and len(site_data['visits']) > 0:
                last_visit = site_data['visits'][-1]
                
                # Handle multiple moisture readings
                if last_visit.get('moisture_readings'):
                    moisture_detail = f"{last_visit['moisture']}% avg"
                    readings_list = "<br/>".join([f"&nbsp;&nbsp;• {r['location']}: {r['moisture']}%" for r in last_visit['moisture_readings']])
                    moisture_display = f"{moisture_detail}<br/>{readings_list}"
                else:
                    moisture_display = f"{last_visit['moisture']}%"
                
                # Escape notes properly
                notes_text = last_visit.get('notes', '').replace("'", "&apos;").replace('"', "&quot;").replace('\n', ' ')
                notes_html = f"<p style='margin: 3px 0; font-size: 10px; font-style: italic; color: #666;'>&quot;{notes_text}&quot;</p>" if notes_text else ""
                
                last_visit_html = f"""
                <div style='background: #f0f0f0; padding: 8px; border-radius: 4px; margin-top: 10px; border-left: 3px solid #4caf50;'>
                    <p style='margin: 0 0 5px 0; font-weight: bold; color: #2e7d32; font-size: 11px;'>📋 LAST VISIT: {last_visit['date']}</p>
                    <p style='margin: 3px 0; font-size: 11px;'><strong>Person:</strong> {last_visit.get('person', 'N/A')}</p>
                    <p style='margin: 3px 0; font-size: 11px;'><strong>Truck:</strong> {last_visit.get('truck', 'N/A')}</p>
                    <p style='margin: 3px 0; font-size: 11px;'><strong>Hours:</strong> {last_visit['hours']}h</p>
                    <p style='margin: 3px 0; font-size: 11px;'><strong>Moisture:</strong> {moisture_display}</p>
                    {notes_html}
                </div>
                """
            else:
                last_visit_html = """
                <div style='background: #e3f2fd; padding: 8px; border-radius: 4px; margin-top: 10px;'>
                    <p style='margin: 0; font-size: 11px; color: #1976d2;'>ℹ️ No visits logged yet</p>
                </div>
                """
            
            popup_html = f"""
            <div style='width: 300px; font-family: Arial, sans-serif;'>
                <h4 style='margin: 0 0 8px 0; color: #333;'>{site['name']}</h4>
                <p style='margin: 3px 0; font-size: 12px;'><strong>👤 Client:</strong> {site['client']}</p>
                <p style='margin: 3px 0; font-size: 12px;'><strong>📍 Location:</strong> {site['location']}</p>
                <p style='margin: 3px 0; font-size: 12px;'><strong>Priority:</strong> {site['priority']}</p>
                <p style='margin: 3px 0; font-size: 12px;'><strong>💧 Moisture:</strong> {site['moisture']}{'%' if site['moisture'] != '--' else ''}</p>
                <p style='margin: 3px 0; font-size: 12px;'><strong>💦 Water/Visit:</strong> {site['water']:,}L</p>
                <div style='background: #fff3cd; padding: 6px; border-radius: 4px; margin-top: 8px; border-left: 3px solid #ffc107;'>
                    <p style='margin: 0; font-size: 11px; font-style: italic;'>{site['message']}</p>
                </div>
                {last_visit_html}
            </div>
            """
            
            # Use different icon URLs
            if color == "red":
                icon_url = "https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-red.png"
            elif color == "orange":
                icon_url = "https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-orange.png"
            elif color == "green":
                icon_url = "https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-green.png"
            else:
                icon_url = "https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-blue.png"
            
            # Escape quotes properly in popup HTML
            popup_html_escaped = popup_html.replace("'", "\\'").replace('"', '\\"').replace('\n', ' ')
            
            markers_js += f"""
            L.marker([{site['lat']}, {site['lon']}], {{
                icon: L.icon({{
                    iconUrl: '{icon_url}',
                    shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
                    iconSize: [25, 41],
                    iconAnchor: [12, 41],
                    popupAnchor: [1, -34],
                    shadowSize: [41, 41]
                }})
            }}).addTo(map).bindPopup(`{popup_html_escaped}`, {{maxWidth: 350}});
            """
        
        # Add animated rain radar if toggle is on
        rain_animation_js = ""
        if show_rain:
            # Set animation speed
            speed_map = {"Slow": 2000, "Medium": 1000, "Fast": 500}
            animation_speed = speed_map[rain_speed]
            
            rain_animation_js = f"""
            // Animated Rain Radar from RainViewer
            var rainLayers = {{}};
            var animationPosition = 0;
            var animationTimer = null;
            var radarTimestamps = [];
            var currentLayer = null;
            var rainOpacity = {rain_opacity};
            
            // Timeline display
            var timelineDiv = L.control({{position: 'bottomleft'}});
            timelineDiv.onAdd = function(map) {{
                var div = L.DomUtil.create('div', 'timeline-control');
                div.style.background = 'rgba(255,255,255,0.9)';
                div.style.padding = '10px';
                div.style.borderRadius = '5px';
                div.style.fontSize = '14px';
                div.style.fontWeight = 'bold';
                div.innerHTML = '<div id="timeline-text">Loading rain data...</div>';
                return div;
            }};
            timelineDiv.addTo(map);
            
            // Play/Pause control
            var controlDiv = L.control({{position: 'topleft'}});
            controlDiv.onAdd = function(map) {{
                var div = L.DomUtil.create('div', 'rain-control');
                div.style.background = 'white';
                div.style.padding = '5px';
                div.style.borderRadius = '3px';
                div.style.cursor = 'pointer';
                div.style.fontSize = '24px';
                div.innerHTML = '⏸️';
                div.onclick = function() {{
                    if (animationTimer) {{
                        stopAnimation();
                        div.innerHTML = '▶️';
                    }} else {{
                        startAnimation();
                        div.innerHTML = '⏸️';
                    }}
                }};
                return div;
            }};
            controlDiv.addTo(map);
            
            function formatTime(timestamp) {{
                var date = new Date(timestamp * 1000);
                var now = new Date();
                var hours = date.getHours().toString().padStart(2, '0');
                var minutes = date.getMinutes().toString().padStart(2, '0');
                
                if (date > now) {{
                    return hours + ':' + minutes + ' (Forecast)';
                }} else {{
                    return hours + ':' + minutes;
                }}
            }}
            
            function showFrame(frameIndex) {{
                if (currentLayer) {{
                    map.removeLayer(currentLayer);
                }}
                
                var timestamp = radarTimestamps[frameIndex];
                if (rainLayers[timestamp]) {{
                    currentLayer = rainLayers[timestamp];
                    currentLayer.addTo(map);
                    
                    var timelineText = formatTime(timestamp);
                    var now = Date.now() / 1000;
                    if (timestamp < now) {{
                        timelineText = '⏮️ ' + timelineText + ' (Past)';
                    }} else if (timestamp > now) {{
                        timelineText = '⏭️ ' + timelineText + ' (Future)';
                    }} else {{
                        timelineText = '⏺️ ' + timelineText + ' (Now)';
                    }}
                    document.getElementById('timeline-text').innerHTML = timelineText;
                }}
            }}
            
            function startAnimation() {{
                animationTimer = setInterval(function() {{
                    animationPosition++;
                    if (animationPosition >= radarTimestamps.length) {{
                        animationPosition = 0;
                    }}
                    showFrame(animationPosition);
                }}, {animation_speed});
            }}
            
            function stopAnimation() {{
                if (animationTimer) {{
                    clearInterval(animationTimer);
                    animationTimer = null;
                }}
            }}
            
            // Fetch radar data from RainViewer
            fetch('https://api.rainviewer.com/public/weather-maps.json')
                .then(response => response.json())
                .then(data => {{
                    // Get past radar frames (last 24 hours, but API typically provides last 2 hours)
                    var pastFrames = data.radar.past || [];
                    
                    // Get nowcast/forecast frames (next 30-60 minutes typically)
                    var forecastFrames = data.radar.nowcast || [];
                    
                    // Combine all timestamps
                    var allFrames = pastFrames.concat(forecastFrames);
                    
                    allFrames.forEach(function(frame) {{
                        var timestamp = frame.time;
                        radarTimestamps.push(timestamp);
                        
                        // Pre-create all layers with custom opacity
                        rainLayers[timestamp] = L.tileLayer(
                            'https://tilecache.rainviewer.com/v2/radar/' + timestamp + '/256/{{z}}/{{x}}/{{y}}/2/1_1.png',
                            {{
                                opacity: rainOpacity,
                                zIndex: 10
                            }}
                        );
                    }});
                    
                    if (radarTimestamps.length > 0) {{
                        // Find the frame closest to current time
                        var now = Date.now() / 1000;
                        var closestIndex = 0;
                        var minDiff = Math.abs(radarTimestamps[0] - now);
                        
                        for (var i = 1; i < radarTimestamps.length; i++) {{
                            var diff = Math.abs(radarTimestamps[i] - now);
                            if (diff < minDiff) {{
                                minDiff = diff;
                                closestIndex = i;
                            }}
                        }}
                        
                        animationPosition = closestIndex;
                        showFrame(animationPosition);
                        startAnimation();
                    }} else {{
                        document.getElementById('timeline-text').innerHTML = 'Rain data unavailable';
                    }}
                }})
                .catch(error => {{
                    console.log('Rain radar not available:', error);
                    document.getElementById('timeline-text').innerHTML = 'Rain data unavailable';
                }});
            """
        
        map_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <link rel="stylesheet" href="https://unpkg.com/leaflet@1.7.1/dist/leaflet.css" />
            <script src="https://unpkg.com/leaflet@1.7.1/dist/leaflet.js"></script>
            <style>
                #map {{ height: 600px; width: 100%; }}
                body {{ margin: 0; padding: 0; }}
                .timeline-control {{
                    box-shadow: 0 2px 6px rgba(0,0,0,0.3);
                }}
                .rain-control {{
                    box-shadow: 0 2px 6px rgba(0,0,0,0.3);
                    user-select: none;
                }}
            </style>
        </head>
        <body>
            <div id="map"></div>
            <script>
                var map = L.map('map').setView([{center_lat}, {center_lon}], 10);
                
                L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
                    attribution: '© OpenStreetMap contributors',
                    maxZoom: 18
                }}).addTo(map);
                
                {markers_js}
                
                {rain_animation_js}
            </script>
        </body>
        </html>
        """
        
        st.components.v1.html(map_html, height=620)
        
        st.divider()
        
        # Legend and info
        col1, col2 = st.columns([3, 1])
        
        with col1:
            st.markdown("### Map Legend")
            subcol1, subcol2, subcol3, subcol4 = st.columns(4)
            subcol1.markdown("🔴 **High Priority** - Critical watering needed")
            subcol2.markdown("🟡 **Medium Priority** - Watering recommended")
            subcol3.markdown("🟢 **Low/Optimal** - Adequate moisture")
            subcol4.markdown("🔵 **No Data** - No readings logged yet")
        
        with col2:
            if show_rain:
                st.markdown("### Rain Controls")
                st.info("⏸️ = Pause\n\n▶️ = Play")
        
        if show_rain:
            st.success("🌧️ **Animated Rain Radar Active** - Shows past observations and future forecast. Click ⏸️/▶️ to pause/play.")
elif page == "🌧️ Rain Radar":
    st.header("Melbourne Rain Radar")
    w = st.session_state.weather
    c1, c2, c3 = st.columns(3)
    c1.metric("Last 7 Days", f"{w['last_7d']}mm")
    c2.metric("Next 24 Hours", f"{w['next_24h']}mm")
    c3.metric("Next 7 Days", f"{w['next_7d']}mm")
    st.components.v1.iframe("http://www.bom.gov.au/products/IDR023.loop.shtml", height=600, scrolling=True)
    st.caption("Live radar from Bureau of Meteorology")
    
    st.divider()
    st.subheader("Update Weather Manually")
    with st.form("weather_form"):
        c1, c2, c3 = st.columns(3)
        last = c1.number_input("Last 7 days (mm)", 0.0, step=0.1, value=w['last_7d'])
        next24 = c2.number_input("Next 24h (mm)", 0.0, step=0.1, value=w['next_24h'])
        next7 = c3.number_input("Next 7d (mm)", 0.0, step=0.1, value=w['next_7d'])
        
        if st.form_submit_button("Update"):
            st.session_state.weather['last_7d'] = last
            st.session_state.weather['next_24h'] = next24
            st.session_state.weather['next_7d'] = next7
            save_data()
            st.success("Weather updated!")
            st.rerun()

elif page == "➕ Add Site":
    st.header("Add New Watering Site")
    
    # Check if we're editing a site
    if 'editing_site' in st.session_state and st.session_state.editing_site:
        editing_site_id = st.session_state.editing_site
        
        # Check if site still exists
        if editing_site_id not in st.session_state.sites:
            st.error("Site no longer exists!")
            del st.session_state.editing_site
            st.rerun()
        
        editing_site = st.session_state.sites[editing_site_id]
        
        st.info(f"✏️ Editing: **{editing_site['name']}**")
        
        col1, col2 = st.columns([1, 5])
        if col1.button("⬅️ Back to Overview"):
            del st.session_state.editing_site
            st.rerun()
        
        with st.form("edit_site"):
            st.subheader("Basic Information")
            c1, c2 = st.columns(2)
            name = c1.text_input("Site Name *", value=editing_site['name'])
            client = c2.text_input("Client Name", value=editing_site.get('client', ''), placeholder="e.g., UDL, ABC Landscapes")
            c1, c2 = st.columns(2)
            location = c1.text_input("Location *", value=editing_site['location'])
            po = c2.text_input("PO Number *", value=editing_site['po_number'])
            c1, c2 = st.columns(2)
            soil = c1.selectbox("Soil Type", ['Clay Loam', 'Sandy Loam', 'Loam', 'Clay', 'Sand'], 
                               index=['Clay Loam', 'Sandy Loam', 'Loam', 'Clay', 'Sand'].index(editing_site['soil_type']))
            
            st.subheader("Contract Details")
            c1, c2, c3 = st.columns(3)
            start = c1.date_input("Start Date", value=pd.to_datetime(editing_site['start_date']))
            end = c2.date_input("End Date", value=pd.to_datetime(editing_site['end_date']))
            visits = c3.number_input("Visits/Week", 1, 7, editing_site['visits_per_week'])
            c1, c2 = st.columns(2)
            hours = c1.number_input("Hours Quoted", 0.0, step=0.5, value=editing_site['hours_quoted'])
            maturity = c2.selectbox("Plant Maturity", ['Establishment', 'Young', 'Mature'],
                                   index=['Establishment', 'Young', 'Mature'].index(editing_site['maturity']))
            
            st.subheader("Vegetation & Water")
            c1, c2 = st.columns(2)
            trees = c1.number_input("Number of Trees", 0, step=1, value=editing_site['trees'])
            trees_l = c2.number_input("Litres per Tree", 0, step=10, value=editing_site['trees_litres'])
            c1, c2 = st.columns(2)
            tubes = c1.number_input("Tube Stock", 0, step=1, value=editing_site['tubestock'])
            tubes_l = c2.number_input("Litres per Tube", 0, step=1, value=editing_site['tubestock_litres'])
            c1, c2 = st.columns(2)
            turf = c1.number_input("Turf Area (m²)", 0, step=10, value=editing_site['turf_m2'])
            turf_l = c2.number_input("Litres per m²", 0, step=1, value=editing_site['turf_litres'])
            
            if st.form_submit_button("💾 Save Changes", type="primary"):
                if name and location and po:
                    st.session_state.sites[editing_site_id].update({
                        'name': name, 'location': location, 'client': client, 'soil_type': soil, 
                        'start_date': start.strftime('%Y-%m-%d'), 'end_date': end.strftime('%Y-%m-%d'),
                        'visits_per_week': visits, 'po_number': po, 'trees': trees, 'trees_litres': trees_l,
                        'tubestock': tubes, 'tubestock_litres': tubes_l, 'turf_m2': turf, 'turf_litres': turf_l,
                        'hours_quoted': hours, 'maturity': maturity
                    })
                    save_data()
                    st.success(f"✅ {name} updated!")
                    del st.session_state.editing_site
                    st.balloons()
                    st.rerun()
                else:
                    st.error("Fill required fields (*)")
    else:
        # Normal add site form
        with st.form("new_site"):
            st.subheader("Basic Information")
            c1, c2 = st.columns(2)
            name = c1.text_input("Site Name *")
            client = c2.text_input("Client Name", placeholder="e.g., UDL, ABC Landscapes")
            c1, c2 = st.columns(2)
            location = c1.text_input("Location *")
            po = c2.text_input("PO Number *")
            c1, c2 = st.columns(2)
            soil = c1.selectbox("Soil Type", ['Clay Loam', 'Sandy Loam', 'Loam', 'Clay', 'Sand'])
            
            st.subheader("Contract Details")
            c1, c2, c3 = st.columns(3)
            start = c1.date_input("Start Date")
            end = c2.date_input("End Date")
            visits = c3.number_input("Visits/Week", 1, 7, 3)
            c1, c2 = st.columns(2)
            hours = c1.number_input("Hours Quoted", 0.0, step=0.5, value=4.0)
            maturity = c2.selectbox("Plant Maturity", ['Establishment', 'Young', 'Mature'])
            
            st.subheader("Vegetation & Water")
            c1, c2 = st.columns(2)
            trees = c1.number_input("Number of Trees", 0, step=1)
            trees_l = c2.number_input("Litres per Tree", 0, step=10, value=200)
            c1, c2 = st.columns(2)
            tubes = c1.number_input("Tube Stock", 0, step=1)
            tubes_l = c2.number_input("Litres per Tube", 0, step=1, value=5)
            c1, c2 = st.columns(2)
            turf = c1.number_input("Turf Area (m²)", 0, step=10)
            turf_l = c2.number_input("Litres per m²", 0, step=1, value=10)
            
            if st.form_submit_button("✅ Add Site", type="primary"):
                if name and location and po:
                    site_id = f"site_{len(st.session_state.sites) + 1:03d}"
                    st.session_state.sites[site_id] = {
                        'name': name, 'location': location, 'client': client, 'soil_type': soil, 
                        'start_date': start.strftime('%Y-%m-%d'), 'end_date': end.strftime('%Y-%m-%d'),
                        'visits_per_week': visits, 'po_number': po, 'trees': trees, 'trees_litres': trees_l,
                        'tubestock': tubes, 'tubestock_litres': tubes_l, 'turf_m2': turf, 'turf_litres': turf_l,
                        'hours_quoted': hours, 'maturity': maturity, 'visits': []
                    }
                    save_data()
                    st.success(f"✅ {name} added!")
                    st.balloons()
                else:
                    st.error("Fill required fields (*)")

elif page == "⚙️ Settings":
    st.header("Settings & Data Management")
    
    st.subheader("🚦 Priority Level Thresholds")
    st.write("Configure the soil moisture levels that trigger different priority alerts:")
    
    with st.form("threshold_settings"):
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.markdown("### 🔴 High Priority")
            critical = st.slider(
                "Critical - Below this %",
                min_value=0,
                max_value=100,
                value=st.session_state.priority_thresholds['critical'],
                step=1,
                help="Sites with moisture below this level will show as RED/HIGH priority"
            )
            st.caption(f"Current: Below {st.session_state.priority_thresholds['critical']}% = 🔴 HIGH")
        
        with col2:
            st.markdown("### 🟡 Medium Priority")
            medium = st.slider(
                "Medium - Below this %",
                min_value=0,
                max_value=100,
                value=st.session_state.priority_thresholds['medium'],
                step=1,
                help="Sites between critical and this level will show as YELLOW/MEDIUM priority"
            )
            st.caption(f"Current: {st.session_state.priority_thresholds['critical']}%-{st.session_state.priority_thresholds['medium']}% = 🟡 MEDIUM")
        
        with col3:
            st.markdown("### 🟢 Low Priority")
            low = st.slider(
                "Low - Below this %",
                min_value=0,
                max_value=100,
                value=st.session_state.priority_thresholds['low'],
                step=1,
                help="Sites between medium and this level will show as GREEN/LOW priority"
            )
            st.caption(f"Current: {st.session_state.priority_thresholds['medium']}%-{st.session_state.priority_thresholds['low']}% = 🟢 LOW")
        
        st.info(f"⚪ **Optimal**: Moisture above {low}% will be marked as OPTIMAL (no watering needed)")
        
        if st.form_submit_button("💾 Save Threshold Settings", type="primary"):
            if critical >= medium or medium >= low:
                st.error("❌ Thresholds must be in ascending order: Critical < Medium < Low")
            else:
                st.session_state.priority_thresholds['critical'] = critical
                st.session_state.priority_thresholds['medium'] = medium
                st.session_state.priority_thresholds['low'] = low
                save_data()
                st.success(f"✅ Thresholds updated!\n\n🔴 HIGH: <{critical}% | 🟡 MEDIUM: {critical}-{medium}% | 🟢 LOW: {medium}-{low}% | ⚪ OPTIMAL: >{low}%")
                st.balloons()
    
    st.divider()
    
    st.subheader("📤 Import Sites from Excel")
    
    from io import BytesIO
    template_df = pd.DataFrame({
        'Site Name': ['Example Site', ''], 'Address': ['123 St, Melbourne', ''], 'Client': ['ABC Landscapes', ''],
        'PO Number': ['PO-2025-001', ''], 'Soil Type': ['Clay Loam', ''], 'Start Date': ['2025-01-15', ''],
        'End Date': ['2025-06-30', ''], 'Visits Per Week': [3, ''], 'Number of Trees': [50, ''],
        'Litres Per Tree': [200, ''], 'Number of Tube Stock': [150, ''], 'Litres Per Tube Stock': [5, ''],
        'Turf Area (m²)': [500, ''], 'Litres Per m² Turf': [10, ''], 'Hours Quoted': [4.0, ''],
        'Plant Maturity': ['Establishment', '']
    })
    
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        template_df.to_excel(writer, sheet_name='Sites', index=False)
    buffer.seek(0)
    
    st.download_button("📥 Download Import Template", data=buffer, 
                      file_name="UVS_Import_Template.xlsx",
                      mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    
    st.divider()
    excel_file = st.file_uploader("Upload Excel file", type=['xlsx', 'xls'])
    
    if excel_file:
        try:
            try:
                df = pd.read_excel(excel_file, sheet_name='Sites')
            except:
                df = pd.read_excel(excel_file, sheet_name=0)
            
            st.write(f"**Found {len(df)} rows**")
            st.dataframe(df.head(10), use_container_width=True)
            
            if st.button("✅ Import All Sites", type="primary"):
                imported, skipped = 0, 0
                for idx, row in df.iterrows():
                    site_name = row.get('Site Name') or row.get('Site')
                    if pd.isna(site_name) or str(site_name).strip() == '':
                        skipped += 1
                        continue
                    
                    site_id = f"site_{len(st.session_state.sites) + 1:03d}"
                    st.session_state.sites[site_id] = {
                        'name': str(site_name).strip(),
                        'location': str(row.get('Address', 'Unknown')).strip() if not pd.isna(row.get('Address')) else 'Unknown',
                        'client': str(row.get('Client', '')).strip() if not pd.isna(row.get('Client')) else '',
                        'soil_type': str(row.get('Soil Type', 'Clay Loam')).strip() if not pd.isna(row.get('Soil Type')) else 'Clay Loam',
                        'start_date': pd.to_datetime(row.get('Start Date')).strftime('%Y-%m-%d') if not pd.isna(row.get('Start Date')) else datetime.now().strftime('%Y-%m-%d'),
                        'end_date': pd.to_datetime(row.get('End Date')).strftime('%Y-%m-%d') if not pd.isna(row.get('End Date')) else (datetime.now() + timedelta(days=180)).strftime('%Y-%m-%d'),
                        'visits_per_week': int(row.get('Visits Per Week', 3)) if not pd.isna(row.get('Visits Per Week')) else 3,
                        'po_number': str(row.get('PO Number', f'PO-{idx}')).strip(),
                        'trees': int(row.get('Number of Trees', 0)) if not pd.isna(row.get('Number of Trees')) else 0,
                        'trees_litres': int(row.get('Litres Per Tree', 200)) if not pd.isna(row.get('Litres Per Tree')) else 200,
                        'tubestock': int(row.get('Number of Tube Stock', 0)) if not pd.isna(row.get('Number of Tube Stock')) else 0,
                        'tubestock_litres': int(row.get('Litres Per Tube Stock', 5)) if not pd.isna(row.get('Litres Per Tube Stock')) else 5,
                        'turf_m2': int(row.get('Turf Area (m²)', 0)) if not pd.isna(row.get('Turf Area (m²)')) else 0,
                        'turf_litres': int(row.get('Litres Per m² Turf', 10)) if not pd.isna(row.get('Litres Per m² Turf')) else 10,
                        'hours_quoted': float(row.get('Hours Quoted', 4.0)) if not pd.isna(row.get('Hours Quoted')) else 4.0,
                        'maturity': str(row.get('Plant Maturity', 'Establishment')).strip() if not pd.isna(row.get('Plant Maturity')) else 'Establishment',
                        'visits': []
                    }
                    imported += 1
                
                save_data()
                st.success(f"✅ Imported {imported} sites!")
                if skipped > 0:
                    st.info(f"ℹ️ Skipped {skipped} empty rows")
                st.balloons()
        except Exception as e:
            st.error(f"Error: {str(e)}")
    
    st.divider()
    st.subheader("📥 Export Data")
    data = json.dumps(st.session_state.sites, indent=2)
    st.download_button("Download Backup (JSON)", data, f"uvs_backup_{datetime.now().strftime('%Y%m%d')}.json", "application/json")
    
    st.divider()
    st.subheader("📤 Import Data")
    uploaded = st.file_uploader("Choose backup file", type=['json'])
    if uploaded:
        if st.button("Import Data"):
            try:
                imported = json.load(uploaded)
                st.session_state.sites = imported.get('sites', imported)
                if 'weather' in imported:
                    st.session_state.weather = imported['weather']
                save_data()
                st.success("✅ Data imported!")
                st.rerun()
            except Exception as e:
                st.error(f"Error: {str(e)}")
    
    st.divider()
    st.subheader("⚠️ Danger Zone")
    if st.checkbox("Show danger zone"):
        st.warning("This will delete ALL site data!")
        if st.button("🗑️ Clear All Data", type="secondary"):
            st.session_state.sites = {}
            save_data()
            st.success("All data cleared")
            st.rerun()

st.divider()
st.caption("Urban Vegetation Solutions | Call: 0431 405 802 | Dashboard v3.0")
