FROM python:3.11-slim

RUN apt-get update && apt-get install -y postgresql-client

WORKDIR /app

RUN pip install poetry

COPY pyproject.toml poetry.lock ./
RUN poetry install

COPY . .

EXPOSE 8000

CMD ["poetry", "run", "python", "manage.py", "runserver", "0.0.0.0:8000"]
