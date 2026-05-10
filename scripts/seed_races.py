"""
Seed the Firebase races collection with verified upcoming Indian running races.
Dates sourced from official race websites (May 2026).
Dates left empty ("") where not yet announced — web search fills them at runtime.

Run: python -m scripts.seed_races
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from integrations.race_lookup import upsert_race

RACES = [
    # ── Procam Gold Label Series ───────────────────────────────────────────
    {
        "name": "Vedanta Delhi Half Marathon",
        "aliases": ["VDHM", "Delhi Half Marathon", "Airtel Delhi Half Marathon", "DHM"],
        "date": "2026-10-18",
        "city": "New Delhi",
        "distances": ["21.1km", "10km", "7km", "4.3km", "3.5km"],
        "url": "https://vedantadelhihalfmarathon.procam.in",
        "source": "seeded",
    },
    {
        "name": "Tata Steel World 25K Kolkata",
        "aliases": ["TSW25K", "Kolkata 25K", "Tata Steel Kolkata", "Kolkata Marathon"],
        "date": "2026-12-20",
        "city": "Kolkata",
        "distances": ["25km", "10km", "4.5km"],
        "url": "https://tatasteelworld25k.procam.in",
        "source": "seeded",
    },
    {
        "name": "Tata Mumbai Marathon",
        "aliases": ["TMM", "Mumbai Marathon", "SCMM", "Standard Chartered Mumbai Marathon", "Mumbai Full"],
        "date": "2027-01-17",
        "city": "Mumbai",
        "distances": ["42.2km", "21.1km", "10km", "6km"],
        "url": "https://tatamumbaimarathon.procam.in",
        "source": "seeded",
    },
    {
        "name": "TCS World 10K Bengaluru",
        "aliases": ["World 10K", "TCS 10K", "TCS World 10K", "World 10K Bangalore", "Bangalore 10K"],
        "date": "",   # 2027 date not yet announced (2026 edition was April 26)
        "city": "Bengaluru",
        "distances": ["10km", "4.2km"],
        "url": "https://tcsworld10k.procam.in",
        "source": "seeded",
    },

    # ── Major City Marathons ───────────────────────────────────────────────
    {
        "name": "NMDC Hyderabad Marathon",
        "aliases": ["Hyderabad Marathon", "NHM", "Airtel Hyderabad Marathon", "NMDC HM"],
        "date": "2026-08-30",
        "city": "Hyderabad",
        "distances": ["42.2km", "21.1km", "10km", "5km"],
        "url": "https://nmdchyderabadmarathon.com",
        "source": "seeded",
    },
    {
        "name": "Wipro Bengaluru Marathon",
        "aliases": ["Bangalore Marathon", "WBM", "Bengaluru Marathon", "BM"],
        "date": "2026-09-27",
        "city": "Bengaluru",
        "distances": ["42.2km", "21.1km", "10km", "5km"],
        "url": "https://www.bengalurumarathon.in",
        "source": "seeded",
    },
    {
        "name": "Adani Ahmedabad Marathon",
        "aliases": ["Ahmedabad Marathon", "AAM"],
        "date": "2026-11-29",
        "city": "Ahmedabad",
        "distances": ["42.2km", "21.1km", "10km", "5km"],
        "url": "https://www.ahmedabadmarathon.com",
        "source": "seeded",
    },
    {
        "name": "Baramati Power Marathon",
        "aliases": ["BPM", "Baramati Marathon"],
        "date": "2026-11-29",
        "city": "Baramati",
        "distances": ["42.2km", "21.1km", "10km", "5km"],
        "url": "https://www.bpmorg.com",
        "source": "seeded",
    },
    {
        "name": "Pune International Marathon",
        "aliases": ["PIM", "Pune Marathon"],
        "date": "2026-12-06",
        "city": "Pune",
        "distances": ["42.2km", "21.1km", "10km", "5km"],
        "url": "https://www.marathonpune.com",
        "source": "seeded",
    },
    {
        "name": "Bajaj Pune Marathon",
        "aliases": ["Bajaj Pune", "Bajaj Pune Full"],
        "date": "2026-12-13",
        "city": "Pune",
        "distances": ["42.2km", "21.1km", "10km", "5km"],
        "url": "https://bajajpunemarathon.com",
        "source": "seeded",
    },
    {
        "name": "SKF Goa River Marathon",
        "aliases": ["Goa River Marathon", "GRM", "SKF Goa", "Goa Marathon"],
        "date": "2026-12-13",
        "city": "Goa",
        "distances": ["42.2km", "32km", "21.1km", "10km", "5km"],
        "url": "https://www.skfgoarivermarathon.com",
        "source": "seeded",
    },
    {
        "name": "Freshworks Chennai Marathon",
        "aliases": ["Chennai Marathon", "Chennai Runners Marathon", "FCM", "Chennai Full"],
        "date": "",
        "city": "Chennai",
        "distances": ["42.2km", "32km", "21.1km", "10km"],
        "url": "https://www.thechennaimarathon.com",
        "source": "seeded",
    },
    {
        "name": "Bengaluru Midnight Marathon",
        "aliases": ["Bangalore Midnight Marathon", "BMM", "Midnight Marathon Bangalore"],
        "date": "",
        "city": "Bengaluru",
        "distances": ["42.2km", "31.6km", "21.1km", "10km", "5km"],
        "url": "https://bangalore.bharatmidnightmarathon.run",
        "source": "seeded",
    },
    {
        "name": "Vasai Virar Mayor's Marathon",
        "aliases": ["VVMM", "Vasai Virar Marathon", "Vasai Marathon"],
        "date": "",
        "city": "Vasai-Virar",
        "distances": ["42.2km", "21.1km", "10km", "5km"],
        "url": "https://vvmm.in",
        "source": "seeded",
    },
    {
        "name": "Bodh Gaya Marathon",
        "aliases": ["Bodhgaya Marathon", "Bodh Gaya International Marathon", "Run for Global Peace"],
        "date": "2027-02-14",
        "city": "Bodh Gaya",
        "distances": ["42.2km", "21.1km", "10km"],
        "url": "https://www.bodhgayamarathon.com",
        "source": "seeded",
    },
    {
        "name": "AU Jaipur Marathon",
        "aliases": ["Jaipur Marathon", "Pink City Marathon", "Jaipur Full"],
        "date": "",
        "city": "Jaipur",
        "distances": ["42.2km", "21.1km", "10km", "5km"],
        "url": "https://www.marathonjaipur.com",
        "source": "seeded",
    },
    {
        "name": "Cognizant New Delhi Marathon",
        "aliases": ["New Delhi Marathon", "NDM", "Apollo Tyres New Delhi Marathon", "Delhi Marathon"],
        "date": "",
        "city": "New Delhi",
        "distances": ["42.2km", "21.1km", "10km", "5km"],
        "url": "https://newdelhimarathon.com",
        "source": "seeded",
    },
    {
        "name": "MG Vadodara International Marathon",
        "aliases": ["Vadodara Marathon", "Baroda Marathon", "MG Vadodara"],
        "date": "",
        "city": "Vadodara",
        "distances": ["42.2km", "21.1km", "10km", "5km"],
        "url": "https://vadodaramarathon.com",
        "source": "seeded",
    },

    # ── High Altitude & Specialty ──────────────────────────────────────────
    {
        "name": "Ladakh Marathon",
        "aliases": ["Leh Marathon", "Silk Route Ultra", "Khardung La Challenge", "Ladakh"],
        "date": "2026-09-13",
        "city": "Leh, Ladakh",
        "distances": ["122km", "72km", "42.2km", "21.1km", "11.2km", "5km"],
        "url": "https://ladakhmarathon.com",
        "source": "seeded",
    },
    {
        "name": "Spiti Marathon",
        "aliases": ["Kaza Marathon", "Spiti Valley Marathon"],
        "date": "",
        "city": "Kaza, Spiti Valley",
        "distances": ["77km", "42.2km", "21.1km", "10km"],
        "url": "https://spitimarathon.com",
        "source": "seeded",
    },
    {
        "name": "Himalayan 100 Mile Stage Race",
        "aliases": ["Himalayan 100", "H100", "Darjeeling Stage Race"],
        "date": "2026-10-29",
        "city": "Darjeeling",
        "distances": ["160km", "100km", "43km"],
        "url": "https://himalayan.com",
        "source": "seeded",
    },
    {
        "name": "Manali Marathon",
        "aliases": ["Manali Trail Marathon", "Rohtang Ultra", "Himalayan Xtreme Manali"],
        "date": "",
        "city": "Manali",
        "distances": ["100km", "42.2km", "21.1km", "10km", "5km"],
        "url": "https://www.manalimarathon.org",
        "source": "seeded",
    },
    {
        "name": "Nandi Hills Marathon",
        "aliases": ["Nandi Marathon", "Nandi Hills", "NHM Nandi"],
        "date": "",
        "city": "Nandi Hills",
        "distances": ["42.2km", "21.1km", "10km"],
        "url": "",
        "source": "seeded",
    },
    {
        "name": "Auroville Marathon",
        "aliases": ["Auroville", "Pondicherry Marathon"],
        "date": "",   # 2027 date not announced (2026 was Feb 8)
        "city": "Auroville",
        "distances": ["42.2km", "21.1km", "10km"],
        "url": "https://www.aurovillemarathon.com",
        "source": "seeded",
    },
    {
        "name": "Kaveri Trail Marathon",
        "aliases": ["KTM", "Kaveri Marathon", "Coorg Marathon"],
        "date": "",   # 2027 date not announced (2026 was Apr 11)
        "city": "Coorg",
        "distances": ["42.2km", "21.1km", "10km"],
        "url": "https://kaveritrailmarathon.com",
        "source": "seeded",
    },

    # ── Trail & Ultra ──────────────────────────────────────────────────────
    {
        "name": "Bangalore Ultra",
        "aliases": ["Bangalore Ultra Marathon", "BU", "BLR Ultra"],
        "date": "2026-07-26",
        "city": "Bengaluru",
        "distances": ["50km", "37.5km", "25km", "12.5km", "5km"],
        "url": "https://bangaloreultra.com",
        "source": "seeded",
    },

    # ── Half Marathons & 10Ks ─────────────────────────────────────────────
    {
        "name": "Mumbai Half Marathon",
        "aliases": ["MHM", "Mumbai HM"],
        "date": "2026-08-30",
        "city": "Mumbai",
        "distances": ["21.1km", "10km", "5km"],
        "url": "https://mumbaihalfmarathon.com",
        "source": "seeded",
    },
    {
        "name": "Sarmang Dehradun Marathon",
        "aliases": ["Dehradun Marathon", "SDM"],
        "date": "2026-10-04",
        "city": "Dehradun",
        "distances": ["50km", "42.2km", "21.1km", "10km", "5km"],
        "url": "https://sarmangdehradunmarathon.sarmang.com",
        "source": "seeded",
    },
    {
        "name": "Vedanta Pink City Half Marathon",
        "aliases": ["Pink City Half Marathon", "PCHM", "Jaipur Half Marathon"],
        "date": "",
        "city": "Jaipur",
        "distances": ["21.1km", "10km", "5km"],
        "url": "https://vedantapchm.abcr.in",
        "source": "seeded",
    },
]


if __name__ == "__main__":
    from datetime import date
    today = date.today().isoformat()
    print(f"Seeding {len(RACES)} races (verified as of {today})...")
    for race in RACES:
        upsert_race(race)
        date_str = race["date"] or "date TBD"
        print(f"  ✓ {race['name']} | {date_str} | {race['city']}")
    print(f"\nDone. {len(RACES)} races seeded to Firebase.")
