"""Synchronous image-generation service. Runs in a thread-pool worker."""
import datetime
import io
import math
import os
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from loguru import logger

from app.core.config import settings

VALID_FONTS = {
    "DavidLibre-Bold", "FrankRuhlLibre-Bold", "FrankRuhlLibre",
    "Heebo-Bold", "NotoSansHebrew-Bold",
}
DEFAULT_FONT = "NotoSansHebrew-Bold"

# ── Hebrew time tables ────────────────────────────────

HOURS = [
    "אַחַת", "שְׁתַּיִם", "שָׁלוֹשׁ", "אַרְבַּע", "חָמֵשׁ", "שֵׁשׁ",
    "שֶׁבַע", "שְׁמוֹנֶה", "תֵּשַׁע", "עֶשֶׂר", "אַחַת עֶשְׂרֵה", "שְׁתֵּים עֶשְׂרֵה"
]
MINUTE_PREFIX = [
    "", "וְדַקָּה אַחַת", "וּשְׁתֵּי דַקּוֹת", "וְשָׁלוֹשׁ דַקּוֹת",
    "וְאַרְבַּע דַקּוֹת", "וְחָמֵשׁ דַקּוֹת", "וְשֵׁשׁ דַקּוֹת", "וְשֶׁבַע דַקּוֹת",
    "וּשְׁמוֹנֶה דַקּוֹת", "וְתֵשַׁע דַקּוֹת", "וְעֶשֶׂר דַקּוֹת",
    "וְאַחַת עֶשְׂרֵה דַּקּוֹת", "וּשְׁתֵּים עֶשְׂרֵה דַּקּוֹת",
    "וּשְׁלוֹשׁ עֶשְׂרֵה דַּקּוֹת", "וְאַרְבַּע עֶשְׂרֵה דַּקּוֹת",
    "וָרֶבַע", "וְשֵׁשׁ עֶשְׂרֵה דַּקּוֹת", "וּשְׁבַע עֶשְׂרֵה דַּקּוֹת",
    "וּשְׁמוֹנֶה עֶשְׂרֵה דַּקּוֹת", "וּתְשַׁע עֶשְׂרֵה דַּקּוֹת",
    "וְעֶשְׂרִים דַקּוֹת", "וְעֶשְׂרִים וְאַחַת", "וְעֶשְׂרִים וּשְׁתַּיִם",
    "וְעֶשְׂרִים וְשָׁלוֹשׁ", "וְעֶשְׂרִים וְאַרְבַּע", "וְעֶשְׂרִים וְחָמֵשׁ",
    "וְעֶשְׂרִים וְשֵׁשׁ", "וְעֶשְׂרִים וְשֶׁבַע", "וְעֶשְׂרִים וּשְׁמוֹנֶה",
    "וְעֶשְׂרִים וְתֵשַׁע", "וּשְׁלוֹשִׁים", "וּשְׁלוֹשִׁים וְאַחַת",
    "וּשְׁלוֹשִׁים וּשְׁתַּיִם", "וּשְׁלוֹשִׁים וְשָׁלוֹשׁ", "וּשְׁלוֹשִׁים וְאַרְבַּע",
    "וּשְׁלוֹשִׁים וְחָמֵשׁ", "וּשְׁלוֹשִׁים וְשֵׁשׁ", "וּשְׁלוֹשִׁים וְשֶׁבַע",
    "וּשְׁלוֹשִׁים וּשְׁמוֹנֶה", "וּשְׁלוֹשִׁים וְתֵשַׁע", "וְאַרְבָּעִים",
    "וְאַרְבָּעִים וְאַחַת", "וְאַרְבָּעִים וּשְׁתַּיִם", "וְאַרְבָּעִים וְשָׁלוֹשׁ",
    "וְאַרְבָּעִים וְאַרְבַּע", "וְאַרְבָּעִים וְחָמֵשׁ", "וְאַרְבָּעִים וְשֵׁשׁ",
    "וְאַרְבָּעִים וְשֶׁבַע", "וְאַרְבָּעִים וּשְׁמוֹנֶה", "וְאַרְבָּעִים וְתֵשַׁע",
    "וַחֲמִשִּׁים", "וַחֲמִשִּׁים וְאַחַת", "וַחֲמִשִּׁים וּשְׁתַּיִם",
    "וַחֲמִשִּׁים וְשָׁלוֹשׁ", "וַחֲמִשִּׁים וְאַרְבַּע", "וַחֲמִשִּׁים וְחָמֵשׁ",
    "וַחֲמִשִּׁים וְשֵׁשׁ", "וַחֲמִשִּׁים וְשֶׁבַע", "וַחֲמִשִּׁים וּשְׁמוֹנֶה",
    "וַחֲמִשִּׁים וְתֵשַׁע",
]

PERIOD_WORDS = {
    "בַּבֹּקֶר", "בַּצָּהֳרַיִם", "אַחַר הַצָּהֳרַיִם",
    "בָּעֶרֶב", "בַּלַּיְלָה", "לִפְנוֹת בֹּקֶר",
}

MONTHS_HE = [
    "בְּיָנוּאָר", "בְּפֶבְּרוּאָר", "בְּמָרְץ", "בְּאַפְּרִיל",
    "בְּמַאי", "בְּיוּנִי", "בְּיוּלִי", "בְּאוֹגוּסְט",
    "בְּסֶפְּטֶמְבֶּר", "בְּאוֹקְטוֹבֶּר", "בְּנוֹבֶמְבֶּר", "בְּדֶצֶמְבֶּר",
]
DAYS_HE = [
    "יוֹם שֵׁנִי", "יוֹם שְׁלִישִׁי", "יוֹם רְבִיעִי",
    "יוֹם חֲמִישִׁי", "יוֹם שִׁישִּׁי", "שַׁבָּת", "יוֹם רִאשׁוֹן",
]

# ── Love notes for מטר (rotate through the info band). Override with the
#    LOVE_NOTES env var: a "|"-separated list, e.g. "שורה אחת|שורה שתיים". ──
LOVE_NOTES = [
    "מָטָר, אַתְּ כָּל כָּךְ מוּכְשֶׁרֶת",
    "אַתְּ הָאִמָּא הֲכִי טוֹבָה בָּעוֹלָם",
    "מָטָר, אַתְּ הַכִּי סֶקְסִית",
    "אֵין עוֹבֶדֶת קָשָׁה מִמֵּךְ",
    "אַתְּ חוֹלֶמֶת וּמַגְשִׁימָה",
    "אַתְּ הַחֲבֵרָה הֲכִי טוֹבָה שֶׁלִּי",
    "אַתְּ הָאֲהוּבָה שֶׁלִּי",
    "אֵין כָּמוֹךְ עִם בַּעֲלֵי הַחַיִּים שֶׁלָּנוּ",
    "אַתְּ גִּבּוֹרָה אֲמִתִּית",
    "אַתְּ עוֹשָׂה קֶסֶם בַּיָּדַיִם",
    "מָטָר, אֲנִי אוֹהֵב אוֹתָךְ",
]
# In auto mode, show a love note on 1 of every LOVE_CYCLE minutes (always if
# there's no upcoming workout to show).
LOVE_CYCLE = 4

# ── Helpers ───────────────────────────────────────────

def get_israel_time() -> datetime.datetime:
    utc = datetime.datetime.utcnow()
    local = utc + datetime.timedelta(hours=3 if 3 <= utc.month <= 10 else 2)
    return local + datetime.timedelta(seconds=settings.display_lag)


def get_font(size: int, font_name: str = DEFAULT_FONT) -> ImageFont.FreeTypeFont:
    name = font_name if font_name in VALID_FONTS else DEFAULT_FONT
    path = settings.font_dir / f"{name}.ttf"
    if path.exists():
        try:
            return ImageFont.truetype(str(path), size)
        except Exception:
            pass
    for fallback in ("NotoSansHebrew-Bold", "FrankRuhlLibre"):
        fb = settings.font_dir / f"{fallback}.ttf"
        if fb.exists():
            try:
                return ImageFont.truetype(str(fb), size)
            except Exception:
                pass
    return ImageFont.load_default()


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.convert("1", dither=Image.Dither.NONE).save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.read()


def _get_time_period(h: int) -> str:
    if 6  <= h < 12: return "בַּבֹּקֶר"
    if 12 <= h < 16: return "בַּצָּהֳרַיִם"
    if 16 <= h < 18: return "אַחַר הַצָּהֳרַיִם"
    if 18 <= h < 21: return "בָּעֶרֶב"
    if 21 <= h < 24: return "בַּלַּיְלָה"
    if 0  <= h < 3:  return "בַּלַּיְלָה"
    return "לִפְנוֹת בֹּקֶר"


def _get_time_lines(h24: int, m: int) -> list[str]:
    h12 = h24 % 12 or 12
    period = _get_time_period(h24)
    mp = MINUTE_PREFIX[m]
    hp = HOURS[h12 - 1]
    if len(hp + mp) > 25:
        return [hp, mp, period]
    return [hp + " " + mp, period]

# ── Drawing ───────────────────────────────────────────

def _draw_weather_icon(draw: ImageDraw.Draw, cx: int, cy: int,
                       icon_key: str, size: int = 38) -> None:
    s = size

    def cloud(ox: int = 0, oy: int = 0, scale: float = 1.0) -> None:
        w, h = int(s * 1.4 * scale), int(s * 0.7 * scale)
        pts = []
        for a in range(180, 361, 8):
            pts.append((ox + cx + int(w / 2 * math.cos(math.radians(a))),
                        oy + cy + int(h / 2 * math.sin(math.radians(a)))))
        for centre, rx, dy in [
            (int(w * 0.25),  int(h * 0.6  * scale), int(h * 0.2)),
            (0,              int(h * 0.75 * scale), int(h * 0.3)),
            (-int(w * 0.25), int(h * 0.55 * scale), int(h * 0.1)),
        ]:
            for a in range(0, 181, 8):
                pts.append((ox + cx + centre + int(rx * math.cos(math.radians(a))),
                            oy + cy - dy     + int(rx * math.sin(math.radians(a)))))
        draw.polygon(pts, fill=255, outline=0)

    if icon_key == "sun":
        r = s // 2
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255, outline=0, width=3)
        for a in range(0, 360, 45):
            rad = math.radians(a)
            draw.line([cx + (r + 4)  * math.cos(rad), cy + (r + 4)  * math.sin(rad),
                       cx + (r + 13) * math.cos(rad), cy + (r + 13) * math.sin(rad)],
                      fill=0, width=3)
    elif icon_key == "sun_cloud":
        sr = s // 3
        scx, scy = cx - s // 3, cy - s // 4
        draw.ellipse([scx - sr, scy - sr, scx + sr, scy + sr], fill=255, outline=0, width=2)
        for a in range(0, 360, 60):
            rad = math.radians(a)
            draw.line([scx + (sr + 3) * math.cos(rad), scy + (sr + 3) * math.sin(rad),
                       scx + (sr + 9) * math.cos(rad), scy + (sr + 9) * math.sin(rad)],
                      fill=0, width=2)
        cloud(s // 5, s // 5, 0.85)
    elif icon_key == "cloud":
        cloud()
    elif icon_key == "cloud_rain":
        cloud(0, -s // 5, 0.9)
        for ox in (-s // 3, -s // 8, s // 8, s // 3):
            draw.line([cx + ox, cy + s // 4, cx + ox - 4, cy + s // 2 + 4], fill=0, width=2)
    elif icon_key == "cloud_snow":
        cloud(0, -s // 5, 0.9)
        for ox in (-s // 3, -s // 8, s // 8, s // 3):
            x, y = cx + ox, cy + s // 3
            for a in (0, 60, 120):
                rad = math.radians(a)
                draw.line([x - 6 * math.cos(rad), y - 6 * math.sin(rad),
                           x + 6 * math.cos(rad), y + 6 * math.sin(rad)],
                          fill=0, width=2)
    elif icon_key == "thunder":
        cloud(0, -s // 4, 0.9)
        pts = [(cx + 4, cy + s // 6), (cx - 6, cy + s // 2),
               (cx + 2, cy + s // 2), (cx - 8, cy + s)]
        draw.line(pts, fill=0, width=3)


def _draw_analog_clock(draw: ImageDraw.Draw, cx: int, cy: int, r: int,
                       h24: int, m: int, font_name: str) -> None:
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=0, width=3)
    for i in range(12):
        angle = math.radians(i * 30 - 90)
        if i % 3 == 0:
            draw.line([cx + (r - 4)  * math.cos(angle), cy + (r - 4)  * math.sin(angle),
                       cx + (r - 12) * math.cos(angle), cy + (r - 12) * math.sin(angle)],
                      fill=0, width=3)
        else:
            draw.line([cx + (r - 4) * math.cos(angle), cy + (r - 4) * math.sin(angle),
                       cx + (r - 9) * math.cos(angle), cy + (r - 9) * math.sin(angle)],
                      fill=0, width=2)
    num_font = get_font(max(12, r // 4), font_name)
    for num, deg in ((12, -90), (3, 0), (6, 90), (9, 180)):
        angle = math.radians(deg)
        draw.text((cx + (r - 18) * math.cos(angle), cy + (r - 18) * math.sin(angle)),
                  str(num), font=num_font, fill=0, anchor="mm")
    h12 = h24 % 12
    hour_angle = math.radians((h12 + m / 60) * 30 - 90)
    draw.line([cx, cy, cx + (r * 0.55) * math.cos(hour_angle),
               cy + (r * 0.55) * math.sin(hour_angle)], fill=0, width=4)
    min_angle = math.radians(m * 6 - 90)
    draw.line([cx, cy, cx + (r * 0.75) * math.cos(min_angle),
               cy + (r * 0.75) * math.sin(min_angle)], fill=0, width=2)
    draw.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=0)

# ── Image generators ──────────────────────────────────

def _generate_night_image(font_name: str) -> bytes:
    W, H = 800, 480
    img = Image.new("L", (W, H), color=0)
    draw = ImageDraw.Draw(img)

    rng = random.Random(42)
    for _ in range(60):
        x = rng.randint(20, W - 20)
        y = rng.randint(20, H - 20)
        size = rng.choice([1, 1, 2, 2, 3])
        draw.ellipse([x - size, y - size, x + size, y + size], fill=255)

    mx, my, mr = 100, 90, 55
    draw.ellipse([mx - mr, my - mr, mx + mr, my + mr], fill=255)
    draw.ellipse([mx - mr + 16, my - mr - 12, mx + mr + 16, my - mr - 12 + mr * 2], fill=0)

    sleeping_path = settings.font_dir / "sleeping.png"
    if sleeping_path.exists():
        try:
            sleeping = Image.open(sleeping_path).convert("L")
            mask = sleeping.point(lambda p: 255 if p < 128 else 0)
            white_lines = Image.new("L", sleeping.size, 255)
            black_bg   = Image.new("L", sleeping.size, 0)
            result = Image.composite(white_lines, black_bg, mask)
            sw, sh = 380, 280
            result = result.resize((sw, sh), Image.LANCZOS)
            mask_r = mask.resize((sw, sh), Image.LANCZOS)
            img.paste(result, (W - sw - 20, (H - sh) // 2), mask=mask_r)
        except Exception as exc:
            logger.warning("sleeping image error: {}", exc)

    text_cx = (W - 380 - 40) // 2
    draw.text((text_cx, H // 2 - 30), "זְמַן לִישׁוֹן",
              font=get_font(72, font_name), fill=255, anchor="mm")
    draw.text((text_cx, H // 2 + 55), "לַיְלָה טוֹב",
              font=get_font(44, font_name), fill=180, anchor="mm")
    return _png_bytes(img)


def _generate_quiet_image(font_name: str) -> bytes:
    W, H = 800, 480
    img = Image.new("L", (W, H), color=255)
    draw = ImageDraw.Draw(img)
    PAD1, PAD2 = 8, 16
    draw.rectangle([PAD1, PAD1, W - PAD1, H - PAD1], outline=0, width=3)
    draw.rectangle([PAD2, PAD2, W - PAD2, H - PAD2], outline=0, width=1)
    draw.text((W // 2, H // 2 - 50), "לֹא לְהָעִיר אַף אֶחָד!",
              font=get_font(72, font_name), fill=0, anchor="mm")
    draw.text((W // 2 - 60, H // 2 + 30), "z", font=get_font(72, font_name), fill=0, anchor="mm")
    draw.text((W // 2,      H // 2 + 20), "z", font=get_font(55, font_name), fill=0, anchor="mm")
    draw.text((W // 2 + 50, H // 2 + 10), "z", font=get_font(38, font_name), fill=0, anchor="mm")
    return _png_bytes(img)


def _draw_dumbbell(draw: ImageDraw.Draw, cx: int, cy: int, s: int = 18) -> None:
    """Small dumbbell glyph: a bar with a plate + end-cap on each side."""
    bar_hw = s
    draw.rectangle([cx - bar_hw, cy - 3, cx + bar_hw, cy + 3], fill=0)
    for sx in (-1, 1):
        ox = cx + sx * bar_hw
        draw.rectangle([ox - 5, cy - 14, ox + 5, cy + 14], fill=0)
        cap = ox + sx * 8
        draw.rectangle([cap - 3, cy - 9, cap + 3, cy + 9], fill=0)


def _draw_heart(draw: ImageDraw.Draw, cx: int, cy: int, s: int = 13) -> None:
    """Small filled heart: two top lobes + a downward point."""
    r = s
    top = cy - r // 2
    draw.ellipse([cx - r, top - r, cx, top + r], fill=0)
    draw.ellipse([cx, top - r, cx + r, top + r], fill=0)
    draw.polygon([(cx - r + 1, top), (cx + r - 1, top), (cx, cy + r)], fill=0)


def _rel_day(date_s: str, now: datetime.datetime) -> str:
    try:
        d = datetime.date.fromisoformat(date_s)
    except ValueError:
        return ""
    delta = (d - now.date()).days
    if delta == 0:
        return "הַיּוֹם"
    if delta == 1:
        return "מָחָר"
    return DAYS_HE[d.weekday()]


def _format_next_session(ns: dict, now: datetime.datetime) -> str:
    rel = _rel_day(ns.get("date", ""), now)
    line = "הָאִימוּן הַבָּא"
    bits = [b for b in (rel, ns.get("time", "")) if b]
    if bits:
        line += " · " + " ".join(bits)
    cat = (ns.get("category") or "").strip()
    if cat:
        line += " · " + cat
    return line


def _get_love_notes() -> list[str]:
    raw = os.environ.get("LOVE_NOTES", "").strip()
    if raw:
        notes = [n.strip() for n in raw.split("|") if n.strip()]
        if notes:
            return notes
    return LOVE_NOTES


def _pick_love_note(notes: list[str], now: datetime.datetime) -> str:
    # Deterministic per minute, cycles through the list, varies across days.
    idx = (now.timetuple().tm_yday * 1440 + now.hour * 60 + now.minute) % len(notes)
    return notes[idx]


def generate_clock_image(
    font_name:   str        = DEFAULT_FONT,
    sleep_time:  bool       = False,
    weather:     dict | None = None,
    jewish_date: str | None  = None,
    next_session: dict | None = None,
    band_mode:   str          = "auto",
) -> bytes:
    fn = font_name if font_name in VALID_FONTS else DEFAULT_FONT

    if sleep_time:
        return _generate_night_image(fn)

    now  = get_israel_time()
    h24, m = now.hour, now.minute

    if h24 == 6 or (h24 == 7 and m < 30):
        return _generate_quiet_image(fn)

    W, H = 800, 480
    img  = Image.new("L", (W, H), color=255)
    draw = ImageDraw.Draw(img)

    PAD1, PAD2 = 8, 16
    draw.rectangle([PAD1, PAD1, W - PAD1, H - PAD1], outline=0, width=3)
    draw.rectangle([PAD2, PAD2, W - PAD2, H - PAD2], outline=0, width=1)

    lines       = _get_time_lines(h24, m)
    time_lines  = [l for l in lines if l not in PERIOD_WORDS]
    period_line = next((l for l in lines if l in PERIOD_WORDS), "")

    font_large  = get_font(108, fn)
    font_medium = get_font(58,  fn)
    font_small  = get_font(34,  fn)

    # ── Decide the info band: rotate the ARBOX workout with love notes ──
    has_gym       = bool(next_session and next_session.get("time"))
    love_notes    = _get_love_notes()
    minute_of_day = now.hour * 60 + now.minute
    if band_mode == "love":
        show_love = bool(love_notes)
    elif band_mode == "gym":
        show_love = False
    else:  # auto: mostly the workout, a love note every LOVE_CYCLE-th minute
        love_slot = (minute_of_day % LOVE_CYCLE) == (LOVE_CYCLE - 1)
        show_love = bool(love_notes) and (not has_gym or love_slot)
    has_band = has_gym or show_love

    # ── Hero: the time spelled out in Hebrew (analog clock removed) ──
    words_top    = PAD2 + 18
    words_bottom = (H - 190) if has_band else (H - 118)
    n            = len(time_lines)
    line_h       = 100
    total_h      = n * line_h
    ty           = words_top + (words_bottom - words_top - total_h) // 2 + line_h // 2

    for i, line in enumerate(time_lines):
        f = font_large
        while True:
            bbox = draw.textbbox((0, 0), line, font=f)
            if (bbox[2] - bbox[0]) < (W - 60):
                break
            current_size = getattr(f, "size", 108)
            if current_size <= 40:
                break
            f = get_font(current_size - 6, fn)
        draw.text((W // 2, ty + i * line_h), line, font=f, fill=0, anchor="mm")

    # ── Info band: workout (dumbbell) or a love note for מטר (heart) ──
    if has_band:
        band_cy = H - 138
        draw.line([(PAD2 + 40, H - 176), (W - PAD2 - 40, H - 176)], fill=0, width=1)
        if show_love:
            band_text = _pick_love_note(love_notes, now)
            draw_icon, icon_s = _draw_heart, 13
        else:
            band_text = _format_next_session(next_session, now)
            draw_icon, icon_s = _draw_dumbbell, 18
        bf = get_font(38, fn)
        while True:
            bb = draw.textbbox((0, 0), band_text, font=bf)
            if (bb[2] - bb[0]) <= (W - 150):
                break
            cur = getattr(bf, "size", 38)
            if cur <= 22:
                break
            bf = get_font(cur - 2, fn)
        bb          = draw.textbbox((0, 0), band_text, font=bf)
        tw          = bb[2] - bb[0]
        icon_w, gap = 44, 14
        group_left  = (W - (icon_w + gap + tw)) // 2
        draw_icon(draw, group_left + icon_w // 2, band_cy, s=icon_s)
        draw.text((group_left + icon_w + gap, band_cy), band_text, font=bf, fill=0, anchor="lm")

    sep_y = H - 105
    draw.line([(PAD2 + 8, sep_y), (W - PAD2 - 8, sep_y)], fill=0, width=1)
    bar_cy    = H - 52
    bar_left  = PAD2 + 8
    bar_right = W - PAD2 - 8
    bar_width = bar_right - bar_left
    div_x     = bar_left + bar_width // 3
    div_x2    = bar_left + 2 * bar_width // 3
    draw.line([(div_x,  H - 92), (div_x,  H - 15)], fill=0, width=1)
    draw.line([(div_x2, H - 92), (div_x2, H - 15)], fill=0, width=1)

    day_name  = DAYS_HE[now.weekday()]
    if jewish_date and "\n" in jewish_date:
        date_str, year_str = jewish_date.split("\n", 1)
    else:
        date_str = jewish_date if jewish_date else f"{now.day} {MONTHS_HE[now.month - 1]}"
        year_str = None
    left_cx   = (bar_left + div_x) // 2
    cell_w    = div_x - bar_left - 10

    def _fit_font(text: str, start: int, minimum: int = 18) -> ImageFont.FreeTypeFont:
        f = get_font(start, fn)
        while True:
            bbox = draw.textbbox((0, 0), text, font=f)
            if (bbox[2] - bbox[0]) <= cell_w:
                return f
            cur = getattr(f, "size", start)
            if cur <= minimum:
                return f
            f = get_font(cur - 2, fn)

    if year_str:
        day_font  = _fit_font(day_name, 28)
        date_font = _fit_font(date_str, 26)
        year_font = _fit_font(year_str, 22)
        draw.text((left_cx, bar_cy - 26), day_name, font=day_font,  fill=0, anchor="mm")
        draw.text((left_cx, bar_cy),      date_str, font=date_font, fill=0, anchor="mm")
        draw.text((left_cx, bar_cy + 24), year_str, font=year_font, fill=0, anchor="mm")
    else:
        date_font = _fit_font(date_str, 34)
        draw.text((left_cx, bar_cy - 14), day_name, font=font_small, fill=0, anchor="mm")
        draw.text((left_cx, bar_cy + 14), date_str, font=date_font,  fill=0, anchor="mm")

    mid_x = (div_x + div_x2) // 2
    if period_line:
        draw.text((mid_x, bar_cy), period_line, font=font_small, fill=0, anchor="mm")

    if weather:
        right_start = div_x2
        right_end   = W - PAD2 - 8
        icon_x      = right_start + (right_end - right_start) // 4
        text_x      = right_start + 3 * (right_end - right_start) // 4
        _draw_weather_icon(draw, icon_x, bar_cy, weather.get("icon_key", "cloud"), size=34)
        draw.text((text_x, bar_cy - 14), f"{weather['temp']}°",
                  font=get_font(40, fn), fill=0, anchor="mm")
        draw.text((text_x, bar_cy + 16), weather.get("desc", ""),
                  font=font_small, fill=0, anchor="mm")

    return _png_bytes(img)


def log_available_fonts() -> None:
    found = [f for f in VALID_FONTS
             if (settings.font_dir / f"{f}.ttf").exists()]
    if found:
        logger.info("available fonts: {}", ", ".join(sorted(found)))
    else:
        logger.warning("no Hebrew font files found in {}", settings.font_dir)
