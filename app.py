import os
import re
import tempfile
import unicodedata
from datetime import date, datetime, timedelta
from io import BytesIO

import requests
import streamlit as st
from fpdf import FPDF


st.set_page_config(page_title="AI Itinerary Architect", layout="wide")

st.markdown(
    """
    <style>
    .main-header { color: #153e8b; font-weight: 800; font-size: 2.5rem; margin-bottom: 0.15rem; }
    .sub-header { color: #475569; margin-bottom: 1rem; }
    .preview-card { border: 1px solid #dbe3f0; border-radius: 14px; padding: 1rem; margin-bottom: 1rem; background: #f8fbff; }
    .stButton>button, .stDownloadButton>button {
        background: #2563eb;
        color: white;
        border-radius: 10px;
        border: none;
        font-weight: 700;
        width: 100%;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def safe_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return normalized.encode("latin-1", "ignore").decode("latin-1").strip()


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", value or "")
    return cleaned.strip("_").lower() or "travel_plan"


def format_day_label(day_date: date) -> str:
    return day_date.strftime("%B %d - %A")


def compact_date(day_date: date) -> str:
    return day_date.strftime("%b %d, %Y")


def fallback_plan(destination: str, start_date: date, end_date: date):
    total_days = max((end_date - start_date).days + 1, 1)
    days = []
    for idx in range(total_days):
        current_date = start_date + timedelta(days=idx)
        if idx == 0:
            title = "Arrival & Rest"
        elif idx == total_days - 1:
            title = "Departure"
        else:
            title = f"Day {idx + 1} Highlights"

        days.append(
            {
                "date": current_date,
                "title": title,
                "morning": f"Start the morning with a comfortable sightseeing plan in {destination}, focusing on a major landmark and relaxed exploration.",
                "afternoon": f"Use the afternoon for local food, cultural spots, or shopping areas that fit the style of {destination}.",
                "evening": f"End the day with a scenic walk, dinner, and quiet rest before the next part of the itinerary.",
            }
        )
    return days


def parse_ai_plan(raw_text: str, destination: str, start_date: date, end_date: date):
    total_days = max((end_date - start_date).days + 1, 1)
    expected_dates = [start_date + timedelta(days=i) for i in range(total_days)]
    days = []
    current = None

    for line in [item.strip() for item in raw_text.splitlines() if item.strip()]:
        lowered = line.lower()
        if lowered.startswith("day "):
            if current:
                days.append(current)
            current = {"title": "", "morning": "", "afternoon": "", "evening": ""}
        elif lowered.startswith("title:"):
            current = current or {"title": "", "morning": "", "afternoon": "", "evening": ""}
            current["title"] = line.split(":", 1)[1].strip()
        elif lowered.startswith("morning:"):
            current = current or {"title": "", "morning": "", "afternoon": "", "evening": ""}
            current["morning"] = line.split(":", 1)[1].strip()
        elif lowered.startswith("afternoon:"):
            current = current or {"title": "", "morning": "", "afternoon": "", "evening": ""}
            current["afternoon"] = line.split(":", 1)[1].strip()
        elif lowered.startswith("evening:"):
            current = current or {"title": "", "morning": "", "afternoon": "", "evening": ""}
            current["evening"] = line.split(":", 1)[1].strip()
        elif current:
            if current["evening"]:
                current["evening"] = f"{current['evening']} {line}".strip()
            elif current["afternoon"]:
                current["afternoon"] = f"{current['afternoon']} {line}".strip()
            else:
                current["morning"] = f"{current['morning']} {line}".strip()

    if current:
        days.append(current)

    if not days:
        return fallback_plan(destination, start_date, end_date)

    normalized = []
    for idx, item in enumerate(days[:total_days]):
        normalized.append(
            {
                "date": expected_dates[idx],
                "title": item.get("title") or f"Day {idx + 1} Highlights",
                "morning": item.get("morning", ""),
                "afternoon": item.get("afternoon", ""),
                "evening": item.get("evening", ""),
            }
        )

    while len(normalized) < total_days:
        idx = len(normalized)
        normalized.append(
            {
                "date": expected_dates[idx],
                "title": f"Day {idx + 1} Highlights",
                "morning": "",
                "afternoon": "",
                "evening": "",
            }
        )

    return normalized


def get_ai_plan(client: str, destination: str, start_date: date, end_date: date):
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        return fallback_plan(destination, start_date, end_date)

    prompt = f"""
Create a professional travel plan.

Client: {client}
Destination: {destination}
Dates: {start_date} to {end_date}

Return plain text only using this exact format:

Day 1
Title: ...
Morning: ...
Afternoon: ...
Evening: ...

Day 2
Title: ...
Morning: ...
Afternoon: ...
Evening: ...

Keep each day practical and realistic.
"""

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "anthropic/claude-3-haiku",
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        raw_text = data["choices"][0]["message"]["content"]
        return parse_ai_plan(raw_text, destination, start_date, end_date)
    except Exception:
        return fallback_plan(destination, start_date, end_date)


def download_image(url: str):
    try:
        response = requests.get(url, timeout=25)
        response.raise_for_status()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as temp_file:
            temp_file.write(response.content)
            return temp_file.name
    except Exception:
        return None


def get_cover_image(destination: str):
    seed = slugify(destination)
    for url in [
        f"https://loremflickr.com/1200/700/{seed},city",
        f"https://picsum.photos/seed/{seed}_cover/1200/700",
    ]:
        path = download_image(url)
        if path:
            return path
    return None


def get_day_images(destination: str, title: str):
    seed = slugify(f"{destination}_{title}")
    urls = [
        f"https://loremflickr.com/600/420/{slugify(destination)},landmark",
        f"https://loremflickr.com/600/420/{slugify(destination)},travel",
        f"https://loremflickr.com/600/420/{slugify(destination)},architecture",
        f"https://picsum.photos/seed/{seed}_alt/600/420",
    ]
    paths = []
    for url in urls:
        path = download_image(url)
        if path:
            paths.append(path)
    return paths[:4]


class TravelPlanPDF(FPDF):
    def header(self):
        if self.page_no() >= 3:
            self.set_font("Helvetica", "B", 8)
            self.set_text_color(0, 0, 0)
            self.cell(0, 6, f"Page {self.page_no()} of {{nb}}", align="R")
            self.ln(3)


def draw_cover_page(pdf: TravelPlanPDF, client: str, title: str, start_date: date, end_date: date, cover_path: str | None):
    pdf.add_page()
    pdf.set_fill_color(255, 255, 255)
    pdf.rect(0, 0, 210, 297, "F")

    pdf.set_xy(0, 18)
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(210, 10, safe_text(client.upper()), align="C")

    if cover_path:
        pdf.image(cover_path, x=10, y=38, w=190, h=86)

    pdf.set_xy(0, 132)
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(14, 44, 85)
    pdf.cell(210, 10, safe_text(title), align="C")

    pdf.set_xy(0, 146)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(53, 90, 129)
    pdf.cell(210, 8, safe_text(f"{compact_date(start_date)} - {compact_date(end_date)}"), align="C")


def draw_summary_page(pdf: TravelPlanPDF, days: list[dict]):
    pdf.add_page()
    pdf.set_xy(14, 18)
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(20, 54, 109)
    pdf.cell(0, 10, "Trip Summary")
    pdf.ln(14)

    for item in days:
        pdf.set_draw_color(210, 220, 230)
        pdf.line(14, pdf.get_y() + 2, 196, pdf.get_y() + 2)
        pdf.ln(5)
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(35, 68, 115)
        pdf.cell(110, 8, safe_text(item["title"]))
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(0, 8, safe_text(format_day_label(item["date"])), align="R")
        pdf.ln(10)


def draw_timeline_marker(pdf: TravelPlanPDF, y_top: float):
    x = 20
    pdf.set_draw_color(190, 200, 210)
    pdf.line(x, y_top, x, y_top + 24)
    pdf.ellipse(x - 4, y_top, 8, 8, "D")
    pdf.set_xy(x - 2, y_top + 1.2)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(50, 50, 50)
    pdf.cell(4, 4, "+", align="C")


def draw_image_grid(pdf: TravelPlanPDF, image_paths: list[str], x: float, y: float):
    if not image_paths:
        return y

    positions = [
        (x, y, 68, 40),
        (x + 70, y, 34, 19),
        (x + 106, y, 34, 19),
        (x + 70, y + 21, 34, 19),
    ]

    for idx, image_path in enumerate(image_paths[:4]):
        px, py, pw, ph = positions[idx]
        try:
            pdf.image(image_path, x=px, y=py, w=pw, h=ph)
        except Exception:
            continue

    return y + 44


def draw_day_block(pdf: TravelPlanPDF, item: dict, image_paths: list[str]):
    if pdf.get_y() > 230:
        pdf.add_page()

    start_y = pdf.get_y() + 4
    draw_timeline_marker(pdf, start_y)

    content_x = 32
    pdf.set_xy(content_x, start_y - 1)
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_text_color(52, 86, 129)
    pdf.cell(0, 8, safe_text(format_day_label(item["date"])))
    pdf.ln(8)

    pdf.set_x(content_x)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 7, safe_text(item["title"]))
    pdf.ln(7)

    for label, content in [
        ("Morning", item["morning"]),
        ("Afternoon", item["afternoon"]),
        ("Evening", item["evening"]),
    ]:
        if not safe_text(content):
            continue
        pdf.set_x(content_x)
        pdf.set_font("Helvetica", "B", 10)
        pdf.write(5, f"{label}: ")
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(150, 5, safe_text(content))

    if image_paths:
        image_y = pdf.get_y() + 2
        last_y = draw_image_grid(pdf, image_paths, content_x, image_y)
        pdf.set_y(last_y + 7)
    else:
        pdf.ln(7)

    pdf.set_draw_color(220, 228, 236)
    pdf.line(14, pdf.get_y(), 196, pdf.get_y())
    pdf.ln(5)


def build_pdf(client: str, title: str, destination: str, start_date: date, end_date: date, days: list[dict]) -> bytes:
    cover_path = get_cover_image(destination)
    day_images = [get_day_images(destination, item["title"]) for item in days]

    pdf = TravelPlanPDF("P", "mm", "A4")
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=16)

    draw_cover_page(pdf, client, title, start_date, end_date, cover_path)
    draw_summary_page(pdf, days)

    pdf.add_page()
    pdf.set_y(12)
    for idx, item in enumerate(days):
        draw_day_block(pdf, item, day_images[idx])

    output = pdf.output(dest="S")
    if isinstance(output, str):
        return output.encode("latin-1", errors="ignore")
    if isinstance(output, bytearray):
        return bytes(output)
    return output


st.markdown("<div class='main-header'>AI Itinerary Architect</div>", unsafe_allow_html=True)
st.markdown(
    "<div class='sub-header'>Generate a structured travel plan and export a PDF with embedded destination photos.</div>",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("### Trip Details")
    client_name = st.text_input("Client Name", "Mr. Rana Muhammad Asif")
    destination = st.text_input("Destination", "Belgium")
    plan_title = st.text_input("Plan Title", "Travel Plan")
    start_date = st.date_input("Departure", datetime.now().date())
    end_date = st.date_input("Return", datetime.now().date() + timedelta(days=5))
    generate = st.button("Create Travel Plan")

if end_date < start_date:
    st.error("Return date cannot be before departure date.")
    st.stop()

if generate:
    with st.spinner("Generating itinerary and preparing PDF images..."):
        itinerary_days = get_ai_plan(client_name, destination, start_date, end_date)
        pdf_bytes = build_pdf(
            client=client_name,
            title=plan_title,
            destination=destination,
            start_date=start_date,
            end_date=end_date,
            days=itinerary_days,
        )

    st.success("Your travel plan is ready.")
    st.subheader(f"{plan_title}: {destination}")

    preview_cols = st.columns(3)
    preview_urls = [
        f"https://loremflickr.com/500/320/{slugify(destination)},landmark",
        f"https://loremflickr.com/500/320/{slugify(destination)},architecture",
        f"https://loremflickr.com/500/320/{slugify(destination)},travel",
    ]
    for idx, column in enumerate(preview_cols):
        with column:
            st.image(preview_urls[idx], use_container_width=True)

    for item in itinerary_days:
        st.markdown(
            f"""
            <div class="preview-card">
                <strong>{safe_text(format_day_label(item["date"]))}</strong><br>
                <strong>{safe_text(item["title"])}</strong><br><br>
                <strong>Morning:</strong> {safe_text(item["morning"])}<br><br>
                <strong>Afternoon:</strong> {safe_text(item["afternoon"])}<br><br>
                <strong>Evening:</strong> {safe_text(item["evening"])}
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.download_button(
        label="Download Matching PDF",
        data=BytesIO(pdf_bytes),
        file_name=f"{slugify(destination)}_travel_plan.pdf",
        mime="application/pdf",
    )