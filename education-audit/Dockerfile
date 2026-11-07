FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOST=0.0.0.0 PORT=8000
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home audit
COPY --chown=audit:audit . .
USER audit
EXPOSE 8000
CMD ["python", "run.py", "--init-db"]
