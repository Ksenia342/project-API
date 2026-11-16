
from html import escape

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

app = FastAPI()

# Временное хранилище. Позже заменим его на SQLite.
user_answers = {}
weekly_schedule = {}

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


def page(content: str) -> str:
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
        font-family: Arial, sans-serif;
        max-width: 680px;
        margin: 35px auto;
        padding: 20px;
        background: #f5f5fa;
        color: #252538;
        line-height: 1.6;
    ">
        <h1>🧠 Anti-Overload</h1>
        <p>Планируй жизнь, а не перегружай её.</p>
        {content}
    </body>
    </html>
    """


def field(label: str, name: str, value: str = "",
          placeholder: str = "") -> str:
    return f"""
    <label style="display:block;margin-top:12px">
        {escape(label)}
        <input name="{escape(name)}"
               value="{escape(value)}"
               placeholder="{escape(placeholder)}"
               required maxlength="200"
               style="box-sizing:border-box;width:100%;
                      padding:10px;margin-top:5px">
    </label>
    """


@app.get("/", response_class=HTMLResponse)
def home():
    step = int(user_answers.get("step", 0))

    if step < len(QUESTIONS):
        key, title, description = QUESTIONS[step]
        old = escape(user_answers.get(key, ""))

        content = f"""
        <p>Этап 1 из 2 · Вопрос {step + 1} из {len(QUESTIONS)}</p>
        <h2>{title}</h2>
        <p>{description}</p>
        <form action="/answer" method="post">
            <input type="hidden" name="step" value="{step}">
            <textarea name="answer" required maxlength="2000"
                placeholder="Напиши свой ответ..."
                style="box-sizing:border-box;width:100%;
                       min-height:120px;padding:12px;
                       font:inherit">{old}</textarea>
            <p><button style="padding:12px 20px">
                Далее →
            </button></p>
        </form>
        """
        return page(content)

    # После вопросов показываем расписание по дням.
    content = """
    <p>Этап 2 из 2 · Расписание недели</p>
    <h2>Какие у тебя обязательные дела?</h2>
    <p>
        Добавь работу, учёбу, йогу и другие события.
        Если день свободен, оставь его без событий.
        Время указывай в формате ЧЧ:ММ.
    </p>
    """

    for day_key, day_name in DAYS:
        events = weekly_schedule.get(day_key, [])
        content += f"""
        <section style="background:white;padding:16px;
                        border-radius:10px;margin:14px 0">
            <h3>{day_name}</h3>
            <form action="/event" method="post">
                <input type="hidden" name="day" value="{day_key}">
                <label>Название события
                    <input name="title" required maxlength="100"
                        placeholder="Работа, учёба, йога..."
                        style="box-sizing:border-box;width:100%;
                               padding:10px;margin-top:5px">
                </label>
                <label style="display:block;margin-top:10px">
                    Начало
                    <input type="time" name="start" required>
                </label>
                <label style="display:block;margin-top:10px">
                    Окончание
                    <input type="time" name="end" required>
                </label>
                <p><button type="submit">Добавить событие</button></p>
            </form>
        """

        if events:
            content += "<p><strong>Добавленные события:</strong></p><ul>"
            for index, event in enumerate(events):
                content += f"""
                <li style="margin:8px 0">
                    {escape(event['title'])}:
                    {event['start']}–{event['end']}
                    <form action="/delete-event" method="post"
                          style="display:inline">
                        <input type="hidden" name="day"
                               value="{day_key}">
                        <input type="hidden" name="index"
                               value="{index}">
                        <button type="submit">Удалить</button>
                    </form>
                </li>
                """
            content += "</ul>"

        content += "</section>"

    content += """
    <form action="/finish" method="post">
        <button style="padding:12px 20px">
            Завершить настройку →
        </button>
    </form>
    <form action="/restart" method="post" style="margin-top:12px">
        <button>Начать заново</button>
    </form>
    """

    return page(content)


@app.post("/answer")
def save_answer(step: int = Form(...), answer: str = Form(...)):
    if step < 0 or step >= len(QUESTIONS):
        return RedirectResponse("/", status_code=303)

    answer = answer.strip()
    if not answer:
        return RedirectResponse("/", status_code=303)

    key = QUESTIONS[step][0]
    user_answers[key] = answer
    user_answers["step"] = step + 1

    return RedirectResponse("/", status_code=303)


@app.post("/event")
def add_event(
    day: str = Form(...),
    title: str = Form(...),
    start: str = Form(...),
    end: str = Form(...),
):
    valid_days = {key for key, _ in DAYS}

    if day not in valid_days:
        return RedirectResponse("/", status_code=303)

    # Проверяем формат времени и что конец позже начала.
    try:
        start_minutes = int(start[:2]) * 60 + int(start[3:])
        end_minutes = int(end[:2]) * 60 + int(end[3:])
        valid_time = (
            len(start) == 5 and len(end) == 5
            and start[2] == ":" and end[2] == ":"
            and 0 <= start_minutes < 1440
            and 0 <= end_minutes < 1440
            and end_minutes > start_minutes
        )
    except (ValueError, IndexError):
        valid_time = False

    if not valid_time or not title.strip():
        return RedirectResponse("/", status_code=303)

    events = weekly_schedule.setdefault(day, [])

    # Не разрешаем пересекающиеся события в одном дне.
    for event in events:
        old_start = int(event["start"][:2]) * 60 + int(event["start"][3:])
        old_end = int(event["end"][:2]) * 60 + int(event["end"][3:])

        if start_minutes < old_end and end_minutes > old_start:
            return HTMLResponse(
                page(
                    "<h2>Время пересекается с другим событием</h2>"
                    "<p>Вернись назад и выбери другой промежуток.</p>"
                    '<p><a href="/">Вернуться к расписанию</a></p>'
                ),
                status_code=400,
            )

    events.append({
        "title": title.strip(),
        "start": start,
        "end": end,
    })

    return RedirectResponse("/", status_code=303)


@app.post("/delete-event")
def delete_event(day: str = Form(...), index: int = Form(...)):
    events = weekly_schedule.get(day, [])

    if 0 <= index < len(events):
        events.pop(index)

    return RedirectResponse("/", status_code=303)


@app.post("/finish", response_class=HTMLResponse)
def finish():
    content = "<h2>Твоё расписание собрано! 🎉</h2>"
    content += "<h3>Твои цели</h3><ul>"

    for key, title, _ in QUESTIONS:
        answer = escape(user_answers.get(key, "Не указано"))
        content += f"<li><strong>{title}</strong><p>{answer}</p></li>"

    content += "</ul><h3>Обязательные события</h3>"

    for day_key, day_name in DAYS:
        content += f"<h4>{day_name}</h4>"
        events = weekly_schedule.get(day_key, [])

        if not events:
            content += "<p>Событий не указано</p>"
        else:
            content += "<ul>"
            for event in events:
                content += (
                    f"<li>{escape(event['title'])}: "
                    f"{event['start']}–{event['end']}</li>"
                )
            content += "</ul>"

    content += """
    <p>Следующий шаг — научить программу распределять цели
       по свободному времени.</p>
    <p><a href="/">Вернуться и изменить расписание</a></p>
    """
    return page(content)


@app.post("/restart")
def restart():
    user_answers.clear()
    weekly_schedule.clear()
    return RedirectResponse("/", status_code=303)
