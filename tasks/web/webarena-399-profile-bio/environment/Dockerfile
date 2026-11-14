FROM am1n3e/webarena-verified-reddit@sha256:0594908059a03e5f610005689440a95c05e776e734006197c7b1eba12734cb46
USER root
COPY patch.py /bench/patch.py
RUN python3 /bench/patch.py
COPY app.py router.php /bench/
ENV APP_ENV=prod APP_DEBUG=0 USE_HTTP_CACHE=0 \
    DATABASE_URL="pgsql://postgres@localhost/postmill?host=/tmp&serverVersion=14" \
    LOG_FILE=php://stderr PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER postgres
WORKDIR /var/www/html
ENTRYPOINT ["python3", "/bench/app.py"]
CMD []
