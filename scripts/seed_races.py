"""
Seed the Firebase races collection with known Indian running races.
Run once: python -m scripts.seed_races
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from integrations.race_lookup import upsert_race

RACES = [
    {
        "name": "Tata Mumbai Marathon",
        "aliases": ["Mumbai Marathon", "TMM", "Tata Mumbai", "Mumbai Full"],
        "date": "2027-01-18",
        "city": "Mumbai",
        "distances": ["42.2km", "21.1km", "10km", "6km"],
        "url": "https://www.tatamumbaimarathon.com",
        "source": "seeded",
    },
    {
        "name": "Vedanta Delhi Half Marathon",
        "aliases": ["Delhi Half Marathon", "VDHM", "Delhi HM", "Airtel Delhi"],
        "date": "2026-11-22",
        "city": "Delhi",
        "distances": ["21.1km", "10km", "4km"],
        "url": "https://www.vedantadelhihalfmarathon.com",
        "source": "seeded",
    },
    {
        "name": "Tata Consultancy Services World 10K Bangalore",
        "aliases": ["World 10K", "World 10K Bangalore", "TCS 10K", "Bangalore 10K"],
        "date": "2026-05-17",
        "city": "Bangalore",
        "distances": ["10km", "5km"],
        "url": "https://www.world10kbangalore.com",
        "source": "seeded",
    },
    {
        "name": "Bangalore Marathon",
        "aliases": ["BM", "Bengaluru Marathon", "Bangalore Full", "Procam Bangalore"],
        "date": "2026-10-18",
        "city": "Bangalore",
        "distances": ["42.2km", "21.1km"],
        "url": "https://www.bangaloremarathon.com",
        "source": "seeded",
    },
    {
        "name": "Airtel Hyderabad Marathon",
        "aliases": ["Hyderabad Marathon", "AHM", "Hyderabad Full"],
        "date": "2026-08-23",
        "city": "Hyderabad",
        "distances": ["42.2km", "21.1km", "10km"],
        "url": "https://www.airtelhyderabadmarathon.com",
        "source": "seeded",
    },
    {
        "name": "Ladakh Marathon",
        "aliases": ["Ladakh", "Leh Marathon", "Khardungla Challenge"],
        "date": "2026-09-12",
        "city": "Leh",
        "distances": ["42.2km", "21.1km", "72km"],
        "url": "https://www.ladakhmarathon.com",
        "source": "seeded",
    },
    {
        "name": "Kaveri Trail Marathon",
        "aliases": ["KTM", "Kaveri Marathon", "Coorg Marathon"],
        "date": "2026-09-06",
        "city": "Coorg",
        "distances": ["42.2km", "21.1km", "10km"],
        "url": "https://www.kaveritrailmarathon.com",
        "source": "seeded",
    },
    {
        "name": "Pune Marathon",
        "aliases": ["Pune Full", "Procam Pune"],
        "date": "2026-09-20",
        "city": "Pune",
        "distances": ["42.2km", "21.1km"],
        "url": "",
        "source": "seeded",
    },
    {
        "name": "Chennai Marathon",
        "aliases": ["Madras Marathon", "Chennai Full", "Standard Chartered Chennai"],
        "date": "2027-01-11",
        "city": "Chennai",
        "distances": ["42.2km", "21.1km", "10km"],
        "url": "",
        "source": "seeded",
    },
    {
        "name": "Kolkata Marathon",
        "aliases": ["Calcutta Marathon", "KM"],
        "date": "2026-12-20",
        "city": "Kolkata",
        "distances": ["42.2km", "21.1km"],
        "url": "",
        "source": "seeded",
    },
    {
        "name": "Nandi Hills Marathon",
        "aliases": ["Nandi Marathon", "Nandi Hills", "NHM"],
        "date": "2026-09-27",
        "city": "Nandi Hills",
        "distances": ["42.2km", "21.1km", "10km"],
        "url": "",
        "source": "seeded",
    },
    {
        "name": "Auroville Marathon",
        "aliases": ["Auroville", "Pondicherry Marathon"],
        "date": "2027-02-14",
        "city": "Auroville",
        "distances": ["42.2km", "21.1km", "10km"],
        "url": "https://www.aurovillemarathon.com",
        "source": "seeded",
    },
    {
        "name": "Vasai Virar Mayor's Marathon",
        "aliases": ["Vasai Virar Marathon", "VVMM", "Mayor's Marathon"],
        "date": "2026-08-02",
        "city": "Vasai Virar",
        "distances": ["42.2km", "21.1km"],
        "url": "",
        "source": "seeded",
    },
]

if __name__ == "__main__":
    print(f"Seeding {len(RACES)} races...")
    for race in RACES:
        upsert_race(race)
        print(f"  ✓ {race['name']} ({race['date']})")
    print(f"\nDone. {len(RACES)} races seeded to Firebase.")
