
import sqlite3
from contextlib import closing
from html import escape

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse

app = FastAPI()
DB_NAME = "database.db"

DAYS = [
    ("monday", "Понедельник"),
    ("tuesday", "Вторник"),
    ("wednesday", "Среда"),
    ("thursday", "Четверг"),
    ("friday", "Пятница"),
    ("saturday", "Суббота"),
    ("sunday", "Воскресенье"),
]

QUESTIONS = [
    ("goals", "Чем ты хочешь заниматься?",
     "Например: английский, спорт, чтение, рисование."),
    ("sleep", "Какой у тебя режим сна?",
     "Например: встаю в 8–9, ложусь около полуночи."),
    ("duration", "Сколько времени хочешь уделять своим целям?",
     "Например: 1–2 часа в день."),
    ("preferences", "Что ещё важно учесть?",
     "Например: после работы устаю, в выходные хочу отдыхать."),
]

PRIORITY_NAMES = {
    "high": "Высокий",
    "medium": "Средний",
    "low": "Низкий",
}

TIME_NAMES = {
    "any": "Без предпочтений",
    "morning": "Утро",
    "afternoon": "День",
    "evening": "Вечер",
}

DAY_NAMES = dict(DAYS)


def connect_db():
    return sqlite3.connect(DB_NAME)


def init_db():
    with closing(connect_db()) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS answers (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT NOT NULL,
                title TEXT NOT NULL,
                start TEXT NOT NULL,
                end TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL,
                frequency INTEGER NOT NULL,
                priority TEXT NOT NULL,
                preferred_time TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS weekly_plan (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                goal_id INTEGER,
                day TEXT NOT NULL,
                title TEXT NOT NULL,
                start TEXT NOT NULL,
                end TEXT NOT NULL
            )
        """)

        conn.commit()


init_db()


def get_answer(key):
    with closing(connect_db()) as conn:
        row = conn.execute(
            "SELECT value FROM answers WHERE key = ?",
            (key,),
        ).fetchone()
    return row[0] if row else ""


def save_answer(key, value):
    with closing(connect_db()) as conn:
        conn.execute(
            """
            INSERT INTO answers (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        conn.commit()


def get_events(day=None):
    with closing(connect_db()) as conn:
        if day:
            rows = conn.execute(
                """
                SELECT id, day, title, start, end
                FROM events WHERE day = ? ORDER BY start
                """,
                (day,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, day, title, start, end FROM events"
            ).fetchall()
    return rows


def get_goals():
    with closing(connect_db()) as conn:
        return conn.execute("""
            SELECT id, name, duration_minutes, frequency,
                   priority, preferred_time
            FROM goals
            ORDER BY id
        """).fetchall()


def get_plan():
    with closing(connect_db()) as conn:
        return conn.execute("""
            SELECT id, goal_id, day, title, start, end
            FROM weekly_plan
            ORDER BY
                CASE day
                    WHEN 'monday' THEN 1
                    WHEN 'tuesday' THEN 2
                    WHEN 'wednesday' THEN 3
                    WHEN 'thursday' THEN 4
                    WHEN 'friday' THEN 5
                    WHEN 'saturday' THEN 6
                    WHEN 'sunday' THEN 7
                END,
                start
        """).fetchall()


def to_minutes(value):
    hours, minutes = map(int, value.split(":"))
    return hours * 60 + minutes


def to_time(value):
    return f"{value // 60:02d}:{value % 60:02d}"


def overlaps(start_a, end_a, start_b, end_b):
    return start_a < end_b and end_a > start_b


def generate_plan():
    goals = get_goals()
    events = get_events()

    # Планируем заново, не меняя обязательные события и цели.
    with closing(connect_db()) as conn:
        conn.execute("DELETE FROM weekly_plan")
        conn.commit()

    if not goals:
        return 0

    # Для начала используем базовое окно бодрствования 08:00–22:00.
    # Позже настроим его индивидуально по режиму сна.
    day_busy = {day: [] for day, _ in DAYS}

    for _, day, _, start, end in events:
        day_busy[day].append(
            (to_minutes(start), to_minutes(end))
        )

    # Учитываем уже запланированные занятия.
    day_goal_count = {day: 0 for day, _ in DAYS}
    created = []

    priority_order = {"high": 0, "medium": 1, "low": 2}
    goals = sorted(
        goals,
        key=lambda goal: (
            priority_order.get(goal[4], 1),
            -goal[3],
        ),
    )

    for goal_id, name, duration, frequency, priority, preferred in goals:
        if duration > 14 * 60:
            continue

        # Время суток, в которое предпочтительно заниматься.
        if preferred == "morning":
            window_start, window_end = 8 * 60, 12 * 60
        elif preferred == "afternoon":
            window_start, window_end = 12 * 60, 18 * 60
        elif preferred == "evening":
            window_start, window_end = 18 * 60, 22 * 60
        else:
            window_start, window_end = 8 * 60, 22 * 60

        placed_days = set()

        for _ in range(frequency):
            # Сначала пробуем дни, в которых меньше занятий.
            ordered_days = sorted(
                [day for day, _ in DAYS],
                key=lambda day: (
                    day in placed_days,
                    day_goal_count[day],
                    [key for key, _ in DAYS].index(day),
                ),
            )

            placed = False

            for day in ordered_days:
                if day in placed_days:
                    continue

                # Ищем место с шагом 30 минут.
                start = window_start

                while start + duration <= window_end:
                    end = start + duration

                    # 15 минут отдыха до и после занятия.
                    padded_start = max(8 * 60, start - 15)
                    padded_end = min(22 * 60, end + 15)

                    conflict = any(
                        overlaps(
                            padded_start,
                            padded_end,
                            busy_start,
                            busy_end,
                        )
                        for busy_start, busy_end in day_busy[day]
                    )

                    if not conflict:
                        day_busy[day].append(
                            (padded_start, padded_end)
                        )
                        day_busy[day].sort()

                        created.append((
                            goal_id,
                            day,
                            name,
                            to_time(start),
                            to_time(end),
                        ))

                        day_goal_count[day] += 1
                        placed_days.add(day)
                        placed = True
                        break

                    start += 30

                if placed:
                    break

    with closing(connect_db()) as conn:
        conn.executemany(
            """
            INSERT INTO weekly_plan
                (goal_id, day, title, start, end)
            VALUES (?, ?, ?, ?, ?)
            """,
            created,
        )
        conn.commit()

    return len(created)


def page(content):
    return f"""
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport"
              content="width=device-width, initial-scale=1">
        <title>Anti-Overload</title>
    </head>
    <body style="
        font-family:Arial,sans-serif;max-width:720px;
        margin:30px auto;padding:20px;background:#f5f5fa;
        color:#252538;line-height:1.6">
        <h1>🧠 Anti-Overload</h1>
        <p>Планируй жизнь, а не перегружай её.</p>
        {content}
    </body>
    </html>
    """


@app.get("/", response_class=HTMLResponse)
def home():
    step = int(get_answer("step") or 0)

    if step < len(QUESTIONS):
        key, title, description = QUESTIONS[step]

        content = f"""
        <p>Этап 1 из 2 · Вопрос {step + 1} из {len(QUESTIONS)}</p>
        <h2>{title}</h2>
        <p>{description}</p>
        <form action="/answer" method="post">
            <input type="hidden" name="step" value="{step}">
            <textarea name="answer" required maxlength="2000"
                placeholder="Напиши свой ответ..."
                style="box-sizing:border-box;width:100%;
                min-height:120px;padding:12px;font:inherit">{escape(get_answer(key))}</textarea>
            <p><button style="padding:12px 20px">Далее →</button></p>
        </form>
        """
        return page(content)

    content = """
    <h2>🎯 Мои цели</h2>
    <p>Добавь каждую цель отдельно.</p>

    <form action="/goal" method="post"
          style="background:white;padding:16px;border-radius:10px">
        <label>Название
            <input name="name" required maxlength="100"
                placeholder="Например, английский"
                style="box-sizing:border-box;width:100%;padding:10px">
        </label>

        <p>Длительность одного занятия, минут</p>
        <input type="number" name="duration_minutes"
            min="5" max="480" value="30" required>

        <p>Сколько раз в неделю?</p>
        <input type="number" name="frequency"
            min="1" max="7" value="3" required>

        <p>Приоритет</p>
        <select name="priority">
            <option value="high">Высокий</option>
            <option value="medium" selected>Средний</option>
            <option value="low">Низкий</option>
        </select>

        <p>Предпочтительное время</p>
        <select name="preferred_time">
            <option value="any">Без предпочтений</option>
            <option value="morning">Утро</option>
            <option value="afternoon">День</option>
            <option value="evening">Вечер</option>
        </select>

        <p><button type="submit">Добавить цель</button></p>
    </form>
    """

    goals = get_goals()
    content += "<h3>Сохранённые цели</h3>"

    if goals:
        content += "<ul>"
        for goal_id, name, duration, frequency, priority, preferred in goals:
            content += f"""
            <li style="margin:12px 0">
                <strong>{escape(name)}</strong><br>
                {duration} минут · {frequency} раз в неделю<br>
                Приоритет: {PRIORITY_NAMES.get(priority, priority)}<br>
                Время: {TIME_NAMES.get(preferred, preferred)}
                <form action="/delete-goal" method="post">
                    <input type="hidden" name="goal_id" value="{goal_id}">
                    <button>Удалить цель</button>
                </form>
            </li>
            """
        content += "</ul>"
    else:
        content += "<p>Пока нет целей.</p>"

    content += "<h2>📅 Обязательные дела</h2>"

    for day, day_name in DAYS:
        content += f"""
        <section style="background:white;padding:16px;
                        border-radius:10px;margin:14px 0">
            <h3>{day_name}</h3>
            <form action="/event" method="post">
                <input type="hidden" name="day" value="{day}">
                <p>Название события</p>
                <input name="title" required maxlength="100"
                    placeholder="Работа, учёба, йога...">
                <p>Начало</p>
                <input type="time" name="start" required>
                <p>Окончание</p>
                <input type="time" name="end" required>
                <p><button>Добавить событие</button></p>
            </form>
        """

        events = get_events(day)

        if events:
            content += "<ul>"
            for event_id, _, title, start, end in events:
                content += f"""
                <li>
                    {escape(title)}: {start}–{end}
                    <form action="/delete-event" method="post"
                          style="display:inline">
                        <input type="hidden" name="event_id"
                               value="{event_id}">
                        <button>Удалить</button>
                    </form>
                </li>
                """
            content += "</ul>"
        else:
            content += "<p>Обязательных дел пока нет.</p>"

        content += "</section>"

    content += """
    <form action="/generate" method="post">
        <button style="padding:14px 20px;font-size:16px">
            ✨ Составить план на неделю
        </button>
    </form>

    <p><a href="/plan">Посмотреть сохранённый план</a></p>

    <form action="/finish" method="post">
        <button>Посмотреть сводку</button>
    </form>

    <form action="/restart" method="post" style="margin-top:16px">
        <button>Начать настройку заново</button>
    </form>

    <p style="font-size:13px;color:#666">
        Перезапуск настройки удаляет ответы, цели и события.
    </p>
    """

    return page(content)


@app.post("/answer")
def answer(step: int = Form(...), answer: str = Form(...)):
    if not 0 <= step < len(QUESTIONS):
        return RedirectResponse("/", status_code=303)

    answer = answer.strip()
    if not answer:
        return RedirectResponse("/", status_code=303)

    save_answer(QUESTIONS[step][0], answer)
    save_answer("step", str(step + 1))

    return RedirectResponse("/", status_code=303)


@app.post("/goal")
def add_goal(
    name: str = Form(...),
    duration_minutes: int = Form(...),
    frequency: int = Form(...),
    priority: str = Form(...),
    preferred_time: str = Form(...),
):
    name = name.strip()

    if (
        not name or len(name) > 100
        or not 5 <= duration_minutes <= 480
        or not 1 <= frequency <= 7
        or priority not in {"low", "medium", "high"}
        or preferred_time not in {"any", "morning", "afternoon", "evening"}
    ):
        return HTMLResponse(
            page('<h2>Проверь данные цели.</h2><a href="/">Назад</a>'),
            status_code=400,
        )

    with closing(connect_db()) as conn:
        conn.execute(
            """
            INSERT INTO goals
                (name, duration_minutes, frequency, priority, preferred_time)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, duration_minutes, frequency, priority, preferred_time),
        )
        conn.commit()

    return RedirectResponse("/", status_code=303)


@app.post("/delete-goal")
def delete_goal(goal_id: int = Form(...)):
    with closing(connect_db()) as conn:
        conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
        conn.commit()

    return RedirectResponse("/", status_code=303)


@app.post("/event")
def add_event(
    day: str = Form(...),
    title: str = Form(...),
    start: str = Form(...),
    end: str = Form(...),
):
    if day not in dict(DAYS) or not title.strip():
        return RedirectResponse("/", status_code=303)

    try:
        start_minutes = to_minutes(start)
        end_minutes = to_minutes(end)
        valid = (
            0 <= start_minutes < 1440
            and 0 <= end_minutes < 1440
            and start_minutes < end_minutes
        )
    except (ValueError, TypeError):
        valid = False

    if not valid:
        return HTMLResponse(
            page('<h2>Проверь время.</h2><a href="/">Назад</a>'),
            status_code=400,
        )

    for _, _, _, old_start, old_end in get_events(day):
        if overlaps(
            start_minutes, end_minutes,
            to_minutes(old_start), to_minutes(old_end),
        ):
            return HTMLResponse(
                page(
                    '<h2>Событие пересекается с другим.</h2>'
                    '<a href="/">Вернуться к расписанию</a>'
                ),
                status_code=400,
            )

    with closing(connect_db()) as conn:
        conn.execute(
            """
            INSERT INTO events (day, title, start, end)
            VALUES (?, ?, ?, ?)
            """,
            (day, title.strip(), start, end),
        )
        conn.commit()

    return RedirectResponse("/", status_code=303)


@app.post("/delete-event")
def delete_event(event_id: int = Form(...)):
    with closing(connect_db()) as conn:
        conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
        conn.commit()

    return RedirectResponse("/", status_code=303)


@app.post("/generate")
def generate():
    count = generate_plan()
    return RedirectResponse(f"/plan?created={count}", status_code=303)


@app.get("/plan", response_class=HTMLResponse)
def show_plan(created: int = None):
    plan = get_plan()

    if created is not None:
        content = f"<p>План создан. Запланировано занятий: {created}.</p>"

    elif plan:
        content = "<p>Это сохранённый план на неделю.</p>"
    else:
        content = "<p>План пока не создан.</p>"

    content += """
    <form action="/generate" method="post">
        <button>Пересоставить план</button>
    </form>
    """

    for day, day_name in DAYS:
        content += f"<h2>{day_name}</h2>"

        day_plan = [item for item in plan if item[2] == day]

        if not day_plan:
            content += "<p>Занятий не запланировано.</p>"
            continue

        content += "<ul>"

        for _, _, _, title, start, end in day_plan:
            content += (
                f"<li>{start}–{end}: {escape(title)}</li>"
            )

        content += "</ul>"

    content += """
    <p><a href="/">Вернуться к настройкам</a></p>
    """

    return page(content)


@app.post("/finish", response_class=HTMLResponse)
def finish():
    content = "<h2>Сохранённые данные</h2><h3>Ответы</h3><ul>"

    for key, title, _ in QUESTIONS:
        content += (
            f"<li><strong>{escape(title)}</strong>"
            f"<p>{escape(get_answer(key) or 'Не указано')}</p></li>"
        )

    content += "</ul><h3>Цели</h3>"
    goals = get_goals()

    if goals:
        content += "<ul>"
        for _, name, duration, frequency, priority, preferred in goals:
            content += (
                f"<li>{escape(name)} — {duration} минут, "
                f"{frequency} раз в неделю, "
                f"{PRIORITY_NAMES.get(priority, priority)}, "
                f"{TIME_NAMES.get(preferred, preferred)}</li>"
            )
        content += "</ul>"
    else:
        content += "<p>Целей нет.</p>"

    content += '<p><a href="/plan">Открыть план недели</a></p>'
    content += '<p><a href="/">Вернуться</a></p>'

    return page(content)


@app.post("/restart")
def restart():
    with closing(connect_db()) as conn:
        conn.execute("DELETE FROM answers")
        conn.execute("DELETE FROM events")
        conn.execute("DELETE FROM goals")
        conn.execute("DELETE FROM weekly_plan")
        conn.commit()

    return RedirectResponse("/", status_code=303)
