#!/usr/bin/env python3
# x-ui-hybrid/landing.py
#
# Geo-aware decoy landing-page generator.
# Detects the server's public location, picks a plausible artisan / small-business
# persona for that locale, composes copy from per-archetype phrase pools, and
# renders one of several polished layouts with a randomized palette + font pairing.
#
# Usage:
#   python3 landing.py --domain example.com --out /var/www/example.com
#   python3 landing.py --domain example.com --out /tmp/preview --seed 42
#   python3 landing.py --domain example.com --out /tmp/preview --no-network
#   python3 landing.py --domain example.com --out /tmp/preview --country IT --city Turin
#
# Stdlib only. Tested with Python 3.8+.

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import random
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

def _now() -> datetime:
    return datetime.now(timezone.utc)
from typing import Any, Dict, List, Optional, Tuple

# =============================================================================
# Regional flavor: cities (fallback when geo returns nothing useful), surname
# pools for owner-named businesses, and "place noun" pools for "<noun>
# <trade>" names. Coast=True controls which archetypes are eligible.
# =============================================================================

REGIONS: Dict[str, Dict[str, Any]] = {
    "ES": {"coast": True,  "lang": "es",
           "cities": ["A Coruña", "Cádiz", "Granada", "Bilbao", "Valencia", "San Sebastián"],
           "surnames": ["Mercader", "Olabarri", "Font", "Quiroga", "Aramburu", "Vidal", "Iglesias"],
           "place_nouns": ["Tideline", "Marisma", "Atalaya", "Faro", "Alameda", "Mirador"]},
    "PT": {"coast": True,  "lang": "pt",
           "cities": ["Porto", "Lisboa", "Aveiro", "Coimbra", "Évora", "Braga"],
           "surnames": ["Almeida", "Carvalho", "Macedo", "Pessoa", "Tavares", "Ribeiro"],
           "place_nouns": ["Marés", "Foz", "Ribeira", "Saudade", "Atalaia", "Pedra"]},
    "FR": {"coast": True,  "lang": "fr",
           "cities": ["Lyon", "Bordeaux", "Nantes", "Lille", "Strasbourg", "Marseille", "Brest"],
           "surnames": ["Mercier", "Leclerc", "Dauphin", "Brossard", "Chevalier", "Vasseur"],
           "place_nouns": ["Vieux-Port", "Comptoir", "Atelier", "Faubourg", "Quai", "Marais"]},
    "IT": {"coast": True,  "lang": "it",
           "cities": ["Torino", "Bologna", "Genova", "Trieste", "Verona", "Lecce", "Bari"],
           "surnames": ["Marsala", "Conti", "Lombardi", "Fontana", "Galli", "Ricciardi"],
           "place_nouns": ["Bottega", "Fonte", "Pietra", "Vecchio", "Porto", "Officina"]},
    "DE": {"coast": False, "lang": "de",
           "cities": ["Leipzig", "Dresden", "Münster", "Heidelberg", "Freiburg", "Regensburg"],
           "surnames": ["Werner", "Ostermann", "Brandt", "Hartmann", "Köhler", "Kessler"],
           "place_nouns": ["Ostbau", "Werkstatt", "Hofgut", "Ostmark", "Werft", "Mühle"]},
    "AT": {"coast": False, "lang": "de",
           "cities": ["Innsbruck", "Graz", "Salzburg", "Linz", "Klagenfurt"],
           "surnames": ["Hofer", "Berger", "Steinmann", "Lechner", "Bauer", "Aigner"],
           "place_nouns": ["Almhof", "Werkraum", "Stube", "Holzwerk", "Lichthof"]},
    "CH": {"coast": False, "lang": "de",
           "cities": ["Bern", "Lausanne", "Lucerne", "Basel", "St. Gallen", "Sion"],
           "surnames": ["Fankhauser", "Gerber", "Lüthi", "Brunner", "Kellenberger"],
           "place_nouns": ["Werkhof", "Untergasse", "Belvédère", "Hofstatt"]},
    "NL": {"coast": True,  "lang": "nl",
           "cities": ["Utrecht", "Groningen", "Haarlem", "Leiden", "Maastricht", "Delft"],
           "surnames": ["Van der Werf", "Bosma", "De Vries", "Van Dijk", "Kuipers"],
           "place_nouns": ["Werf", "Gracht", "Polder", "Oude Haven", "Singel"]},
    "BE": {"coast": True,  "lang": "fr",
           "cities": ["Ghent", "Antwerp", "Bruges", "Liège", "Leuven"],
           "surnames": ["Vermeulen", "De Smet", "Janssens", "Dubois", "Lambert"],
           "place_nouns": ["Kaai", "Begijnhof", "Atelier", "Halle"]},
    "GB": {"coast": True,  "lang": "en",
           "cities": ["Edinburgh", "Bristol", "Manchester", "Glasgow", "Norwich", "Sheffield", "Bath"],
           "surnames": ["Fairbairn", "Holloway", "Whitcombe", "Marling", "Pendle", "Ashby"],
           "place_nouns": ["Hollows", "Northgate", "Old Mill", "Tideway", "Quarry", "Spindle"]},
    "IE": {"coast": True,  "lang": "en",
           "cities": ["Galway", "Cork", "Limerick", "Kilkenny", "Sligo", "Dingle"],
           "surnames": ["Gallagher", "Kavanagh", "Donnelly", "Hennessy", "O'Driscoll"],
           "place_nouns": ["Strand", "Headland", "Kilbeg", "Ardmore", "Dún"]},
    "DK": {"coast": True,  "lang": "da",
           "cities": ["Aarhus", "Odense", "Aalborg", "Roskilde", "Esbjerg"],
           "surnames": ["Holm", "Mortensen", "Krogh", "Gundersen", "Nyborg"],
           "place_nouns": ["Værksted", "Havn", "Strandby", "Bryghus"]},
    "SE": {"coast": True,  "lang": "sv",
           "cities": ["Göteborg", "Malmö", "Uppsala", "Visby", "Norrköping", "Umeå"],
           "surnames": ["Lindqvist", "Hellström", "Almgren", "Berglund", "Sjögren"],
           "place_nouns": ["Verkstad", "Brygga", "Norrport", "Bruket"]},
    "NO": {"coast": True,  "lang": "no",
           "cities": ["Trondheim", "Bergen", "Stavanger", "Tromsø", "Ålesund"],
           "surnames": ["Solheim", "Kvist", "Berge", "Halvorsen", "Strand"],
           "place_nouns": ["Verksted", "Brygge", "Fjordsmie", "Nordkai"]},
    "FI": {"coast": True,  "lang": "fi",
           "cities": ["Tampere", "Turku", "Oulu", "Lahti", "Kuopio"],
           "surnames": ["Rantanen", "Lehtinen", "Mäkelä", "Salminen", "Niemi"],
           "place_nouns": ["Paja", "Satama", "Verstas", "Ranta"]},
    "PL": {"coast": False, "lang": "pl",
           "cities": ["Kraków", "Wrocław", "Poznań", "Gdańsk", "Lublin"],
           "surnames": ["Kowalski", "Lewandowski", "Mazur", "Pawlak", "Sienkiewicz"],
           "place_nouns": ["Pracownia", "Stara Mlyn", "Zakład", "Manufaktura"]},
    "CZ": {"coast": False, "lang": "cs",
           "cities": ["Brno", "Olomouc", "Plzeň", "České Budějovice"],
           "surnames": ["Novák", "Procházka", "Kubelka", "Havel", "Bartoš"],
           "place_nouns": ["Dílna", "Manufaktura", "Stará Pošta"]},
    "GR": {"coast": True,  "lang": "el",
           "cities": ["Thessaloniki", "Patras", "Heraklion", "Volos", "Chania"],
           "surnames": ["Papadakis", "Lamprou", "Voulgaris", "Mavridis"],
           "place_nouns": ["Ergastiri", "Limani", "Pyrgos", "Agora"]},
    "TR": {"coast": True,  "lang": "tr",
           "cities": ["Izmir", "Bursa", "Antalya", "Eskişehir", "Trabzon"],
           "surnames": ["Demir", "Yıldırım", "Çelik", "Aslan", "Erdoğan"],
           "place_nouns": ["Atölye", "Liman", "Çarşı", "Han"]},
    "RU": {"coast": False, "lang": "ru",
           "cities": ["Saint Petersburg", "Kazan", "Yekaterinburg", "Nizhny Novgorod"],
           "surnames": ["Volkov", "Sokolov", "Pavlov", "Mironov", "Yegorov"],
           "place_nouns": ["Mastérskaya", "Pochtovaya", "Zaton", "Sloboda"]},
    "UA": {"coast": True,  "lang": "uk",
           "cities": ["Lviv", "Odesa", "Chernivtsi", "Uzhhorod", "Kamianets-Podilskyi"],
           "surnames": ["Kovalenko", "Tkachuk", "Bondar", "Savchenko"],
           "place_nouns": ["Maysternya", "Pidzamche", "Stara Drukarnya"]},
    "US": {"coast": True,  "lang": "en",
           "cities": ["Portland, ME", "Asheville", "Madison", "Burlington",
                      "Santa Fe", "Bozeman", "Providence", "Savannah"],
           "surnames": ["Whittaker", "Holcomb", "Marston", "Pruitt", "Beasley", "Calder"],
           "place_nouns": ["Northgate", "Tideline", "Old Post", "Spruce", "Ferry Hill"]},
    "CA": {"coast": True,  "lang": "en",
           "cities": ["Halifax", "Victoria", "Quebec City", "Kingston", "St. John's"],
           "surnames": ["Tremblay", "Beauchamp", "Cartier", "Lapointe", "Dawson"],
           "place_nouns": ["Northgate", "Ferry Wharf", "Pointe", "Old Pier"]},
    "AU": {"coast": True,  "lang": "en",
           "cities": ["Hobart", "Adelaide", "Newcastle", "Geelong", "Fremantle"],
           "surnames": ["Whitlock", "Gibbs", "Penrose", "Holland", "Cawley"],
           "place_nouns": ["Tidegate", "Old Wharf", "Northshore", "Sandstone"]},
    "NZ": {"coast": True,  "lang": "en",
           "cities": ["Wellington", "Dunedin", "Nelson", "Tauranga", "Napier"],
           "surnames": ["Ngata", "Rountree", "Holloway", "Calder", "Hawthorn"],
           "place_nouns": ["Tideline", "Headland", "Cove", "Kahawai"]},
    "JP": {"coast": True,  "lang": "ja",
           "cities": ["Kyoto", "Kanazawa", "Sapporo", "Fukuoka", "Sendai", "Matsumoto"],
           "surnames": ["Kuroda", "Hayashi", "Saitō", "Mori", "Komatsu", "Aoki"],
           "place_nouns": ["Kobō", "Higashiyama", "Nishi-Mura", "Hatoba"]},
    "KR": {"coast": True,  "lang": "ko",
           "cities": ["Busan", "Daegu", "Jeonju", "Gwangju", "Gangneung"],
           "surnames": ["Han", "Seo", "Jang", "Bae", "Yoon"],
           "place_nouns": ["Gongbang", "Hanok-gil", "Pohang"]},
    "SG": {"coast": True,  "lang": "en",
           "cities": ["Singapore"],
           "surnames": ["Chia", "Ong", "Tan", "Lim", "Goh"],
           "place_nouns": ["Tanjong", "Boat Quay", "Joo Chiat", "Tiong Bahru"]},
    "HK": {"coast": True,  "lang": "en",
           "cities": ["Hong Kong"],
           "surnames": ["Cheung", "Lau", "Wong", "Ng", "Yip"],
           "place_nouns": ["Sheung Wan", "Sai Ying Pun", "Kennedy Town"]},
    "BR": {"coast": True,  "lang": "pt",
           "cities": ["Curitiba", "Florianópolis", "Belo Horizonte", "Recife", "Porto Alegre"],
           "surnames": ["Macedo", "Carvalho", "Pessoa", "Tavares", "Vasconcelos"],
           "place_nouns": ["Mercado", "Praça", "Bairro Velho", "Estaleiro"]},
    "AR": {"coast": True,  "lang": "es",
           "cities": ["Mendoza", "Rosario", "Bariloche", "Mar del Plata", "Salta"],
           "surnames": ["Cabrera", "Quiroga", "Iturbide", "Sarmiento"],
           "place_nouns": ["Almacén", "Patio", "Casa Vieja", "Galpón"]},
    "MX": {"coast": True,  "lang": "es",
           "cities": ["Oaxaca", "Mérida", "Guanajuato", "Puebla", "Querétaro"],
           "surnames": ["Mendoza", "Iturbide", "Rosales", "Bermúdez"],
           "place_nouns": ["Taller", "Casa", "Mercado del Carmen", "Patio"]},
    "ZA": {"coast": True,  "lang": "en",
           "cities": ["Stellenbosch", "Cape Town", "Knysna", "Hermanus"],
           "surnames": ["Du Preez", "Van der Merwe", "Botha", "Coetzee"],
           "place_nouns": ["Werf", "Bay", "Old Wharf", "Vinekraal"]},
    # Generic fallback for anything we don't have a regional flavor for.
    "_":  {"coast": True,  "lang": "en",
           "cities": ["Northgate", "Old Quarter", "Riverside"],
           "surnames": ["Whitcombe", "Marling", "Pendle", "Holcomb", "Marston"],
           "place_nouns": ["Northgate", "Old Mill", "Tideline", "Spindle"]},
}


# =============================================================================
# Archetypes: small-business templates that compose with regional flavor.
# Each archetype carries:
#   - id, trade, label (UK English)
#   - tagline templates (no period, will be punctuated by the layout)
#   - blurb sentences (1 chosen as opener, 1–2 chosen as filler)
#   - bench items (rendered as the "what's on the bench" key/value list)
#   - quotes pool (customer testimonials)
#   - jsonld_type: schema.org type for structured data
#   - coast: True if it only makes sense by the sea
#   - name patterns: how to compose the business name from regional pools
# =============================================================================

ARCHETYPES: List[Dict[str, Any]] = [
    {
        "id": "rope", "trade": "marine cordage", "label": "Hand-laid marine rope",
        "coast": True,
        "name_patterns": ["{place} Cordage", "{surname} & Sons Cordage", "{place} Rope Walk"],
        "taglines": [
            "Hand-laid three-strand and double-braid line",
            "Cordage for boats, climbers and stage rigging",
            "Traditional rope-walk methods, modern fibres"
        ],
        "blurbs": [
            "We splice traditional three-strand and double-braid line at a small shop in {city} — for sailors, climbers and stage riggers who want cordage that outlives the boat.",
            "Each spool is laid on a 60-metre rope walk and inspected by hand before it leaves the workshop.",
            "We work with manilla, hemp, polyester, Dyneema and a small stock of natural sisal for restoration commissions.",
            "Repairs and re-splices are offered at a flat rate; bring the line, or post it.",
        ],
        "bench": [
            ("Lead time",   "{lead}–{lead2} weeks"),
            ("Materials",   "manilla · hemp · polyester · Dyneema"),
            ("Splice work", "eye, end-to-end, brummel"),
            ("Open days",   "Tue – Sat, 09–17"),
            ("Shipping",    "EU + UK, insured"),
            ("Currently booking", "{season} {year}"),
        ],
        "quotes": [
            "It came back stronger than the bow it was tied to. — V.M., {city}",
            "Twelve metres of three-strand, perfectly even. The kind of work you can feel under load. — sailing club commission",
        ],
        "jsonld_type": "Store",
    },
    {
        "id": "knife", "trade": "knife sharpening", "label": "Edge restoration & sharpening",
        "coast": False,
        "name_patterns": ["{surname} Forge", "{place} Edgeworks", "Atelier {surname}"],
        "taglines": [
            "Edge restoration on Japanese and Belgian natural stones",
            "Whetstone service for kitchen, garden, and woodworking edges",
            "Geometry-correct sharpening, not just polishing"
        ],
        "blurbs": [
            "A two-person sharpening atelier in {city}. We bring kitchen, garden and woodworking edges back to factory geometry on Japanese and Belgian natural stones.",
            "We do not use powered grinders. Every edge is hand-set on water stones and finished on a natural slate.",
            "Drop-off, post-in and on-site service for restaurants are all available.",
            "We can sharpen anything from a paring knife to a draw-knife or a hand-plane iron.",
        ],
        "bench": [
            ("Lead time",   "{lead}–{lead2} business days"),
            ("Stones",      "Naniwa · Suehiro · Coticule"),
            ("Edges seen",  "kitchen · garden · woodworking · scissors"),
            ("Restaurant pickup", "Tuesdays"),
            ("Drop-off",    "by the back door, ring twice"),
            ("Repairs",     "tip, chip, and re-bevel from €18"),
        ],
        "quotes": [
            "It cuts paper now, and that has not been true for ten years. — H.B., {city}",
            "Brought a Sabatier carbon I'd given up on. It came back square. — restaurant pickup",
        ],
        "jsonld_type": "LocalBusiness",
    },
    {
        "id": "typewriter", "trade": "typewriter restoration",
        "label": "Vintage typewriter restoration", "coast": False,
        "name_patterns": ["{surname} & Sons", "Maison {surname}", "{place} Typewriters"],
        "taglines": [
            "Strip-down service for Olympia, Olivetti, Hermes and Royal portables",
            "Replated parts, fresh ribbons, calibrated touch",
            "Manual typewriter restoration since {founded}"
        ],
        "blurbs": [
            "Three generations of mechanics in {city}. We service Olympia, Olivetti, Hermes and Royal portables — full strip-down, replated parts, fresh ribbons, calibrated touch.",
            "We hold a small parts library going back to 1947. If we don't have it, we machine it.",
            "Estimates are free; collection within {city} can be arranged.",
        ],
        "bench": [
            ("Lead time",   "{lead}–{lead2} weeks"),
            ("Common services", "platen recovering · escapement · keytops"),
            ("Marques",     "Olympia · Olivetti · Hermes · Royal · Adler"),
            ("Estimates",   "free, in writing, within a week"),
            ("Currently booking", "{season} {year}"),
        ],
        "quotes": [
            "It came back better than it left the factory in 1962. — A.M., {city}",
            "The carriage return is a different machine entirely. Worth every cent. — collector commission",
        ],
        "jsonld_type": "ProfessionalService",
    },
    {
        "id": "surf", "trade": "surfboard shaping", "label": "Hand-shaped surfboards",
        "coast": True,
        "name_patterns": ["{place} Shapes", "{surname} Surfboards", "{place} Glass"],
        "taglines": [
            "Hand-shaped PU and EPS surfboards",
            "Custom shapes for the local point break",
            "One blank at a time, glassed in-house"
        ],
        "blurbs": [
            "A solo glasser in {city} shaping PU and EPS blanks for the local point break and a small list of repeat customers.",
            "Boards are shaped by hand, glassed in 6+4 or 4+4 cloth, and finished with a hot coat or a sanded gloss to order.",
            "We do not ship boards untested; everything goes in the water before it goes to a customer.",
        ],
        "bench": [
            ("Lead time",       "{lead}–{lead2} weeks"),
            ("Stock blanks",    "5'10\" – 9'6\""),
            ("Glassing",        "PU 6+4, EPS 4+4 epoxy"),
            ("Finboxes",        "FCS II · Futures · single-tab"),
            ("Currently booking", "{season} {year}"),
        ],
        "quotes": [
            "Best 6'8\" I've owned. Light, fast, and it doesn't pearl. — repeat customer",
            "Asked for a fish, got a fish that paddles. — local pickup",
        ],
        "jsonld_type": "Store",
    },
    {
        "id": "bookbind", "trade": "bookbinding", "label": "Bookbinding & paper restoration",
        "coast": False,
        "name_patterns": ["{place} Bindery", "{surname} & Co. Bookbinders", "Atelier {surname}"],
        "taglines": [
            "Hand-sewn rebinds, conservation work, custom slipcases",
            "Letterpress endpapers and full-cloth rebinds",
            "Paper, board and leather, finished by hand"
        ],
        "blurbs": [
            "Studio in {city}'s old quarter. Letterpress endpapers, Cohen leather and full-cloth rebinds for libraries, dealers and people who refuse to read on screens.",
            "We accept conservation work on case-by-case basis — please write before posting anything older than 1900.",
            "Custom journals, slipcases and presentation portfolios from a one-off to small editions of fifty.",
        ],
        "bench": [
            ("Lead time",       "{lead}–{lead2} weeks"),
            ("Materials",       "linen · Cohen · Roma · marbled paper"),
            ("Editions",        "1 – 50 copies"),
            ("Conservation",    "by appointment"),
            ("Currently booking", "{season} {year}"),
        ],
        "quotes": [
            "A 19th-century atlas, fully resewn. The hinges sit perfectly. — institutional commission",
            "It will outlive me, my child, and probably my child's child. — private commission",
        ],
        "jsonld_type": "ProfessionalService",
    },
    {
        "id": "coffee", "trade": "coffee roasting", "label": "Specialty coffee roasted to order",
        "coast": False,
        "name_patterns": ["{place} Coffee Roasters", "{surname} Roastery", "{place} Coffee Co."],
        "taglines": [
            "Single-origin green, roasted weekly",
            "Specialty coffee, roasted to order",
            "Direct-trade beans, named-producer lots"
        ],
        "blurbs": [
            "We import single-lot Ethiopian and Colombian green from named producers and roast every Tuesday in a converted dairy outside {city}.",
            "Subscription orders are dispatched on Wednesday morning so the bag in your hand is at most six days off the cooling tray.",
            "We sell only what we roast; no resale, no white-label.",
        ],
        "bench": [
            ("Roast day",      "Tuesday"),
            ("Dispatch",       "Wednesday morning"),
            ("Bag sizes",      "250g · 1kg · 5kg"),
            ("Subscriptions",  "open · weekly or fortnightly"),
            ("Wholesale",      "limited list, take a tasting first"),
        ],
        "quotes": [
            "The Sidamo is the best filter we've poured this season. — café owner, {city}",
            "Six days from cooling tray to cup. The body holds. — subscriber",
        ],
        "jsonld_type": "Store",
    },
    {
        "id": "keys", "trade": "mechanical keyboards", "label": "Custom mechanical keyboards",
        "coast": False,
        "name_patterns": ["{place} Keyworks", "{surname} Keys", "{place} Keyboard Co."],
        "taglines": [
            "Aluminium cases, brass plates, hand-built one at a time",
            "Custom mechanical keyboards, lubed and tuned",
            "Group buys avoided. Builds, not products"
        ],
        "blurbs": [
            "Workshop in {city}. Aluminium cases, brass plates, and topre-converted boards built one at a time. Lead time is honest and long.",
            "We do not run group buys. Every keyboard is a private commission — you talk to the builder, not a Discord moderator.",
            "Switches are lubed by hand, springs sorted by weight, stabilizers band-aided and tuned on a sound box before assembly.",
        ],
        "bench": [
            ("Lead time",       "{lead}–{lead2} weeks"),
            ("Layouts",         "60 · 65 · 75 · TKL · 1800"),
            ("Switches",        "MX, ALPS, topre conversion"),
            ("Cases",           "aluminium, brass, walnut on request"),
            ("Currently booking", "{season} {year}"),
        ],
        "quotes": [
            "Sounds like nothing else I've owned. The thock is honest. — repeat customer",
            "Took longer than promised, came out better than asked. — private commission",
        ],
        "jsonld_type": "Store",
    },
    {
        "id": "field", "trade": "field recording", "label": "Field recording & sound design",
        "coast": True,
        "name_patterns": ["{place} Acoustics", "{surname} Sound", "{place} Field Recording"],
        "taglines": [
            "Location sound for documentary, museum and game work",
            "Field recording, edited and licensed",
            "Cold-weather and salt-rated location kit"
        ],
        "blurbs": [
            "We build location sound for documentary, museum installations and game studios. Based in {city}, equipped for cold and salt, available worldwide.",
            "Standard delivery is 24-bit/96 kHz BWAV with full metadata, organised in Soundminer-compatible folders.",
            "We license non-exclusive use of our own libraries — write for the catalogue.",
        ],
        "bench": [
            ("Booking",        "by quote, half-day minimum"),
            ("Travel",         "EU short-haul, worldwide on commission"),
            ("Format",         "24-bit / 96 kHz BWAV"),
            ("Mics",           "Sennheiser MKH 8000 series · DPA · Sanken"),
            ("Currently booking", "{season} {year}"),
        ],
        "quotes": [
            "We've used three location teams this year and only one came back with usable wind. — broadcast credit",
            "The salt-fog session was clean. We licensed the lot. — game studio",
        ],
        "jsonld_type": "ProfessionalService",
    },
    {
        "id": "ceramic", "trade": "ceramics", "label": "Studio ceramics & functional pottery",
        "coast": False,
        "name_patterns": ["{surname} Ceramics", "{place} Pottery", "{surname} Studio Ceramics"],
        "taglines": [
            "Wheel-thrown stoneware for everyday tables",
            "Functional pottery, fired in a small electric kiln",
            "Reduction-fired porcelain in small batches"
        ],
        "blurbs": [
            "Wheel-thrown stoneware out of a small studio in {city}. Mugs, bowls, plates, jugs — meant to live on a table, go in a dishwasher and come out unchanged.",
            "Glazes are mixed in-house in batches of four litres; chemistry notes are written on the back of every test tile we keep.",
            "Wholesale is limited to about a dozen restaurants and shops. We keep the list short on purpose.",
        ],
        "bench": [
            ("Studio open",  "Sat 11–16, by chance"),
            ("Firing day",   "Wednesday"),
            ("Wholesale",    "by quote, four-restaurant cap"),
            ("Repairs",      "kintsugi referrals on request"),
            ("Mailing list", "we don't keep one"),
        ],
        "quotes": [
            "Five years of daily use, no change. — restaurant pickup, {city}",
            "Heaviest mug I own. The handle is honest. — private order",
        ],
        "jsonld_type": "Store",
    },
    {
        "id": "candle", "trade": "candle making", "label": "Hand-poured candles & natural wax",
        "coast": False,
        "name_patterns": ["{place} Chandlery", "{surname} Candle Co.", "{place} Wax & Wick"],
        "taglines": [
            "Hand-poured beeswax and rapeseed candles",
            "Pure-wax candles, no synthetic fragrance",
            "Small-batch chandlery, dipped and poured"
        ],
        "blurbs": [
            "We pour and dip candles by hand in a workshop in {city}. Beeswax sourced from a single apiary, rapeseed from a co-operative two valleys over.",
            "We do not use synthetic fragrance, paraffin, or stearic-acid blends. The candles smell like wax because they are wax.",
            "Restoration of antique candleholders and oil lamps is a small side practice. Ask if you need a brass piece re-tinned.",
        ],
        "bench": [
            ("Pour day",     "Mondays"),
            ("Beeswax",      "single-apiary, {city} valley"),
            ("Wholesale",    "small list, ask for terms"),
            ("Restoration",  "brass holders, re-tinning"),
            ("Currently booking", "{season} {year}"),
        ],
        "quotes": [
            "Eight hours of clean burn, no soot. — buyer's note",
            "The dipped tapers are the best I've used since my grandmother's. — private order",
        ],
        "jsonld_type": "Store",
    },
    {
        "id": "ferment", "trade": "small-batch fermentation",
        "label": "Fermented hot sauces, miso & vinegar", "coast": False,
        "name_patterns": ["{place} Ferments", "{surname} Pickle Co.", "{place} Brining Room"],
        "taglines": [
            "Wild-fermented hot sauces and miso",
            "Aged vinegars, koji and fermented condiments",
            "Small-batch ferments, two presses a year"
        ],
        "blurbs": [
            "A small fermentation room in {city}. Wild-fermented hot sauces, three-year miso, koji-aged condiments and apple-must vinegars.",
            "Everything ages in glass or oak; nothing in plastic. Salt comes by sack from a single saltworks; chillies and pulses are sourced from named growers each season.",
            "Two press days a year — spring and autumn. The list is small and we keep it that way.",
        ],
        "bench": [
            ("Press days",   "spring · autumn"),
            ("Aged miso",    "12 / 24 / 36 months"),
            ("Hot sauce heat", "mild · warm · serious · don't"),
            ("Wholesale",    "ask, batch-by-batch"),
            ("Currently booking", "{season} {year}"),
        ],
        "quotes": [
            "The 24-month miso is structural. We use it every service. — restaurant pickup",
            "I've gone through three bottles of the warm one. Stop reading and order. — newsletter (we don't have one)",
        ],
        "jsonld_type": "Store",
    },
    {
        "id": "frame", "trade": "frame building", "label": "Hand-brazed bicycle frames",
        "coast": False,
        "name_patterns": ["{surname} Frameworks", "{place} Cycles", "{surname} & Co. Frame Builders"],
        "taglines": [
            "Hand-brazed steel frames, fillet and lugged",
            "Custom geometry, single-builder shop",
            "Steel road, gravel and touring frames"
        ],
        "blurbs": [
            "A single-builder frame shop in {city}. Hand-brazed steel — Reynolds 853, Columbus Spirit, True Temper S3 — fillet and lugged construction.",
            "Geometry is drawn for the rider, not the frame size; fittings include cleat-stance and saddle setback measurement.",
            "Paint is in-house: two-pack, baked, with a heat-cured clear coat. Ten colours on the chart, anything else by sample.",
        ],
        "bench": [
            ("Lead time",       "{lead}–{lead2} months"),
            ("Tubes",           "Reynolds · Columbus · True Temper"),
            ("Build types",     "road · gravel · touring · randonneur"),
            ("Paint",           "two-pack, baked, in-house"),
            ("Currently booking", "{season} {year}"),
        ],
        "quotes": [
            "Climbed the col like the bike was helping. — owner, three seasons in",
            "Painted to match a 1972 Peugeot. Got it on the third try, exact. — private build",
        ],
        "jsonld_type": "Store",
    },
    {
        "id": "letterpress", "trade": "letterpress", "label": "Letterpress stationery & cards",
        "coast": False,
        "name_patterns": ["{place} Press", "{surname} & Daughter Press", "{place} Letterpress"],
        "taglines": [
            "Letterpress stationery on cotton stock",
            "Hand-set type, one impression at a time",
            "Cotton, lead and a Heidelberg cylinder"
        ],
        "blurbs": [
            "A two-press shop in {city}: a Heidelberg KSBA cylinder and a hand-fed Vandercook proof press.",
            "We print on Italian and German cotton stock, with photopolymer or cast-lead type, in one or two colours.",
            "Wedding suites, calling cards, business stationery and small editions of poetry are our standing list.",
        ],
        "bench": [
            ("Presses",      "Heidelberg KSBA · Vandercook 4"),
            ("Stock",        "Tintoretto · Gmund · Magnani"),
            ("Lead time",    "{lead}–{lead2} weeks"),
            ("Editions",     "1 – 250 copies"),
            ("Currently booking", "{season} {year}"),
        ],
        "quotes": [
            "The deboss has a tooth you can read with a fingertip. — buyer's note",
            "Three impressions, perfectly registered. Worth the wait. — wedding commission",
        ],
        "jsonld_type": "ProfessionalService",
    },
    {
        "id": "watch", "trade": "watch repair", "label": "Mechanical watch repair & restoration",
        "coast": False,
        "name_patterns": ["{surname} Horology", "{place} Watchmaker", "{surname} & Co. Watchmakers"],
        "taglines": [
            "Service and restoration of mechanical wristwatches",
            "Bench-trained watchmaking, no module swaps",
            "Vintage Omega, Longines, JLC and the rest"
        ],
        "blurbs": [
            "A small watchmaking bench in {city}. Service and restoration of mechanical movements: cleaning, lubrication, escapement adjustment, and casework where it serves the watch.",
            "We are not a parts swapper. Where a part is repairable, it is repaired; where it is not, we source NOS or have one made.",
            "We do not service quartz movements except as a favour to existing clients.",
        ],
        "bench": [
            ("Service interval", "5 – 7 years recommended"),
            ("Lead time",        "{lead}–{lead2} weeks"),
            ("Movements",        "manual · automatic · chronograph"),
            ("Estimates",        "free, in writing"),
            ("Currently booking", "{season} {year}"),
        ],
        "quotes": [
            "Running within seven seconds a day. The chronograph reset is sharp. — owner, post-service",
            "Dial cleaned without a single removed marker. That's craft. — collector",
        ],
        "jsonld_type": "ProfessionalService",
    },
    {
        "id": "tea", "trade": "tea importing", "label": "Tea importer & tasting room",
        "coast": False,
        "name_patterns": ["{place} Tea Co.", "{surname} & Sons Tea", "{place} Tea Rooms"],
        "taglines": [
            "Single-garden tea, imported and tasted",
            "Direct-trade Japanese green and Chinese oolong",
            "Tasting room and small tea-import practice"
        ],
        "blurbs": [
            "A small tea-import practice and tasting room in {city}. We hold thirty-odd named-garden lots — Japanese sencha, Chinese oolong, a small list of Taiwanese high-mountain — and do not sell what we have not tasted.",
            "Tastings are by appointment, in flights of three, with notes written by hand and given to take away.",
            "We do not blend, scent, or sweeten anything in this room.",
        ],
        "bench": [
            ("Open hours",   "Wed–Sat 13–18, by appointment"),
            ("List size",    "30 – 40 lots, named gardens"),
            ("Tastings",     "flights of three, written notes"),
            ("Wholesale",    "small list, ask for the catalogue"),
            ("Mailing",      "EU + UK, insured"),
        ],
        "quotes": [
            "The Anhua dark tea was the most honest pour I've had in this city. — visiting taster",
            "She knows every garden by name, and every harvest by month. — repeat customer",
        ],
        "jsonld_type": "Store",
    },
    {
        "id": "drylab", "trade": "analogue photo lab", "label": "Analogue photo lab & C-41",
        "coast": False,
        "name_patterns": ["{place} Lab", "{surname} & Co. Photo Lab", "{place} Darkroom"],
        "taglines": [
            "C-41, E-6 and B&W developing, scanning by request",
            "Hand-developed film, scanned to 50 megapixels",
            "Analogue photo lab, drum-scan service"
        ],
        "blurbs": [
            "A two-person darkroom in {city}. C-41, B&W and on Tuesdays E-6, plus drum and flatbed scanning, optical printing on RC and fibre paper.",
            "Push and pull on request. Negatives are sleeved, never stapled. We do not auto-correct scans without asking.",
            "Walk-in turnaround for C-41 is 24 hours; everything else by quote.",
        ],
        "bench": [
            ("Process",       "C-41 · B&W · E-6 (Tue)"),
            ("Turnaround",    "C-41 next-day · B&W 2–3 days"),
            ("Scanning",      "Frontier · Imacon · drum on request"),
            ("Optical prints","fibre or RC, by hand"),
            ("Mailing",       "drop-off bag at the door"),
        ],
        "quotes": [
            "First scan from a 1995 Portra and the dust map shows nothing. — magazine job",
            "She caught a fogged roll before I'd noticed. Saved a wedding. — pickup, {city}",
        ],
        "jsonld_type": "ProfessionalService",
    },
    {
        "id": "honey", "trade": "beekeeping", "label": "Single-apiary honey & beekeeping",
        "coast": False,
        "name_patterns": ["{place} Apiary", "{surname} Honey Co.", "{place} Bees"],
        "taglines": [
            "Single-apiary, single-season honey",
            "Hive products from one valley",
            "Honey, beeswax and propolis from the home apiary"
        ],
        "blurbs": [
            "A small apiary in the hills above {city}: thirty-two hives, three apiary sites, one beekeeper.",
            "Honey is bottled by season, never blended across years, and never heated above hive temperature.",
            "Beeswax goes to local candle-makers and a chandler in town; propolis tincture is poured to order.",
        ],
        "bench": [
            ("Harvests",     "May · July · September"),
            ("Hives",        "32 across three sites"),
            ("Bottling",     "by hand, single-season"),
            ("Wax",          "to candle-makers, by appointment"),
            ("Propolis",     "tincture, poured to order"),
        ],
        "quotes": [
            "The summer pour is the best lime-flower we've stocked. — co-op buyer",
            "He named the meadow on the label. That's not marketing — that's the meadow. — pickup, {city}",
        ],
        "jsonld_type": "Store",
    },
    {
        "id": "framer", "trade": "framing & gilding",
        "label": "Picture framing, gilding & restoration", "coast": False,
        "name_patterns": ["{place} Framers", "{surname} & Co. Framing", "{place} Gilders"],
        "taglines": [
            "Hand-finished frames, water-gilded and toned",
            "Conservation framing for works on paper",
            "Frame restoration and bespoke moulding"
        ],
        "blurbs": [
            "A two-bench framing and gilding shop in {city}. Bespoke mouldings, water-gilded leaf, and conservation framing for works on paper.",
            "We work with museums, dealers and private collectors; we will also frame your child's drawing properly, if you ask.",
            "Restoration of damaged 18th- and 19th-century frames is a slow speciality — please write before bringing one in.",
        ],
        "bench": [
            ("Lead time",      "{lead}–{lead2} weeks"),
            ("Conservation",   "by appointment"),
            ("Gilding",        "23kt water · 12kt oil"),
            ("Mouldings",      "stock + bespoke"),
            ("Currently booking", "{season} {year}"),
        ],
        "quotes": [
            "Re-gilded an 1810 frame so well I had to be told what they'd done. — dealer commission",
            "Rebated, glazed and lined inside a week. — auction house pickup",
        ],
        "jsonld_type": "ProfessionalService",
    },
    {
        "id": "distill", "trade": "small-batch distilling", "label": "Small-batch distillery",
        "coast": False,
        "name_patterns": ["{place} Distillery", "{surname} & Sons Distilling", "{place} Spirits Co."],
        "taglines": [
            "Botanical gin and aged grain spirit",
            "Single-still distilling, two batches a month",
            "Aquavit, gin and a small list of fruit eaux-de-vie"
        ],
        "blurbs": [
            "A 200-litre still in {city}. Two batches a month — gin in the first half, aged grain or aquavit in the second.",
            "Botanicals are sourced within 80 km of the still; juniper from a single woodland, coriander from a single farm.",
            "All spirits are bottled at cask strength on request; the standard line sits at 43%.",
        ],
        "bench": [
            ("Still",        "200 L copper pot · single rectifying column"),
            ("Schedule",     "gin (1st half) · aquavit (2nd half)"),
            ("Cask strength","by request"),
            ("Wholesale",    "limited, ask for the list"),
            ("Tasting room", "Friday 17–20"),
        ],
        "quotes": [
            "Most honest aquavit I've poured this year. — bar pickup, {city}",
            "The Navy strength gin holds its citrus on ice. Rare. — listing buyer",
        ],
        "jsonld_type": "Store",
    },
    {
        "id": "sail", "trade": "sailmaking", "label": "Sailmaking & canvas work",
        "coast": True,
        "name_patterns": ["{place} Sail Loft", "{surname} & Sons Sailmakers", "{place} Canvas Works"],
        "taglines": [
            "Hand-finished sails and traditional canvas work",
            "Sail repairs, dodgers and bespoke covers",
            "Loft work for cruisers and classic boats"
        ],
        "blurbs": [
            "A sail loft in {city}, working in Dacron, laminate and traditional cotton canvas. New sails, repairs, and full re-cuts to old plans.",
            "Heavy canvas work — boom covers, dodgers, sprayhoods, awnings — is hand-finished on a Pfaff 545 and double-stitched at the load points.",
            "We carry a small loft of secondhand sails, sorted and tagged; ask for the list before you order new.",
        ],
        "bench": [
            ("Lead time",       "{lead}–{lead2} weeks"),
            ("Sail work",       "Dacron · laminate · cotton canvas"),
            ("Canvas",          "covers · dodgers · sprayhoods"),
            ("Repairs",         "while-you-wait for small jobs"),
            ("Currently booking", "{season} {year}"),
        ],
        "quotes": [
            "Twelve seasons on the main, re-cut twice — still sets clean. — owner pickup",
            "Replaced a torn dodger in a morning. We sailed out at noon. — visiting boat",
        ],
        "jsonld_type": "Store",
    },
    {
        "id": "cabinet", "trade": "cabinet-making",
        "label": "Cabinet-making & furniture restoration", "coast": False,
        "name_patterns": ["{place} Joinery", "{surname} & Sons Cabinet-makers", "{surname} Furniture Restoration"],
        "taglines": [
            "Hand-cut joinery in oak, walnut and ash",
            "Furniture restoration and bespoke commissions",
            "Cabinet-making, mortise and dovetail by hand"
        ],
        "blurbs": [
            "A two-bench joiner's shop in {city}. Bespoke cabinets, library shelving and the occasional kitchen, in solid oak, walnut and ash.",
            "Restoration is a separate practice — we re-glue, re-veneer and re-finish 18th- and 19th-century pieces, and we will not sand a patina off unless you ask.",
            "Lead times are honest. Estimates are free. Site visits within {city} are no charge.",
        ],
        "bench": [
            ("Lead time",      "{lead}–{lead2} months"),
            ("Materials",      "European oak · walnut · ash"),
            ("Joinery",        "mortise · dovetail · half-blind"),
            ("Restoration",    "veneer · French polish · re-glue"),
            ("Currently booking", "{season} {year}"),
        ],
        "quotes": [
            "Floor-to-ceiling library, dry-fitted before delivery, perfect on site. — private commission",
            "He saved the patina. The piece is unrecognisable, in the right way. — heirloom restoration",
        ],
        "jsonld_type": "Store",
    },
    {
        "id": "dye", "trade": "natural dyeing", "label": "Natural-dye textile studio",
        "coast": False,
        "name_patterns": ["{place} Dye House", "{surname} & Co. Textiles", "{place} Indigo Studio"],
        "taglines": [
            "Plant-dyed linen, indigo vats and madder reds",
            "Hand-dyed cloth and small-run scarves",
            "Indigo, madder, and a working dye garden"
        ],
        "blurbs": [
            "A small dye studio with its own dye garden in {city}. Indigo vats, madder, weld and walnut hulls. Cloth is dyed in lots of one to twelve metres.",
            "We work in linen, hemp and a slow-grown wool from a flock two valleys over. No mordants beyond alum and iron.",
            "Custom dye work is offered on cloth supplied by the client — within reason, and after a sample.",
        ],
        "bench": [
            ("Vats",          "indigo · madder · weld · walnut"),
            ("Lead time",     "{lead}–{lead2} weeks"),
            ("Lot size",      "1 – 12 m"),
            ("Custom work",   "after a sample"),
            ("Currently booking", "{season} {year}"),
        ],
        "quotes": [
            "An honest blue. The depth holds after a year of wear. — designer commission",
            "Walnut on linen, exactly the colour I drew. — repeat customer",
        ],
        "jsonld_type": "Store",
    },
    {
        "id": "luthier", "trade": "lutherie",
        "label": "Stringed-instrument repair & lutherie", "coast": False,
        "name_patterns": ["{surname} Lutherie", "{place} String Shop", "{surname} & Co. Luthiers"],
        "taglines": [
            "Acoustic and classical instrument repair",
            "Set-ups, neck resets and crack repairs",
            "Stringed-instrument workshop, all repairs by hand"
        ],
        "blurbs": [
            "A two-bench lutherie in {city}. Acoustic guitars, classical guitars and an occasional violin: set-ups, neck resets, crack repair, fretwork.",
            "We work with carved tops as well as flat tops; resonator instruments and steel-string archtops on a case-by-case basis.",
            "Estimates are written. Difficult repairs come with a second pair of eyes before any glue is opened.",
        ],
        "bench": [
            ("Common work",  "set-up · refret · neck reset"),
            ("Lead time",    "{lead}–{lead2} weeks"),
            ("Estimates",    "free, in writing"),
            ("Acceptance",   "guitars · classical · occasional violin"),
            ("Currently booking", "{season} {year}"),
        ],
        "quotes": [
            "Bridge re-glued, neck reset, action set perfectly. The guitar plays itself. — recording-session pickup",
            "She found a hairline I'd missed for ten years. — collector",
        ],
        "jsonld_type": "ProfessionalService",
    },
]


# =============================================================================
# Visual systems: layouts × palettes × font pairings.
# =============================================================================

PALETTES: List[Dict[str, str]] = [
    {"name": "paper",      "bg": "#f5efe6", "fg": "#1c1a16", "muted": "#5a554c", "rule": "#3a342b", "accent": "#7b2d1e", "card": "#ede5d8"},
    {"name": "linen",      "bg": "#efe9df", "fg": "#1f1d18", "muted": "#5a554c", "rule": "#2c2722", "accent": "#3a4a3f", "card": "#e3dccf"},
    {"name": "ivory",      "bg": "#f7f3ea", "fg": "#231f1a", "muted": "#5b5448", "rule": "#3a3128", "accent": "#5b3a1d", "card": "#ece6d8"},
    {"name": "fog",        "bg": "#e8e6e1", "fg": "#1f1f1f", "muted": "#535353", "rule": "#252525", "accent": "#2a4f3f", "card": "#dcdad4"},
    {"name": "blackwhite", "bg": "#fafafa", "fg": "#0a0a0a", "muted": "#4a4a4a", "rule": "#0a0a0a", "accent": "#0a0a0a", "card": "#ececec"},
    {"name": "bone",       "bg": "#ece5d9", "fg": "#1a1814", "muted": "#54504a", "rule": "#2a261f", "accent": "#6b3326", "card": "#e2dac9"},
    {"name": "midnight",   "bg": "#0f1217", "fg": "#e5e2da", "muted": "#9aa1ac", "rule": "#7a8290", "accent": "#c5a26a", "card": "#1b1f26"},
    {"name": "ink",        "bg": "#101313", "fg": "#e8e3d6", "muted": "#a39e90", "rule": "#7c7867", "accent": "#a05a2e", "card": "#1a1d1d"},
    {"name": "moss",       "bg": "#1a1f1a", "fg": "#e3e0d4", "muted": "#9aa195", "rule": "#7a8175", "accent": "#b89a5e", "card": "#222820"},
    {"name": "sage",       "bg": "#eef0e7", "fg": "#1f211a", "muted": "#5a5d52", "rule": "#33372d", "accent": "#3f5942", "card": "#e1e4d8"},
    {"name": "ochre",      "bg": "#f3ece0", "fg": "#1f1a14", "muted": "#5b5247", "rule": "#3a2f1f", "accent": "#a05a1c", "card": "#e8e0cf"},
]

FONTS: List[Dict[str, str]] = [
    {"name": "iowan", "head": "'Iowan Old Style','Palatino Linotype',Georgia,serif",
     "body": "'Iowan Old Style','Palatino Linotype',Georgia,serif",
     "small": "system-ui,-apple-system,'Segoe UI',Helvetica,sans-serif"},
    {"name": "gar-helv", "head": "'EB Garamond',Garamond,Georgia,serif",
     "body": "system-ui,-apple-system,'Segoe UI',Helvetica,sans-serif",
     "small": "ui-monospace,'SF Mono',Menlo,monospace"},
    {"name": "didot", "head": "'Didot','Bodoni 72',Didone,serif",
     "body": "Georgia,'Iowan Old Style',serif",
     "small": "system-ui,-apple-system,sans-serif"},
    {"name": "mono-only", "head": "ui-monospace,'SF Mono',Menlo,Consolas,monospace",
     "body": "ui-monospace,'SF Mono',Menlo,Consolas,monospace",
     "small": "ui-monospace,'SF Mono',Menlo,monospace"},
    {"name": "helv-only", "head": "'Helvetica Neue',Helvetica,Arial,sans-serif",
     "body": "'Helvetica Neue',Helvetica,Arial,sans-serif",
     "small": "ui-monospace,'SF Mono',Menlo,monospace"},
    {"name": "playfair-inter", "head": "'Playfair Display','Bodoni 72',Didone,serif",
     "body": "system-ui,-apple-system,'Segoe UI',sans-serif",
     "small": "ui-monospace,'SF Mono',Menlo,monospace"},
    {"name": "georgia-mono", "head": "Georgia,'Iowan Old Style',serif",
     "body": "Georgia,'Iowan Old Style',serif",
     "small": "ui-monospace,'SF Mono',Menlo,monospace"},
]

# Layouts: each is a key consumed by the renderer to pick a template.
LAYOUTS = ["editorial", "studio_dark", "brutalist", "boutique", "press"]

# Layouts that look bad on a dark palette / vice versa — used to filter combos.
DARK_PALETTES = {"midnight", "ink", "moss"}
DARK_LAYOUTS  = {"studio_dark"}
LIGHT_LAYOUTS = {"editorial", "brutalist", "boutique", "press"}


# =============================================================================
# Geo detection
# =============================================================================

GEO_SOURCES = [
    ("https://ipinfo.io/json", lambda d: {
        "country": d.get("country", "").upper() or None,
        "city":    d.get("city") or None,
        "region":  d.get("region") or None,
    }),
    ("https://ipapi.co/json/", lambda d: {
        "country": (d.get("country_code") or d.get("country") or "").upper() or None,
        "city":    d.get("city") or None,
        "region":  d.get("region") or None,
    }),
    ("http://ip-api.com/json/", lambda d: {
        "country": (d.get("countryCode") or "").upper() or None,
        "city":    d.get("city") or None,
        "region":  d.get("regionName") or None,
    }),
]

def detect_geo(timeout: float = 4.0) -> Dict[str, Optional[str]]:
    for url, parse in GEO_SOURCES:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "x-ui-hybrid-landing/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8", errors="replace"))
            parsed = parse(data)
            if parsed.get("country"):
                return parsed
        except Exception:
            continue
    return {"country": None, "city": None, "region": None}


# =============================================================================
# Composition
# =============================================================================

def pick_persona(rng: random.Random, country: str, city: Optional[str]) -> Dict[str, Any]:
    region = REGIONS.get(country) or REGIONS["_"]
    on_coast = bool(region.get("coast", False))
    eligible = [a for a in ARCHETYPES if (not a["coast"] or on_coast)]
    archetype = rng.choice(eligible)
    surname = rng.choice(region["surnames"])
    place_noun = rng.choice(region["place_nouns"])
    name = rng.choice(archetype["name_patterns"]).format(
        surname=surname, place=place_noun
    )
    chosen_city = city or rng.choice(region["cities"])

    # Numerical garnish.
    lead = rng.randint(2, 6)
    lead2 = lead + rng.randint(2, 5)
    year_now = _now().year
    founded = rng.randint(year_now - 35, year_now - 6)
    season = rng.choice(["spring", "summer", "autumn", "winter"])
    next_year = year_now + (1 if rng.random() < 0.5 else 0)

    fmt = {
        "city": chosen_city, "lead": lead, "lead2": lead2,
        "season": season, "year": next_year, "founded": founded,
    }

    blurbs = list(archetype["blurbs"])
    rng.shuffle(blurbs)
    blurb_main = blurbs[0].format(**fmt)
    blurb_more = [b.format(**fmt) for b in blurbs[1:1 + rng.randint(1, 2)]]

    bench = [(k, v.format(**fmt)) for (k, v) in archetype["bench"]]
    rng.shuffle(bench)
    bench = bench[: max(4, min(6, len(bench)))]

    quotes = [q.format(**fmt) for q in archetype["quotes"]]
    rng.shuffle(quotes)
    quotes = quotes[:rng.randint(1, min(2, len(quotes)))]

    tagline = rng.choice(archetype["taglines"]).format(**fmt)

    return {
        "archetype":   archetype["id"],
        "trade":       archetype["trade"],
        "label":       archetype["label"],
        "name":        name,
        "city":        chosen_city,
        "country":     country,
        "founded":     founded,
        "tagline":     tagline,
        "blurb_main":  blurb_main,
        "blurb_more":  blurb_more,
        "bench":       bench,
        "quotes":      quotes,
        "jsonld_type": archetype["jsonld_type"],
    }


def pick_visual(rng: random.Random, layout: Optional[str] = None) -> Dict[str, Any]:
    if layout is None:
        layout = rng.choice(LAYOUTS)
    if layout in DARK_LAYOUTS:
        palette = rng.choice([p for p in PALETTES if p["name"] in DARK_PALETTES])
    else:
        palette = rng.choice([p for p in PALETTES if p["name"] not in DARK_PALETTES])

    # Font pairings that fit each layout's tone.
    font_choices = {
        "editorial":   ["iowan", "gar-helv", "georgia-mono"],
        "studio_dark": ["helv-only", "gar-helv", "playfair-inter"],
        "brutalist":   ["mono-only"],
        "boutique":    ["didot", "playfair-inter", "gar-helv"],
        "press":       ["iowan", "georgia-mono", "didot"],
    }
    fonts = rng.choice([f for f in FONTS if f["name"] in font_choices.get(layout, [f["name"] for f in FONTS])])
    return {"layout": layout, "palette": palette, "fonts": fonts}


# =============================================================================
# Rendering
# =============================================================================

def esc(s: str) -> str:
    return html.escape(s, quote=True)

def render_jsonld(persona: Dict[str, Any], domain: str) -> str:
    data = {
        "@context": "https://schema.org",
        "@type": persona["jsonld_type"],
        "name": persona["name"],
        "description": persona["tagline"] + ". " + persona["blurb_main"],
        "url": f"https://{domain}/",
        "address": {
            "@type": "PostalAddress",
            "addressLocality": persona["city"],
            "addressCountry": persona["country"],
        },
        "email": f"hello@{domain}",
        "foundingDate": str(persona["founded"]),
    }
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

def render_favicon(palette: Dict[str, str], persona: Dict[str, Any]) -> str:
    initial = persona["name"].strip()[:1].upper()
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="8" fill="{palette['accent']}"/>
  <text x="32" y="42" font-family="Georgia, serif" font-size="34" font-weight="600"
        text-anchor="middle" fill="{palette['bg']}">{esc(initial)}</text>
</svg>"""


# ---- HTML pieces shared by all layouts ----------------------------------------

HEAD_TMPL = """<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name} — {tagline}</title>
<meta name="description" content="{descr}">
<meta name="robots" content="index,follow">
<meta property="og:type" content="website">
<meta property="og:title" content="{name}">
<meta property="og:description" content="{tagline}">
<meta property="og:url" content="https://{domain}/">
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<script type="application/ld+json">{jsonld}</script>
<style>{css}</style>
</head>
<body class="layout-{layout} palette-{palette_name}">
"""

FOOT_TMPL = """
<footer class="site-footer">
  <div class="wrap">
    © {year} {name}. {city}. Studio visits by appointment only.
    <span class="sep">·</span>
    <a href="mailto:hello@{domain}">hello@{domain}</a>
  </div>
</footer>
</body>
</html>
"""

BASE_CSS = """
*,*::before,*::after { box-sizing: border-box; }
html,body { margin:0; padding:0; }
img,svg { max-width:100%; display:block; }
a { color: inherit; }
h1,h2,h3,h4 { font-weight: 500; margin:0; }
p { margin:0; }
ul { padding:0; margin:0; list-style:none; }
.wrap { max-width: 1080px; margin: 0 auto; padding: 0 28px; }
@media (max-width: 720px) { .wrap { padding: 0 22px; } }
"""

# ---- Layout-specific renderers ------------------------------------------------

def layout_editorial(persona, palette, fonts, domain) -> Tuple[str, str]:
    """Editorial / paper / serif — newspaper feel with rules and small-caps."""
    css = BASE_CSS + f"""
:root {{
  --bg: {palette['bg']}; --fg: {palette['fg']}; --muted: {palette['muted']};
  --rule: {palette['rule']}; --accent: {palette['accent']}; --card: {palette['card']};
}}
body {{ background:var(--bg); color:var(--fg);
  font-family:{fonts['body']}; font-size: 18px; line-height: 1.55;
  -webkit-font-smoothing: antialiased; }}
.kicker {{ font-family:{fonts['small']}; font-size: 12px; letter-spacing: .22em;
  text-transform: uppercase; color: var(--accent); }}
.masthead {{ padding: 64px 0 28px; border-bottom: 1px solid var(--rule); }}
.masthead h1 {{ font-family:{fonts['head']}; font-size: clamp(40px, 6vw, 76px);
  letter-spacing: -.01em; line-height: 1.02; margin: 14px 0 8px; }}
.masthead .lede {{ font-style: italic; color: var(--muted); font-size: 20px; max-width: 56ch; }}
.section {{ padding: 44px 0; border-bottom: 1px solid var(--rule); }}
.section h2 {{ font-family:{fonts['small']}; font-size: 12px; letter-spacing: .22em;
  text-transform: uppercase; color: var(--rule); margin: 0 0 18px; }}
.section p {{ font-size: 18px; max-width: 68ch; margin-bottom: 16px; }}
.cols-2 {{ display:grid; grid-template-columns: 1.4fr 1fr; gap: 48px; }}
@media (max-width: 800px) {{ .cols-2 {{ grid-template-columns: 1fr; gap: 28px; }} }}
.bench {{ list-style:none; padding:0; margin:0; }}
.bench li {{ display:flex; justify-content:space-between; gap:14px;
  padding: 12px 0; border-bottom: 1px dotted color-mix(in srgb, var(--rule) 50%, transparent); font-size: 16px; }}
.bench li span:last-child {{ color: var(--muted); text-align: right; }}
.quote {{ border-left: 3px solid var(--accent); padding: 6px 0 6px 20px;
  font-style: italic; color: color-mix(in srgb, var(--fg) 85%, var(--bg));
  margin-bottom: 18px; max-width: 60ch; }}
.contact a {{ color: var(--accent); text-decoration: none; border-bottom: 1px solid var(--accent); }}
.site-footer {{ padding: 28px 0 64px; font-size: 13px; color: var(--muted); }}
.site-footer .sep {{ margin: 0 8px; }}
"""
    blurbs_html = "\n".join(f"<p>{esc(b)}</p>" for b in [persona["blurb_main"]] + persona["blurb_more"])
    bench_html = "\n".join(f"<li><span>{esc(k)}</span><span>{esc(v)}</span></li>" for k, v in persona["bench"])
    quotes_html = "\n".join(f'<p class="quote">{esc(q)}</p>' for q in persona["quotes"])
    body = f"""
<header class="masthead">
  <div class="wrap">
    <div class="kicker">{esc(persona['city'])} · {esc(persona['trade'])} · est. {persona['founded']}</div>
    <h1>{esc(persona['name'])}</h1>
    <p class="lede">{esc(persona['tagline'])}.</p>
  </div>
</header>
<main>
  <section class="section">
    <div class="wrap cols-2">
      <div>
        <h2>About the workshop</h2>
        {blurbs_html}
      </div>
      <div>
        <h2>Currently</h2>
        <ul class="bench">{bench_html}</ul>
      </div>
    </div>
  </section>
  <section class="section">
    <div class="wrap">
      <h2>Notes</h2>
      {quotes_html}
    </div>
  </section>
  <section class="section contact">
    <div class="wrap">
      <h2>Get in touch</h2>
      <p>Write with what you have, what you'd like, and roughly when. We answer in batches on Friday afternoons.</p>
      <p>· <a href="mailto:hello@{esc(domain)}">hello@{esc(domain)}</a></p>
    </div>
  </section>
</main>
"""
    return css, body


def layout_studio_dark(persona, palette, fonts, domain) -> Tuple[str, str]:
    """Studio dark — minimal agency-style, sans, dark with one accent."""
    css = BASE_CSS + f"""
:root {{
  --bg: {palette['bg']}; --fg: {palette['fg']}; --muted: {palette['muted']};
  --rule: {palette['rule']}; --accent: {palette['accent']}; --card: {palette['card']};
}}
body {{ background:var(--bg); color:var(--fg);
  font-family:{fonts['body']}; font-size: 17px; line-height: 1.55;
  -webkit-font-smoothing: antialiased; }}
.hero {{ min-height: 78vh; display:flex; flex-direction:column; justify-content:flex-end;
  padding: 60px 0 56px; border-bottom: 1px solid var(--rule); }}
.hero .small {{ font-family:{fonts['small']}; font-size: 12px; letter-spacing: .25em;
  text-transform: uppercase; color: var(--accent); }}
.hero h1 {{ font-family:{fonts['head']}; font-weight: 600; letter-spacing: -.02em;
  font-size: clamp(46px, 8vw, 110px); line-height: .98; margin: 22px 0 18px; }}
.hero .lede {{ font-size: 20px; color: var(--muted); max-width: 52ch; }}
.section {{ padding: 80px 0; border-bottom: 1px solid var(--rule); }}
.label {{ font-family:{fonts['small']}; font-size: 12px; letter-spacing: .25em;
  text-transform: uppercase; color: var(--accent); margin-bottom: 14px; display:block; }}
.section h2 {{ font-family:{fonts['head']}; font-size: clamp(28px,3.6vw,40px); letter-spacing: -.01em; margin-bottom: 24px; max-width: 24ch; }}
.section p {{ max-width: 64ch; margin-bottom: 14px; color: color-mix(in srgb, var(--fg) 90%, var(--bg)); }}
.bench-grid {{ display:grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0;
  border-top: 1px solid var(--rule); }}
.bench-grid > div {{ padding: 18px 22px; border-bottom: 1px solid var(--rule);
  border-right: 1px solid var(--rule); }}
.bench-grid > div:nth-child(2n) {{ border-right: 0; }}
.bench-grid .k {{ font-family:{fonts['small']}; font-size: 11px; letter-spacing: .22em;
  text-transform: uppercase; color: var(--muted); margin-bottom: 6px; }}
.bench-grid .v {{ font-size: 17px; color: var(--fg); }}
.pull {{ font-family:{fonts['head']}; font-size: clamp(20px,2.4vw,28px); line-height: 1.35;
  font-weight: 500; max-width: 36ch; margin-bottom: 14px; }}
.byline {{ font-family:{fonts['small']}; font-size: 12px; letter-spacing: .15em;
  text-transform: uppercase; color: var(--muted); }}
.contact-row {{ display:flex; justify-content: space-between; align-items: baseline;
  flex-wrap: wrap; gap: 18px; }}
.contact-row a {{ font-family:{fonts['head']}; font-size: clamp(28px,4vw,52px);
  text-decoration: none; color: var(--accent); border-bottom: 1px solid var(--accent); }}
.site-footer {{ padding: 28px 0 60px; font-size: 12px; letter-spacing: .12em;
  text-transform: uppercase; color: var(--muted); }}
.site-footer .sep {{ margin: 0 10px; }}
@media (max-width: 600px) {{ .bench-grid {{ grid-template-columns: 1fr; }}
  .bench-grid > div {{ border-right: 0; }} }}
"""
    bench_html = "\n".join(
        f'<div><div class="k">{esc(k)}</div><div class="v">{esc(v)}</div></div>'
        for k, v in persona["bench"])
    blurbs_html = "\n".join(f"<p>{esc(b)}</p>" for b in [persona["blurb_main"]] + persona["blurb_more"])
    pulls = "\n".join(
        f'<p class="pull">{esc(q.split(" — ")[0])}</p>'
        f'<p class="byline">— {esc(q.split(" — ")[-1])}</p>'
        for q in persona["quotes"])
    body = f"""
<header class="hero">
  <div class="wrap">
    <span class="small">{esc(persona['city'])} · {esc(persona['trade'])} · est. {persona['founded']}</span>
    <h1>{esc(persona['name'])}</h1>
    <p class="lede">{esc(persona['tagline'])}.</p>
  </div>
</header>
<main>
  <section class="section">
    <div class="wrap">
      <span class="label">About the studio</span>
      <h2>{esc(persona['blurb_main'].split('.')[0])}.</h2>
      {blurbs_html}
    </div>
  </section>
  <section class="section">
    <div class="wrap">
      <span class="label">Currently</span>
      <div class="bench-grid">{bench_html}</div>
    </div>
  </section>
  <section class="section">
    <div class="wrap">
      <span class="label">Notes from clients</span>
      {pulls}
    </div>
  </section>
  <section class="section">
    <div class="wrap contact-row">
      <span class="label">Get in touch</span>
      <a href="mailto:hello@{esc(domain)}">hello@{esc(domain)}</a>
    </div>
  </section>
</main>
"""
    return css, body


def layout_brutalist(persona, palette, fonts, domain) -> Tuple[str, str]:
    """Brutalist mono — uppercase, hard borders, a single accent rule."""
    css = BASE_CSS + f"""
:root {{
  --bg: {palette['bg']}; --fg: {palette['fg']}; --muted: {palette['muted']};
  --rule: {palette['rule']}; --accent: {palette['accent']};
}}
body {{ background:var(--bg); color:var(--fg);
  font-family:{fonts['body']}; font-size: 15px; line-height: 1.55; }}
.frame {{ border: 2px solid var(--rule); margin: 22px;
  min-height: calc(100vh - 44px); padding: 28px; position: relative; }}
.frame::before {{ content:""; position:absolute; left:-2px; right:-2px; top: 56%;
  border-top: 2px solid var(--accent); }}
.id-row {{ display:flex; justify-content:space-between; align-items:center;
  text-transform: uppercase; letter-spacing: .14em; font-size: 12px;
  border-bottom: 2px solid var(--rule); padding-bottom: 14px; margin-bottom: 24px; }}
h1.brut {{ font-family:{fonts['head']}; font-weight: 700; text-transform: uppercase;
  letter-spacing: -.01em; font-size: clamp(40px, 9vw, 120px); line-height: .92;
  margin: 18px 0 12px; }}
.tag {{ text-transform: uppercase; letter-spacing: .18em; font-size: 13px;
  color: var(--muted); margin-bottom: 36px; max-width: 60ch; }}
.grid {{ display:grid; grid-template-columns: 1.2fr 1fr; gap: 0;
  border-top: 2px solid var(--rule); border-bottom: 2px solid var(--rule); }}
.grid > div {{ padding: 22px; }}
.grid > div + div {{ border-left: 2px solid var(--rule); }}
.grid h3 {{ text-transform: uppercase; letter-spacing: .18em; font-size: 12px;
  margin-bottom: 14px; color: var(--accent); }}
.grid p {{ font-size: 15px; margin-bottom: 12px; }}
.bench-list {{ font-size: 13px; }}
.bench-list li {{ display:flex; justify-content:space-between; gap:12px;
  padding: 8px 0; border-bottom: 1px dashed var(--rule);
  text-transform: uppercase; letter-spacing: .1em; }}
.bench-list li span:last-child {{ color: var(--muted); }}
.q-block {{ margin-top: 26px; }}
.q-block p {{ font-family:{fonts['head']}; font-size: clamp(20px,2.4vw,28px); margin-bottom: 6px; }}
.q-block .src {{ font-size: 12px; letter-spacing: .14em; text-transform: uppercase; color: var(--muted); }}
.contact {{ margin-top: 28px; }}
.contact a {{ color: var(--fg); text-decoration: underline; text-decoration-color: var(--accent); text-underline-offset: 4px; }}
.site-footer {{ margin-top: 40px; font-size: 12px; text-transform: uppercase; letter-spacing: .14em; color: var(--muted); }}
@media (max-width: 760px) {{
  .frame {{ margin: 14px; padding: 18px; }}
  .grid {{ grid-template-columns: 1fr; }}
  .grid > div + div {{ border-left: 0; border-top: 2px solid var(--rule); }}
}}
"""
    bench_html = "\n".join(f"<li><span>{esc(k)}</span><span>{esc(v)}</span></li>" for k, v in persona["bench"])
    blurbs_html = "\n".join(f"<p>{esc(b)}</p>" for b in [persona["blurb_main"]] + persona["blurb_more"])
    quotes_html = "\n".join(
        f'<div class="q-block"><p>{esc(q.split(" — ")[0])}</p>'
        f'<div class="src">— {esc(q.split(" — ")[-1])}</div></div>'
        for q in persona["quotes"])
    body = f"""
<div class="frame">
  <div class="id-row">
    <div>{esc(persona['name'])}</div>
    <div>{esc(persona['city'])} · {esc(persona['country'] or '—')} · {persona['founded']}</div>
  </div>
  <h1 class="brut">{esc(persona['name'])}</h1>
  <p class="tag">{esc(persona['tagline'])}.</p>
  <div class="grid">
    <div>
      <h3>The workshop</h3>
      {blurbs_html}
      {quotes_html}
    </div>
    <div>
      <h3>Currently</h3>
      <ul class="bench-list">{bench_html}</ul>
      <div class="contact">
        <h3 style="margin-top:24px;">Contact</h3>
        <p><a href="mailto:hello@{esc(domain)}">hello@{esc(domain)}</a></p>
        <p style="font-size:13px;color:var(--muted);">we answer in batches on Friday afternoons.</p>
      </div>
    </div>
  </div>
  <footer class="site-footer">
    © {_now().year} {esc(persona['name'])} · studio visits by appointment only
  </footer>
</div>
"""
    return css, body


def layout_boutique(persona, palette, fonts, domain) -> Tuple[str, str]:
    """Boutique — large display serif, soft palette, single column with ornament."""
    css = BASE_CSS + f"""
:root {{
  --bg: {palette['bg']}; --fg: {palette['fg']}; --muted: {palette['muted']};
  --rule: {palette['rule']}; --accent: {palette['accent']}; --card: {palette['card']};
}}
body {{ background:var(--bg); color:var(--fg);
  font-family:{fonts['body']}; font-size: 17px; line-height: 1.6; }}
.wrap {{ max-width: 720px; }}
.crest {{ text-align: center; margin: 80px auto 24px; max-width: 640px; }}
.crest .small {{ font-family:{fonts['small']}; font-size: 11px; letter-spacing: .3em;
  text-transform: uppercase; color: var(--accent); }}
.crest .swash {{ display:flex; align-items:center; justify-content:center; gap: 14px;
  color: var(--rule); margin: 18px 0 6px; }}
.crest .swash::before, .crest .swash::after {{ content:""; flex: 0 1 80px; height: 1px; background: var(--rule); }}
.crest h1 {{ font-family:{fonts['head']}; font-weight: 500;
  font-size: clamp(40px, 7vw, 84px); line-height: 1.02; letter-spacing: -.005em;
  margin: 0 0 8px; }}
.crest .lede {{ font-style: italic; color: var(--muted); font-size: 19px; }}
.section {{ padding: 28px 0 36px; }}
.section h2 {{ text-align:center; font-family:{fonts['small']}; font-size: 11px;
  letter-spacing: .3em; text-transform: uppercase; color: var(--accent);
  margin: 28px 0 22px; position: relative; }}
.section h2::before, .section h2::after {{ content:""; display:inline-block; vertical-align:middle;
  width: 36px; height: 1px; background: var(--rule); margin: 0 12px; }}
.section p {{ margin-bottom: 16px; }}
.bench {{ background: var(--card); border-radius: 6px; padding: 20px 24px; margin: 14px 0; }}
.bench li {{ display:flex; justify-content:space-between; gap:12px; padding: 9px 0;
  border-bottom: 1px dotted color-mix(in srgb, var(--rule) 35%, transparent); font-size: 15px; }}
.bench li:last-child {{ border-bottom: 0; }}
.bench li span:last-child {{ color: var(--muted); }}
.quote {{ font-family:{fonts['head']}; font-size: 22px; font-style: italic;
  text-align: center; max-width: 56ch; margin: 18px auto; line-height: 1.45;
  color: color-mix(in srgb, var(--fg) 85%, var(--bg)); }}
.byline {{ text-align: center; font-family:{fonts['small']}; font-size: 11px;
  letter-spacing: .25em; text-transform: uppercase; color: var(--muted); margin-bottom: 28px; }}
.contact {{ text-align: center; padding: 22px 0 60px; }}
.contact a {{ color: var(--accent); text-decoration: none;
  border-bottom: 1px solid var(--accent); padding-bottom: 2px; }}
.site-footer {{ text-align:center; padding: 12px 0 60px; font-size: 12px; color: var(--muted); }}
"""
    bench_html = "\n".join(f"<li><span>{esc(k)}</span><span>{esc(v)}</span></li>" for k, v in persona["bench"])
    blurbs_html = "\n".join(f"<p>{esc(b)}</p>" for b in [persona["blurb_main"]] + persona["blurb_more"])
    quotes_html = ""
    for q in persona["quotes"]:
        text, _, src = q.partition(" — ")
        quotes_html += f'<p class="quote">"{esc(text)}"</p><p class="byline">— {esc(src)}</p>'
    body = f"""
<header class="crest">
  <div class="wrap">
    <div class="small">{esc(persona['city'])} · est. {persona['founded']}</div>
    <div class="swash">·</div>
    <h1>{esc(persona['name'])}</h1>
    <p class="lede">{esc(persona['tagline'])}.</p>
  </div>
</header>
<main class="wrap">
  <section class="section">
    <h2>The workshop</h2>
    {blurbs_html}
  </section>
  <section class="section">
    <h2>Currently</h2>
    <ul class="bench">{bench_html}</ul>
  </section>
  <section class="section">
    <h2>Notes</h2>
    {quotes_html}
  </section>
  <section class="contact">
    <h2>Write to us</h2>
    <p><a href="mailto:hello@{esc(domain)}">hello@{esc(domain)}</a></p>
    <p style="color:var(--muted);font-size:14px;margin-top:8px;">We answer in batches, Friday afternoons.</p>
  </section>
</main>
"""
    return css, body


def layout_press(persona, palette, fonts, domain) -> Tuple[str, str]:
    """Press / letterpress — heavy serif, drop-cap, classical proportions."""
    css = BASE_CSS + f"""
:root {{
  --bg: {palette['bg']}; --fg: {palette['fg']}; --muted: {palette['muted']};
  --rule: {palette['rule']}; --accent: {palette['accent']}; --card: {palette['card']};
}}
body {{ background:var(--bg); color:var(--fg);
  font-family:{fonts['body']}; font-size: 18px; line-height: 1.6; }}
.head {{ padding: 56px 0 24px; border-top: 6px double var(--rule);
  border-bottom: 1px solid var(--rule); }}
.head .meta {{ display:flex; justify-content:space-between; font-family:{fonts['small']};
  text-transform: uppercase; font-size: 11px; letter-spacing: .26em; color: var(--rule); margin-bottom: 18px; }}
.head h1 {{ font-family:{fonts['head']}; font-weight: 700; font-size: clamp(44px,7vw,84px);
  letter-spacing: -.01em; line-height: 1.0; text-align:center; }}
.head .tag {{ font-style: italic; color: var(--muted); text-align:center; margin-top: 6px; }}
.row {{ padding: 38px 0; border-bottom: 1px solid var(--rule);
  display:grid; grid-template-columns: 1fr 2fr; gap: 36px; }}
.row h2 {{ font-family:{fonts['small']}; font-size: 12px; letter-spacing: .22em;
  text-transform: uppercase; color: var(--rule); }}
.row p {{ margin-bottom: 14px; max-width: 60ch; }}
.dropcap::first-letter {{ float:left; font-family:{fonts['head']}; font-size: 64px;
  line-height: .9; padding-right: 8px; padding-top: 4px; color: var(--accent); }}
.bench {{ list-style:none; padding:0; margin:0; }}
.bench li {{ display:flex; justify-content:space-between; gap:12px; padding: 10px 0;
  border-bottom: 1px dotted color-mix(in srgb, var(--rule) 35%, transparent); font-size: 16px; }}
.bench li span:last-child {{ color: var(--muted); }}
.quote {{ border-left: 3px double var(--accent); padding: 4px 0 4px 16px; font-style: italic;
  color: color-mix(in srgb, var(--fg) 85%, var(--bg)); margin-bottom: 14px; max-width: 60ch; }}
.contact a {{ color: var(--accent); text-decoration: none; border-bottom: 1px solid var(--accent); }}
.site-footer {{ padding: 24px 0 60px; font-size: 13px; color: var(--muted); text-align:center;
  border-top: 6px double var(--rule); }}
@media (max-width: 760px) {{ .row {{ grid-template-columns: 1fr; gap: 18px; }} }}
"""
    bench_html = "\n".join(f"<li><span>{esc(k)}</span><span>{esc(v)}</span></li>" for k, v in persona["bench"])
    quotes_html = "\n".join(f'<p class="quote">{esc(q)}</p>' for q in persona["quotes"])
    body = f"""
<header class="head">
  <div class="wrap">
    <div class="meta">
      <span>{esc(persona['city'])} · {esc(persona['country'] or '—')}</span>
      <span>established {persona['founded']}</span>
    </div>
    <h1>{esc(persona['name'])}</h1>
    <p class="tag">{esc(persona['tagline'])}.</p>
  </div>
</header>
<main>
  <section class="row">
    <div class="wrap" style="padding:0;"><h2>About</h2></div>
    <div class="wrap" style="padding:0;">
      <p class="dropcap">{esc(persona['blurb_main'])}</p>
      {''.join(f'<p>{esc(b)}</p>' for b in persona['blurb_more'])}
    </div>
  </section>
  <section class="row">
    <div class="wrap" style="padding:0;"><h2>Currently</h2></div>
    <div class="wrap" style="padding:0;"><ul class="bench">{bench_html}</ul></div>
  </section>
  <section class="row">
    <div class="wrap" style="padding:0;"><h2>Notes</h2></div>
    <div class="wrap" style="padding:0;">{quotes_html}</div>
  </section>
  <section class="row contact">
    <div class="wrap" style="padding:0;"><h2>Write</h2></div>
    <div class="wrap" style="padding:0;">
      <p>Letters answered in batches, Friday afternoons.</p>
      <p>· <a href="mailto:hello@{esc(domain)}">hello@{esc(domain)}</a></p>
    </div>
  </section>
</main>
"""
    return css, body


LAYOUT_RENDERERS = {
    "editorial":   layout_editorial,
    "studio_dark": layout_studio_dark,
    "brutalist":   layout_brutalist,
    "boutique":    layout_boutique,
    "press":       layout_press,
}


# =============================================================================
# Driver
# =============================================================================

def render_page(persona: Dict[str, Any], visual: Dict[str, Any], domain: str, lang: str) -> str:
    layout = visual["layout"]
    palette = visual["palette"]
    fonts = visual["fonts"]
    css, body = LAYOUT_RENDERERS[layout](persona, palette, fonts, domain)
    head = HEAD_TMPL.format(
        lang=esc(lang),
        layout=esc(layout),
        palette_name=esc(palette["name"]),
        name=esc(persona["name"]),
        tagline=esc(persona["tagline"]),
        descr=esc(f"{persona['tagline']}. {persona['blurb_main']}"),
        domain=esc(domain),
        jsonld=render_jsonld(persona, domain),
        css=css,
    )
    foot = FOOT_TMPL.format(
        year=_now().year,
        name=esc(persona["name"]),
        city=esc(persona["city"]),
        domain=esc(domain),
    )
    return head + body + foot

def render_404(persona, visual, domain) -> str:
    palette = visual["palette"]
    fonts = visual["fonts"]
    return (
f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Not here — {esc(persona['name'])}</title>
<style>
body {{ background:{palette['bg']}; color:{palette['fg']};
  font-family:{fonts['body']}; min-height:100vh; display:flex;
  align-items:center; justify-content:center; margin:0; padding:24px; }}
.box {{ max-width:520px; text-align:center; }}
h1 {{ font-family:{fonts['head']}; font-size: 64px; margin: 0 0 10px;
  color:{palette['accent']}; }}
p {{ color:{palette['muted']}; }}
a {{ color:{palette['accent']}; }}
</style></head>
<body><div class="box">
<h1>404</h1>
<p>This page is not in the workshop.</p>
<p><a href="/">Back to {esc(persona['name'])}</a></p>
</div></body></html>
""")


def derive_seed(domain: str, salt: Optional[str] = None) -> int:
    h = hashlib.sha256()
    h.update(domain.encode("utf-8"))
    if salt:
        h.update(b"|"); h.update(salt.encode("utf-8"))
    return int.from_bytes(h.digest()[:8], "big")


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate a geo-aware decoy landing page.")
    ap.add_argument("--domain", required=True, help="Public domain for this site (used in copy and links).")
    ap.add_argument("--out", required=True, help="Output directory (will be created if missing).")
    ap.add_argument("--no-network", action="store_true", help="Skip geo lookup; randomize country.")
    ap.add_argument("--country", help="Override detected country (ISO-3166-alpha-2).")
    ap.add_argument("--city", help="Override detected city name.")
    ap.add_argument("--layout", choices=LAYOUTS, help="Force a specific layout.")
    ap.add_argument("--seed", help="Deterministic seed (anything string-able). Default: domain itself.")
    ap.add_argument("--print-meta", action="store_true", help="Print chosen persona+visual metadata as JSON to stdout.")
    ap.add_argument("--meta-file", help="Also write metadata JSON to this path (outside the webroot).")
    args = ap.parse_args()

    seed = derive_seed(args.domain, args.seed)
    rng = random.Random(seed)

    if args.country or args.city:
        geo = {"country": (args.country or "").upper() or None, "city": args.city, "region": None}
    elif args.no_network:
        geo = {"country": None, "city": None, "region": None}
    else:
        geo = detect_geo()

    # NB: don't use `REGIONS.keys() - {"_"}` — set iteration order isn't stable
    # across Python runs (PYTHONHASHSEED), and the seeded rng must be deterministic.
    country = (geo.get("country") or "").upper() or rng.choice(
        [k for k in REGIONS.keys() if k != "_"])
    city = geo.get("city")

    persona = pick_persona(rng, country, city)
    visual = pick_visual(rng, args.layout)

    region = REGIONS.get(country) or REGIONS["_"]
    lang = region.get("lang", "en")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    (out / "index.html").write_text(render_page(persona, visual, args.domain, lang), encoding="utf-8")
    (out / "404.html").write_text(render_404(persona, visual, args.domain), encoding="utf-8")
    (out / "robots.txt").write_text("User-agent: *\nDisallow:\n", encoding="utf-8")
    (out / "favicon.svg").write_text(render_favicon(visual["palette"], persona), encoding="utf-8")

    meta = {
        "domain": args.domain,
        "geo": {"country": country, "city": city, "region": geo.get("region")},
        "persona": {k: persona[k] for k in
            ("archetype", "trade", "name", "city", "country", "founded", "tagline")},
        "visual": {"layout": visual["layout"],
                   "palette": visual["palette"]["name"],
                   "fonts": visual["fonts"]["name"]},
        "seed": seed,
    }
    if args.meta_file:
        meta_path = Path(args.meta_file)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.print_meta:
        print(json.dumps(meta, ensure_ascii=False, indent=2))
    else:
        print(f"[landing] {persona['name']} · {persona['trade']} · {persona['city']} ({country}) "
              f"· layout={visual['layout']} palette={visual['palette']['name']} fonts={visual['fonts']['name']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
