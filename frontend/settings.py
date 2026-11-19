"""Business settings of the ambulance service (you can change these)."""

CALL_TYPES = ["Cardiac", "Accident", "Breathing difficulty", "Fall", "Fire", "Pregnancy", "Stroke", "Other"]
URGENCY_LEVELS = ["Critical", "High", "Medium", "Low"]
PAYMENT_MODES = ["Cash", "Card", "UPI"]          # the ambulance service is paid in cash, by card or by UPI only
BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
GENDERS = ["Male", "Female", "Other"]

# Areas of the city with their position (latitude, longitude). The agent picks the area on the call; the hospital nearest to it is
# offered when the ambulance is dispatched. Add more areas here. A hospital's own position is kept in the Hospital records.
AREAS = {
    "MG Road": (12.9756, 77.6067), "Indiranagar": (12.9784, 77.6408), "Koramangala": (12.9352, 77.6245),
    "Jayanagar": (12.9299, 77.5838), "Banashankari": (12.9255, 77.5468), "BTM Layout": (12.9166, 77.6101),
    "HSR Layout": (12.9121, 77.6446), "Bannerghatta Road": (12.8950, 77.5970), "Electronic City": (12.8452, 77.6602),
    "Whitefield": (12.9698, 77.7500), "Marathahalli": (12.9591, 77.6974), "Frazer Town": (13.0010, 77.6143),
    "Hebbal": (13.0358, 77.5970), "Yelahanka": (13.1007, 77.5963), "Malleshwaram": (13.0035, 77.5710),
    "Rajajinagar": (12.9911, 77.5521),
}
ROAD_FACTOR = 1.3        # road distance is about this many times the straight-line distance (used to suggest the trip distance)

# Warning windows on the dashboards (days)
INSURANCE_WARN_DAYS = 60
MAINTENANCE_WARN_DAYS = 30
LICENSE_WARN_DAYS = 90
EQUIPMENT_WARN_DAYS = 60

# A signed-in person is signed out after this many minutes without using the site
SESSION_MINUTES = 60            # everyone is signed out after this many idle minutes
STALE_MINUTES = 15              # a trip with no status update for this long is flagged so the agent phones the crew

# Which tables ("Records" in the menu) each role can open and edit. ADMIN opens everything.
# Prices are kept in the Tariff table (Administrator only). Logins are managed on the Users page.
# Day-to-day work (calls, dispatch, billing, attendance, leave, servicing ...) has its own pages; Records is for corrections
# and for adding new staff, vehicles and so on.
ROLE_TABLES = {
    "ADMIN": "ALL",
    "MAINTENANCE": ["ambulance", "ambulance_insurance", "ambulance_maintenance_log", "ambulance_equipment", "location_log"],
    "HR": ["hr", "call_center_agent", "agent_language", "driver", "paramedic", "hr_attendance"],   # leave is decided on the Leave page
    "AGENT": ["customer", "customer_phone", "customer_email"],
}
