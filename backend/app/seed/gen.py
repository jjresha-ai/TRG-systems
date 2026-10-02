"""Deterministic data generation helpers for the demo seed (made-up but realistic Southern California CRE data)."""
import random
from datetime import date, datetime, timedelta

FIRST = ["James","Robert","Michael","William","David","Richard","Joseph","Thomas","Charles","Daniel","Mark","Steven","Paul","Kevin","Brian","George","Edward","Ronald","Anthony","Gary","Larry","Jeffrey","Frank","Scott","Eric","Raymond","Gregory","Dennis","Walter","Patrick","Peter","Harold","Douglas","Henry","Carl","Arthur","Ryan","Roger","Joe","Juan","Jack","Albert","Jonathan","Justin","Terry","Gerald","Keith","Samuel","Willie","Ralph","Mary","Patricia","Linda","Barbara","Elizabeth","Jennifer","Maria","Susan","Margaret","Dorothy","Lisa","Nancy","Karen","Betty","Helen","Sandra","Donna","Carol","Ruth","Sharon","Michelle","Laura","Sarah","Kimberly","Deborah","Jessica","Shirley","Cynthia","Angela","Melissa","Brenda","Amy","Anna","Rebecca","Virginia","Kathleen","Pamela","Martha","Debra","Amanda","Stephanie","Carolyn","Christine","Marie","Janet","Catherine","Frances","Ann","Joyce","Diane","Raj","Wei","Hiroshi","Sunil","Minh","Carlos","Luis","Jorge","Miguel","Ahmad","Daniel","Tony","Vince","Sal","Nick"]
LAST = ["Nguyen","Tran","Kim","Lee","Park","Chen","Wang","Patel","Shah","Singh","Garcia","Hernandez","Martinez","Lopez","Gonzalez","Rodriguez","Perez","Sanchez","Ramirez","Torres","Flores","Rivera","Gomez","Diaz","Reyes","Morales","Cruz","Ortiz","Gutierrez","Chavez","Ramos","Ruiz","Mendoza","Vargas","Castillo","Smith","Johnson","Williams","Brown","Jones","Miller","Davis","Wilson","Anderson","Taylor","Thomas","Moore","Jackson","Martin","Thompson","White","Harris","Clark","Lewis","Robinson","Walker","Young","Allen","King","Wright","Scott","Hill","Green","Adams","Baker","Nelson","Carter","Mitchell","Roberts","Turner","Phillips","Campbell","Parker","Evans","Edwards","Collins","Stewart","Morris","Murphy","Cook","Rogers","Morgan","Cooper","Peterson","Reed","Bailey","Bell","Kelly","Howard","Ward","Cox","Richardson","Wood","Watson","Brooks","Bennett","Gray","James","Hughes","Price","Sanders","Rossi","Romano","Moretti","Bianchi","Costa","Silva","Takahashi","Yamamoto","Tanaka","Nakamura","Sato","Cohen","Levy","Goldberg","Friedman","Schwartz","Kaplan","Ostrowski","Kowalski","Dimitrov","Petrosyan","Hovsepian","Karapetyan","Sargsyan","Boyle","Sullivan","O'Brien","Donovan","Fitzgerald"]
STREETS = ["Harbor Blvd","Beach Blvd","Brookhurst St","Main St","Katella Ave","Chapman Ave","Orangethorpe Ave","Lincoln Ave","La Palma Ave","Imperial Hwy","Valley View St","Magnolia Ave","Bolsa Ave","Edinger Ave","McFadden Ave","First St","Dyer Rd","Warner Ave","Sand Canyon Ave","Culver Dr","Jamboree Rd","Barranca Pkwy","Alton Pkwy","Irvine Center Dr","Bake Pkwy","Trabuco Rd","Lake Forest Dr","El Toro Rd","Marguerite Pkwy","Crown Valley Pkwy","Pacific Coast Hwy","Anaheim Blvd","Euclid St","Ball Rd","Lakeview Ave","Kraemer Blvd","Tustin Ave","Yorba Linda Blvd","Carson St","Sepulveda Blvd","Western Ave","Figueroa St","Alameda St","Slauson Ave","Telegraph Rd","Rosecrans Ave","Artesia Blvd","Foothill Blvd","Archibald Ave","Haven Ave","Milliken Ave","Etiwanda Ave","Valley Blvd","Mission Blvd","Vineyard Ave","Philadelphia St","Holt Blvd","Francis St","Merrill Ave","Sixth St","Central Ave","Van Buren Blvd","Indiana Ave","Madison St","Cajalco Rd","Rancho California Rd","Winchester Rd","Jefferson Ave","El Camino Real","Rancho Bernardo Rd","Mira Mesa Blvd","Miramar Rd","Palomar Airport Rd","Escondido Blvd","Broadway","Otay Lakes Rd"]
AREAS = [  # city, county, market, submarket, zip prefix, area code, lat, lng
    ("Irvine","Orange","Orange County","Central OC","92618","949",33.68,-117.82),("Anaheim","Orange","Orange County","North OC","92805","714",33.84,-117.91),
    ("Santa Ana","Orange","Orange County","Central OC","92705","714",33.75,-117.87),("Tustin","Orange","Orange County","Central OC","92780","714",33.74,-117.82),
    ("Costa Mesa","Orange","Orange County","Central OC","92626","714",33.66,-117.92),("Fullerton","Orange","Orange County","North OC","92831","714",33.87,-117.92),
    ("Orange","Orange","Orange County","Central OC","92867","714",33.79,-117.85),("Garden Grove","Orange","Orange County","West OC","92840","714",33.77,-117.94),
    ("Huntington Beach","Orange","Orange County","West OC","92647","714",33.66,-118.0),("Lake Forest","Orange","Orange County","South OC","92630","949",33.65,-117.69),
    ("Mission Viejo","Orange","Orange County","South OC","92691","949",33.6,-117.67),("Laguna Hills","Orange","Orange County","South OC","92653","949",33.61,-117.71),
    ("Brea","Orange","Orange County","North OC","92821","714",33.92,-117.9),("Placentia","Orange","Orange County","North OC","92870","714",33.87,-117.87),
    ("Cypress","Orange","Orange County","West OC","90630","714",33.82,-118.04),("Buena Park","Orange","Orange County","North OC","90620","714",33.87,-117.99),
    ("Torrance","Los Angeles","Los Angeles","South Bay","90501","310",33.84,-118.34),("Carson","Los Angeles","Los Angeles","South Bay","90745","310",33.83,-118.26),
    ("Long Beach","Los Angeles","Los Angeles","South Bay","90805","562",33.8,-118.19),("Gardena","Los Angeles","Los Angeles","South Bay","90248","310",33.89,-118.31),
    ("Commerce","Los Angeles","Los Angeles","Mid-Counties","90040","323",34.0,-118.15),("Santa Fe Springs","Los Angeles","Los Angeles","Mid-Counties","90670","562",33.95,-118.08),
    ("Pasadena","Los Angeles","Los Angeles","San Gabriel Valley","91101","626",34.15,-118.14),("Glendale","Los Angeles","Los Angeles","San Fernando Valley","91203","818",34.14,-118.26),
    ("Ontario","San Bernardino","Inland Empire","IE West","91761","909",34.06,-117.65),("Rancho Cucamonga","San Bernardino","Inland Empire","IE West","91730","909",34.1,-117.58),
    ("Fontana","San Bernardino","Inland Empire","IE West","92335","909",34.09,-117.43),("Chino","San Bernardino","Inland Empire","IE West","91710","909",34.01,-117.69),
    ("Riverside","Riverside","Inland Empire","IE East","92507","951",33.95,-117.4),("Corona","Riverside","Inland Empire","IE East","92879","951",33.88,-117.57),
    ("Temecula","Riverside","Inland Empire","IE South","92590","951",33.49,-117.15),("Murrieta","Riverside","Inland Empire","IE South","92562","951",33.55,-117.21),
    ("San Diego","San Diego","San Diego","Central SD","92123","858",32.8,-117.15),("Carlsbad","San Diego","San Diego","North County","92008","760",33.16,-117.35),
    ("Oceanside","San Diego","San Diego","North County","92054","760",33.2,-117.38),("Escondido","San Diego","San Diego","North County","92025","760",33.12,-117.09),
    ("Chula Vista","San Diego","San Diego","South Bay SD","91910","619",32.64,-117.08),("El Cajon","San Diego","San Diego","East County","92020","619",32.79,-116.96),
]
HOME_AREAS = [a for a in AREAS if a[0] in {"Irvine","Newport Beach","Laguna Hills","Mission Viejo","Orange","Tustin","Fullerton","Huntington Beach","Torrance","Carlsbad","Brea","Costa Mesa","Pasadena","Riverside"}]
FAM_PREFIX = ["Pacific","Coastal","Harbor","Golden State","Sunset","Orange Grove","Foothill","Seabright","Bluff","Canyon","Heritage","Cornerstone","Keystone","Summit","Ridgeline","Crown","Bayview","Laurel","Sycamore","Mesa","Tri-City","Southland","Cal-West","Westridge","Eastgate","Monarch","Lighthouse","Redwood","Ironwood","Pinnacle"]
FAM_SUFFIX = ["Holdings","Properties","Investments","Partners","Capital","Realty","Ventures","Asset Group","Equities","Real Estate"]
RETAIL_SUBTYPES = [("Neighborhood Center",(40000,140000),(260,420)),("Strip Center",(8000,35000),(300,520)),("Single-Tenant NNN",(2500,14000),(450,1100)),("Street Retail",(4000,18000),(380,700)),("Pad / Drive-thru",(2000,5500),(700,1500)),("Grocery-Anchored",(60000,180000),(300,480))]
IND_SUBTYPES = [("Warehouse / Distribution",(40000,320000),(190,320)),("Light Industrial / Flex",(8000,60000),(230,380)),("Multi-Tenant Industrial",(20000,120000),(210,340)),("Manufacturing",(25000,150000),(160,260)),("Industrial Outdoor Storage",(0,0),(0,0)),("R&D / Office-Flex",(10000,50000),(240,360))]
SOURCES = ["CoStar export","County records","Referral","Past client","Industry event","Inbound web","Cold call list","Sperry network","LinkedIn","Broker referral"]
LENDERS = ["Wells Fargo","Bank of America","Pacific Premier Bank","Banc of California","Cathay Bank","East West Bank","CIT Bank","Citizens Business Bank","Torrey Pines Bank","Mechanics Bank","Northmarq (CMBS)","JPMorgan (CMBS)","MetLife","Pacific Western Bank","City National Bank","Farmers & Merchants Bank","Axos Bank","Hanmi Bank"]
TENANTS = ["Dollar Tree","7-Eleven","CVS Pharmacy","AutoZone","Starbucks","Chipotle","O'Reilly Auto","Sprouts","Ross Dress for Less","Planet Fitness","Smart & Final","Petco","Jack in the Box","Wendy's","Walgreens","Panera","Raising Cane's","Chase Bank"]


def rnd(a, b):
    return random.randint(a, b)


def pick(seq):
    return random.choice(seq)


def phone(area=None):
    return f"({area or pick(['949','714','562','310','909','951','760','858','619','626'])}) {rnd(200,989)}-{rnd(1000,9999)}"


def street_address():
    return f"{rnd(100, 28999)} {pick(STREETS)}"


def day(years_ago_min: float, years_ago_max: float, today: date | None = None) -> date:
    today = today or date.today()
    return today - timedelta(days=rnd(int(years_ago_min * 365), int(years_ago_max * 365)))


def dt_last_year(today: date | None = None) -> datetime:
    today = today or date.today()
    return datetime.combine(today - timedelta(days=rnd(0, 364)), datetime.min.time()) + timedelta(hours=rnd(7, 18), minutes=rnd(0, 59))
