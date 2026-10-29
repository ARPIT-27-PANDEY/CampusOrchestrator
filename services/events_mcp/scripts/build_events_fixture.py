"""Build events_mcp/data/demo_events.json.

Two kinds of records:

* ``origin: official`` - transcribed by hand from IIT Roorkee academic calendar PDFs
  (see DOCUMENTS; page numbers refer to those PDFs). Absolute dates, all-day.
  Spring 2025-26 rows 27-33 repeat July 2026 rows that the newer Autumn 2026-27 calendar also
  lists; they are taken from the Autumn calendar only. Spring row 33 ("Convocation-2026: first
  week of September") is superseded by Autumn row 12 ("19.09.2026 OR 26.09.2026, final date to be
  notified"), which is recorded as tentative rather than as a fixed date.
* ``origin: synthetic`` - invented demo events (workshops, talks, contests, sports...) with dates
  relative to the campus clock, used to exercise statuses, registration states, recurrence,
  concurrency and timing. They are NOT IIT Roorkee announcements; organisers carry "(demo)".

Run:  python services/events_mcp/scripts/build_events_fixture.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

OUT = Path(__file__).resolve().parents[1] / "events_mcp" / "data" / "demo_events.json"
LOCK = Path(__file__).resolve().parents[2] / "academics_mcp" / "data" / "sources" / "iitr_sources.lock.json"

DOCUMENTS: dict[str, dict[str, Any]] = {
    "iitr-calendar-autumn-2026-27": {
        "title": "Academic Calendar, Autumn Semester 2026-27: All Programs (Other than MBA), IIT Roorkee",
        "url": "https://iitr.ac.in/Academics/static/Calendar/Autumn%202026-27/Autumn_Calander_2026-27_All_Programme_other_than_MBA.pdf",
        "issued": "2026-04-06",
    },
    "iitr-calendar-spring-2025-26": {
        "title": "Academic Calendar, Spring Semester 2025-26: All Programs (Other than MBA), IIT Roorkee",
        "url": "https://iitr.ac.in/Academics/static/Calendar/Spring%202025-26/All_Programs_Other_than_MBA_Spring_Calendar_2025-26.pdf",
        "issued": "2025-11-26",
    },
}

# (row, title, start, end or None, category, tags) - dates exactly as printed (DD.MM.YYYY).
AUTUMN_2026: list[tuple[str, str, str, str | None, str, list[str]]] = [
    ("01", "Admission cum Academic Registration for new Ph.D. and Masters' students", "14.07.2026", None, "registration", ["registration", "phd", "masters", "admission"]),
    ("02", "Academic Registration for existing students in physical mode", "14.07.2026", "15.07.2026", "registration", ["registration"]),
    ("03", "Orientation Program for new Ph.D. and Masters' students", "15.07.2026", None, "orientation", ["orientation", "phd", "masters"]),
    ("04", "Commencement of Classes (except UG I year)", "16.07.2026", None, "academic", ["classes", "semester start"]),
    ("05", "Re-examination and second examination (for Spring Semester 2025-26)", "16.07.2026", "18.07.2026", "examination", ["exam", "re-examination", "second examination"]),
    ("06", "Academic Registration for new UG students (subject to JoSAA counselling)", "24.07.2026", None, "registration", ["registration", "ug", "first year"]),
    ("07a", "Orientation Program - Newly Admitted UG Students (part 1)", "25.07.2026", "26.07.2026", "orientation", ["orientation", "ug", "first year"]),
    ("07b", "Orientation Program - Newly Admitted UG Students (part 2)", "01.08.2026", "02.08.2026", "orientation", ["orientation", "ug", "first year"]),
    ("08", "Commencement of Classes for UG I year (subject to JoSAA counselling)", "27.07.2026", None, "academic", ["classes", "first year", "ug"]),
    ("09", "Last date for Academic Registration with a late fine", "31.07.2026", None, "deadline", ["registration", "deadline", "late fine"]),
    ("10", "Last date for adding/changing courses for all programs", "03.08.2026", None, "deadline", ["courses", "deadline", "add drop"]),
    ("11", "Last date for submission of mandatory documents for newly admitted students", "27.08.2026", None, "deadline", ["documents", "deadline"]),
    ("13", "Mid-Term Examinations (except Sunday)", "10.09.2026", "15.09.2026", "examination", ["exam", "mid-term", "mte"]),
    ("14", "Last date for informing the students about performance in MTE and internal assessment", "28.09.2026", None, "deadline", ["mte", "marks", "deadline"]),
    ("15", "Submission of the feedback/response form - I on the online portal", "28.09.2026", "01.10.2026", "academic", ["feedback"]),
    ("16", "Sangram 2026", "03.10.2026", "04.10.2026", "sports", ["sports", "fest", "sangram"]),
    ("17", "Last date for withdrawal of courses", "05.10.2026", None, "deadline", ["courses", "withdrawal", "deadline"]),
    ("18", "Thomso 2026", "09.10.2026", "11.10.2026", "cultural", ["cultural", "fest", "thomso"]),
    ("19", "Submission of the feedback/response form - II on the online portal", "05.11.2026", "11.11.2026", "academic", ["feedback"]),
    ("20", "Last date of teaching", "11.11.2026", None, "academic", ["teaching", "semester end"]),
    ("21", "End Term Examinations (excluding Sunday and declared holidays)", "13.11.2026", "24.11.2026", "examination", ["exam", "end-term", "ete"]),
    ("22", "Institute Foundation Day", "25.11.2026", None, "institute", ["foundation day"]),
    ("23", "Last date of showing the End Term Examinations answer scripts", "01.12.2026", None, "deadline", ["exam", "answer scripts", "deadline"]),
    ("24", "Last date of electronic communication of grades to students", "03.12.2026", None, "deadline", ["grades", "deadline"]),
    ("25", "Last date for students to apply for grade revision, if any", "04.12.2026", None, "deadline", ["grades", "grade revision", "deadline"]),
    ("26", "Winter vacation for UG students (except IDD final Year)", "05.12.2026", "06.01.2027", "vacation", ["vacation", "winter", "ug"]),
    ("27", "Last date for the evaluation of Project/Thesis/Seminar for all programs", "03.12.2026", None, "deadline", ["project", "thesis", "deadline"]),
    ("28", "Last date for sending final grades to AAO", "08.12.2026", None, "deadline", ["grades", "deadline"]),
    ("29", "Last date for the submission of Progress Reports (Ph.D. students) to the AAO", "09.12.2026", None, "deadline", ["phd", "progress report", "deadline"]),
    ("30", "Online Choices for branch change", "10.12.2026", "14.12.2026", "academic", ["branch change"]),
    ("31", "Declaration of the final list of branch change (Tentative Date)", "31.12.2026", None, "academic", ["branch change"]),
    ("32", "Admission cum Academic Registration for New Ph.D. Students (Spring Semester 2026-27)", "07.01.2027", None, "registration", ["registration", "phd"]),
    ("33", "Academic registration of all existing students for Spring Semester 2026-27 in physical mode", "07.01.2027", "08.01.2027", "registration", ["registration", "spring"]),
    ("34", "Commencement of classes for Spring Semester 2026-27", "11.01.2027", None, "academic", ["classes", "semester start", "spring"]),
    ("35", "Re-examination and Second examination (for Autumn Semester 2026-27)", "11.01.2027", "13.01.2027", "examination", ["exam", "re-examination", "second examination"]),
]  # fmt: skip
AUTUMN_2026_PAGE2: list[tuple[str, str, str, str | None, str, list[str]]] = [
    ("TT1", "Time-table rescheduling: Fridays' time table on Wednesday (all programs)", "23.09.2026", None, "timetable", ["timetable", "rescheduling"]),
    ("TT2", "Time-table rescheduling: Fridays' time table on Wednesday (all programs)", "28.10.2026", None, "timetable", ["timetable", "rescheduling"]),
    ("H01", "Holiday: Independence Day", "15.08.2026", None, "holiday", ["holiday"]),
    ("H02", "Holiday: Id-e-Milad (Prophet Mohammad's Birthday) - subject to moon sighting", "26.08.2026", None, "holiday", ["holiday"]),
    ("H03", "Holiday: Raksha Bandhan", "28.08.2026", None, "holiday", ["holiday"]),
    ("H04", "Holiday: Janamashtami", "04.09.2026", None, "holiday", ["holiday"]),
    ("H05", "Holiday: Mahatma Gandhi's Birthday", "02.10.2026", None, "holiday", ["holiday"]),
    ("H06", "Holiday: Mahashtami", "19.10.2026", None, "holiday", ["holiday"]),
    ("H07", "Holiday: Mahanavmi/Dussehra (Vijaydashmi)", "20.10.2026", None, "holiday", ["holiday", "dussehra"]),
    ("H08", "Holiday: Diwali (Deepavali)", "08.11.2026", None, "holiday", ["holiday", "diwali"]),
    ("H09", "Holiday: Govardhan Puja", "09.11.2026", None, "holiday", ["holiday"]),
    ("H10", "Holiday: Guru Nanak's Birthday", "24.11.2026", None, "holiday", ["holiday"]),
    ("H11", "Holiday: Christmas Day", "25.12.2026", None, "holiday", ["holiday", "christmas"]),
]  # fmt: skip
SPRING_2026: list[tuple[str, str, str, str | None, str, list[str]]] = [
    ("01", "Admission cum Academic Registration for new Ph.D. students", "08.01.2026", None, "registration", ["registration", "phd"]),
    ("02", "Academic Registration for existing students for Spring Semester 2025-26", "08.01.2026", "09.01.2026", "registration", ["registration"]),
    ("03", "Commencement of Classes for Spring Semester 2025-26", "12.01.2026", None, "academic", ["classes", "semester start"]),
    ("04", "Re-examination and second examination (for Autumn Semester 2025-26)", "12.01.2026", "14.01.2026", "examination", ["exam", "re-examination"]),
    ("05", "Last date for sending the grades of Re-examination and second examination for Autumn Semester 2025-26", "19.01.2026", None, "deadline", ["grades", "deadline"]),
    ("06", "Last date for Academic Registration with a late fine", "23.01.2026", None, "deadline", ["registration", "deadline"]),
    ("07", "Last date for adding/changing courses for all programs", "27.01.2026", None, "deadline", ["courses", "deadline"]),
    ("08", "Last date for submission of mandatory documents for newly admitted Ph.D. students", "13.02.2026", None, "deadline", ["documents", "phd", "deadline"]),
    ("09", "Mid-Term Examinations (except Sunday)", "26.02.2026", "03.03.2026", "examination", ["exam", "mid-term", "mte"]),
    ("10", "National Science Day", "28.02.2026", None, "institute", ["science day"]),
    ("11", "Mid Term Break", "04.03.2026", "08.03.2026", "vacation", ["break"]),
    ("12", "Last date for informing the students about performance in MTE and internal assessment", "11.03.2026", None, "deadline", ["mte", "deadline"]),
    ("13", "Submission of the feedback/response form - I on the online portal", "11.03.2026", "13.03.2026", "academic", ["feedback"]),
    ("14", "Institute Research Day", "13.03.2026", None, "institute", ["research day"]),
    ("15", "Cognizance-2026 (tentative)", "13.03.2026", "15.03.2026", "technical", ["fest", "cognizance", "technical"]),
    ("16", "Last date for withdrawal of courses", "27.04.2026", None, "deadline", ["courses", "withdrawal", "deadline"]),
    ("17", "Submission of the feedback/response form - II on the online portal", "28.04.2026", "30.04.2026", "academic", ["feedback"]),
    ("18", "Last date of teaching", "30.04.2026", None, "academic", ["teaching"]),
    ("19", "End Term Examinations (excluding Sunday)", "02.05.2026", "11.05.2026", "examination", ["exam", "end-term"]),
    ("20", "Last date of showing the End Term Examinations answer scripts", "18.05.2026", None, "deadline", ["exam", "deadline"]),
    ("21", "Last date of electronic communication of grades to students", "21.05.2026", None, "deadline", ["grades", "deadline"]),
    ("22", "Last date for students to apply for grade revision, if any", "23.05.2026", None, "deadline", ["grades", "deadline"]),
    ("23", "Last date for the evaluation of Project/Thesis/Seminar for all programs", "28.05.2026", None, "deadline", ["project", "deadline"]),
    ("24", "Last date for sending final grades to AAO", "29.05.2026", None, "deadline", ["grades", "deadline"]),
    ("25", "Last date for submission of the progress report for the PhD Students", "05.06.2026", None, "deadline", ["phd", "deadline"]),
    ("26", "Summer vacation for UG students (except IDD final Year)", "19.05.2026", "14.07.2026", "vacation", ["vacation", "summer"]),
]  # fmt: skip
SPRING_2026_PAGE2 = [
    ("H01", "Holiday: Republic Day", "26.01.2026", None, "holiday", ["holiday"]),
    ("H02", "Holiday: Holi", "04.03.2026", None, "holiday", ["holiday", "holi"]),
    ("H03", "Holiday: Idu'l Fitr - subject to moon sighting", "21.03.2026", None, "holiday", ["holiday"]),
    ("H04", "Holiday: Mahavir Jayanti", "31.03.2026", None, "holiday", ["holiday"]),
    ("H05", "Holiday: Good Friday", "03.04.2026", None, "holiday", ["holiday"]),
    ("H06", "Holiday: Buddha Purnima", "01.05.2026", None, "holiday", ["holiday"]),
    ("H07", "Holiday: Idu'l Zuha (Bakrid) - subject to moon sighting", "27.05.2026", None, "holiday", ["holiday"]),
    ("H08", "Holiday: Muharram - subject to moon sighting", "26.06.2026", None, "holiday", ["holiday"]),
]  # fmt: skip


def _iso(ddmmyyyy: str) -> str:
    d, m, y = ddmmyyyy.split(".")
    return f"{y}-{m}-{d}"


def official(prefix: str, doc: str, page: int, rows: list[tuple[str, str, str, str | None, str, list[str]]]) -> list[dict[str, Any]]:  # fmt: skip
    out = []
    for row, title, start, end, category, tags in rows:
        rec: dict[str, Any] = {
            "event_id": f"{prefix}-{row}",
            "origin": "official",
            "document": doc,
            "page": page,
            "title": title,
            "category": category,
            "tags": tags,
            "date": _iso(start),
            "all_day": True,
            "organizer": "Academic Affairs Office, IIT Roorkee",
            "location": "IIT Roorkee",
            "registration_status": "unknown",
        }
        if end:
            rec["end_date"] = _iso(end)
        out.append(rec)
    return out


CONVOCATION = {
    "event_id": "IITR-A26-12",
    "origin": "official",
    "document": "iitr-calendar-autumn-2026-27",
    "page": 1,
    "title": "Convocation 2026",
    "category": "institute",
    "tags": ["convocation", "degree"],
    "date": "2026-09-19",
    "all_day": True,
    "tentative": True,
    "date_note": "The calendar lists 19.09.2026 OR 26.09.2026; the final date will be notified in due course.",
    "organizer": "IIT Roorkee",
    "location": "IIT Roorkee",
    "registration_status": "unknown",
}


def ev(event_id: str, title: str, category: str, offset: int, start: str, minutes: int, **kw: Any) -> dict[str, Any]:
    return {"event_id": event_id, "origin": "synthetic", "title": title, "category": category,
            "day_offset": offset, "start_time": start, "duration_minutes": minutes, **kw}  # fmt: skip


# Synthetic demo events. EVT-101..112 keep their original ids, offsets and times (tests rely on them);
# EVT-109 ("Mid-Semester Examination Week Begins") was removed: it invented an academic date that
# contradicted the official calendar.
SYNTHETIC: list[dict[str, Any]] = [
    ev("EVT-101", "Hands-on AI Workshop: Building Tool-Using Agents with MCP", "workshop", 3, "14:00", 180,
       tags=["ai", "artificial intelligence", "agents", "mcp", "llm", "workshop"], location="CS Building, Lab 2.14",
       organizer="AI & Data Science Club (demo)", registration_required=True, registration_status="open", capacity=40,
       registration_deadline_offset=2,
       description="Build a small agent that discovers tools over the Model Context Protocol. Part of the AI Workshop "
                   "Series; see the Academic Handbook for the series prerequisite."),
    ev("EVT-102", "Intro to Machine Learning Workshop", "workshop", 10, "10:00", 120,
       tags=["ai", "machine learning", "ml", "python", "workshop"], location="Library Seminar Room A",
       organizer="Department of Computer Science (demo)", registration_required=True, registration_status="open",
       capacity=60, description="Gentle introduction to supervised learning with scikit-learn. Part of the AI Workshop Series."),
    ev("EVT-103", "Campus Career Fair: Software & Data Roles", "career", 6, "09:30", 420,
       tags=["career", "internship", "jobs", "software", "data", "recruitment"], location="Main Auditorium",
       organizer="Career Services (demo)", registration_required=False, registration_status="not_required",
       description="Meet recruiters hiring for SDE and data analytics internships."),
    ev("EVT-104", "Guest Lecture: Retrieval-Augmented Generation in Practice", "lecture", 8, "16:00", 90,
       tags=["ai", "rag", "llm", "lecture", "talk"], location="Lecture Hall 3", organizer="CSE Department (demo)",
       registration_required=False, registration_status="not_required", capacity=200,
       description="How retrieval, citations and evaluation make LLM answers trustworthy."),
    ev("EVT-105", "24-Hour Campus Hackathon", "competition", 17, "09:00", 1440,
       tags=["hackathon", "coding", "competition"], location="Innovation Hub", organizer="Coding Club (demo)",
       registration_required=True, registration_status="open", capacity=120, registration_deadline_offset=12,
       description="Teams of up to four build a working prototype in 24 hours."),
    ev("EVT-106", "Competitive Programming Contest (Div. 2)", "competition", 5, "18:00", 150,
       tags=["competitive programming", "contest", "coding"], location="Online / CS Lab 1.02",
       online_url="https://example.org/demo-contest", organizer="Coding Club (demo)",
       registration_required=True, registration_status="open"),
    ev("EVT-107", "Autumn Cultural Night", "cultural", 12, "18:30", 180, tags=["cultural", "music", "dance"],
       location="Open Air Theatre", organizer="Cultural Council (demo)", registration_required=False,
       registration_status="not_required", description="Music and dance performances by student societies."),
    ev("EVT-108", "Library Research Skills Session", "workshop", 2, "11:00", 60,
       tags=["library", "research", "citations", "workshop"], location="Main Library, Training Room",
       organizer="Library (demo)", registration_required=False, registration_status="not_required", capacity=30,
       description="Searching databases, maintaining references and training on citation tools."),
    ev("EVT-110", "Deep Learning Reading Group", "lecture", -4, "17:00", 60, tags=["deep learning", "reading group", "ai"],
       location="CS Building, Room 3.01", organizer="AI & Data Science Club (demo)", registration_required=False,
       registration_status="not_required", capacity=25, recurrence="Weekly",
       description="Weekly paper discussion."),
    ev("EVT-111", "Data Visualization with Python Workshop", "workshop", 14, "14:00", 120,
       tags=["python", "data visualization", "workshop"], location="CS Lab 1.04", organizer="Data Science Club (demo)",
       registration_required=True, registration_status="closed", capacity=35,
       description="Matplotlib and Plotly basics. Registration is full."),
    ev("EVT-112", "Inter-Department Football Final", "sports", 9, "16:30", 120, tags=["football", "sports"],
       location="Main Sports Ground", organizer="Sports Council (demo)", registration_required=False,
       registration_status="not_required"),
    # --- additional synthetic coverage -------------------------------------------------------------------------------
    ev("EVT-113", "Robotics Workshop: Line-Following Bots", "workshop", 0, "15:00", 120,
       tags=["robotics", "electronics", "workshop", "arduino"], location="Electronics Lab (demo)",
       organizer="Robotics Club (demo)", registration_required=True, registration_status="open", capacity=30),
    ev("EVT-114", "Night Sky Observation Session", "club", 0, "22:30", 180, tags=["astronomy", "club"],
       location="Main Sports Ground", organizer="Astronomy Club (demo)", registration_required=False,
       registration_status="not_required", description="Runs past midnight."),
    ev("EVT-115", "Seminar: Earthquake-Resistant Structures", "seminar", 0, "15:00", 90,
       tags=["civil engineering", "earthquake", "structures", "seminar"], location="Civil Engg. Seminar Hall (demo)",
       organizer="Civil Engineering Society (demo)", registration_status="unknown"),
    ev("EVT-116", "Startup Pitch Practice", "entrepreneurship", 1, "17:00", 120,
       tags=["entrepreneurship", "startup", "pitch"], location="Incubation Centre (demo)",
       organizer="Entrepreneurship Cell (demo)", registration_required=True, registration_status="open", capacity=20),
    ev("EVT-117", "Thermodynamics Doubt-Clearing Session", "academic", 1, "18:00", 60,
       tags=["thermodynamics", "mechanical", "tutorial"], location="LHC Room 101 (demo)",
       organizer="Mechanical Engineering Society (demo)"),
    ev("EVT-118", "Chess Blitz Tournament", "sports", 2, "19:00", 150, tags=["chess", "sports", "tournament"],
       location="Student Activity Centre (demo)", organizer="Chess Club (demo)", registration_required=True,
       registration_status="open"),
    ev("EVT-119", "Cybersecurity Capture-the-Flag", "competition", 4, "10:00", 480,
       tags=["cybersecurity", "ctf", "competition", "security"], location="Online",
       online_url="https://example.org/demo-ctf", organizer="Security Club (demo)", registration_required=True,
       registration_status="open", capacity=200),
    ev("EVT-120", "Guest Talk: Careers in Power Systems", "lecture", 4, "16:00", 60,
       tags=["electrical", "power systems", "career", "talk"], location="EE Seminar Room (demo)",
       organizer="Electrical Engineering Society (demo)", status="cancelled",
       description="Cancelled by the organisers."),
    ev("EVT-121", "Photography Walk", "club", 3, "07:00", 120, tags=["photography", "club"],
       location="Campus main gate (demo)", organizer="Photography Club (demo)", status="rescheduled",
       original_day_offset=1, original_start_time="07:00", registration_status="not_required"),
    ev("EVT-122", "Pre-Placement Talk: Analytics Firm", "career", 7, "18:00", 90,
       tags=["placement", "recruitment", "career", "ppt"], location="LHC Auditorium (demo)",
       organizer="Placement Office (demo)", registration_required=True, registration_status="closed"),
    ev("EVT-123", "Debate: Should Exams Be Open-Book?", "cultural", 7, "18:00", 90,
       tags=["debate", "literary"], location="Student Activity Centre (demo)", organizer="Literary Society (demo)"),
    ev("EVT-124", "Basketball League Match", "sports", 8, "17:30", 90, tags=["basketball", "sports"],
       location="Basketball Courts (demo)", organizer="Sports Council (demo)", registration_status="not_required"),
    ev("EVT-125", "Signals and Systems Problem-Solving Marathon", "academic", 11, "14:00", 240,
       tags=["signals and systems", "electronics", "ece", "tutorial"], location="ECE Tutorial Room (demo)",
       organizer="ECE Society (demo)"),
    ev("EVT-126", "Open Mic Evening", "cultural", 13, "19:00", 120, tags=["music", "poetry", "cultural"],
       location="Cafe Lawn (demo)", organizer="Music Club (demo)", registration_required=False,
       registration_status="not_required"),
    ev("EVT-127", "Environmental Awareness Tree Plantation", "social", 15, "08:00", 120,
       tags=["environment", "sustainability", "social"], location="Campus Green Belt (demo)",
       organizer="Environment Club (demo)", registration_required=False, registration_status="not_required"),
    ev("EVT-128", "Mock Interview Clinic", "career", 16, "10:00", 360, tags=["career", "interview", "placement"],
       location="Career Centre (demo)", organizer="Career Services (demo)", registration_required=True,
       registration_status="open", capacity=50),
    ev("EVT-129", "Hackathon Kick-off Briefing", "competition", 16, "18:00", 45, tags=["hackathon", "briefing"],
       location="Innovation Hub", organizer="Coding Club (demo)"),
    ev("EVT-130", "Badminton Doubles Open", "sports", 19, "09:00", 2880, tags=["badminton", "sports", "tournament"],
       location="Indoor Sports Hall (demo)", organizer="Sports Council (demo)", registration_required=True,
       registration_status="open", description="Two-day tournament."),
    ev("EVT-131", "Quantum Computing Reading Group", "lecture", 3, "17:00", 60, tags=["quantum", "physics", "reading group"],
       location="Physics Dept. Room (demo)", organizer="Physics Society (demo)", recurrence="Weekly"),
    ev("EVT-132", "Alumni Talk: Building a Hardware Startup", "lecture", -2, "18:00", 60,
       tags=["alumni", "startup", "hardware"], location="LHC Room 201 (demo)",
       organizer="Entrepreneurship Cell (demo)", status="completed"),
    ev("EVT-133", "Surveying Field Practice Briefing", "academic", 5, "09:00", 60, tags=["surveying", "civil engineering"],
       location="Civil Engg. Lab (demo)", organizer="Civil Engineering Society (demo)"),
    ev("EVT-134", "Psychology of Learning: Public Lecture", "lecture", 6, "17:00", 75, tags=["psychology", "lecture"],
       location="LHC Room 102 (demo)", organizer="HSS Society (demo)"),
    ev("EVT-135", "Inter-Hostel Quiz", "cultural", 9, "16:30", 120, tags=["quiz", "cultural"],
       location="LHC Auditorium (demo)", organizer="Quiz Club (demo)"),
    ev("EVT-136", "Embedded Systems Workshop (Online)", "workshop", 20, "19:00", 120,
       tags=["embedded systems", "electronics", "workshop", "online"], location="Online",
       online_url="https://example.org/demo-embedded", organizer="Electronics Club (demo)",
       registration_required=True, registration_status="open"),
    ev("EVT-137", "Fluid Mechanics Lab Demo", "academic", 22, "11:00", 90, tags=["fluid mechanics", "mechanical", "lab"],
       location="Hydraulics Lab (demo)", organizer="Mechanical Engineering Society (demo)"),
    ev("EVT-138", "Drama Club Production", "cultural", 25, "19:00", 150, tags=["drama", "theatre", "cultural"],
       location="Open Air Theatre", organizer="Dramatics Society (demo)", registration_status="not_required"),
    ev("EVT-139", "Yoga Morning", "wellness", 1, "06:30", 60, tags=["yoga", "wellness", "health"],
       location="Sports Ground (demo)", organizer="Wellness Centre (demo)", recurrence="Daily",
       registration_status="not_required"),
    ev("EVT-140", "Linear Algebra Revision Session", "academic", 3, "17:00", 90,
       tags=["linear algebra", "mathematics", "tutorial"], location="Maths Dept. Room (demo)",
       organizer="Mathematics Society (demo)"),
]  # fmt: skip


def main() -> None:
    lock = json.loads(LOCK.read_text(encoding="utf-8")) if LOCK.exists() else {}
    docs = {k: {**v, "sha256": lock.get(k, {}).get("sha256")} for k, v in DOCUMENTS.items()}
    events = [
        *official("IITR-A26", "iitr-calendar-autumn-2026-27", 1, AUTUMN_2026),
        CONVOCATION,
        *official("IITR-A26", "iitr-calendar-autumn-2026-27", 2, AUTUMN_2026_PAGE2),
        *official("IITR-S26", "iitr-calendar-spring-2025-26", 1, SPRING_2026),
        *official("IITR-S26", "iitr-calendar-spring-2025-26", 2, SPRING_2026_PAGE2),
        *SYNTHETIC,
    ]
    ids = [e["event_id"] for e in events]
    assert len(ids) == len(set(ids)), "duplicate event ids"
    payload = {
        "description": (
            "Events fixture for CampusOrchestrator. origin=official records are transcribed from IIT Roorkee "
            "academic calendar PDFs (see documents); origin=synthetic records are invented demo events with "
            "dates relative to today. Generated by services/events_mcp/scripts/build_events_fixture.py."
        ),
        "documents": docs,
        "events": events,
    }
    OUT.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    counts: dict[str, int] = {}
    for e in events:
        counts[e["origin"]] = counts.get(e["origin"], 0) + 1
    print(f"wrote {OUT.name}: {len(events)} events {counts}")


if __name__ == "__main__":
    main()
