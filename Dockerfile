FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml ./
COPY backend ./backend
COPY sim ./sim
COPY eval ./eval
RUN pip install --no-cache-dir .
COPY . .
CMD ["uvicorn", "backend.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
