ARG PYTHON_IMAGE
FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app
WORKDIR /app
COPY requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY --chmod=0555 src/autonomy_lab/__init__.py src/autonomy_lab/agent.py src/autonomy_lab/context.py src/autonomy_lab/rpc.py src/autonomy_lab/isolated_agent.py /app/autonomy_lab/
USER 10001:10001
ENTRYPOINT ["python", "-m", "autonomy_lab.isolated_agent"]
