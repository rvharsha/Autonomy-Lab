ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY src /app/src
ENV PYTHONPATH=/app/src
USER 10001:10001
CMD ["python", "-m", "uvicorn", "autonomy_lab.quote:app", "--host", "0.0.0.0", "--port", "8080"]
