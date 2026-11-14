FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY server.py index.html LICENSE THIRD_PARTY_NOTICES.md ./
COPY src ./src
COPY assets ./assets
RUN mkdir /app/data && chown 1000:1000 /app/data
USER 1000:1000
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=2)"
CMD ["python", "server.py", "--host", "0.0.0.0", "--data-dir", "/app/data"]
