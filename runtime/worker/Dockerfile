FROM mcr.microsoft.com/playwright/python:v1.55.0-noble@sha256:640d578aae63cfb632461d1b0aecb01414e4e020864ac3dd45a868dc0eff3078
RUN pip install --no-cache-dir playwright==1.55.0 pyee==13.0.1 greenlet==3.5.6 typing-extensions==4.16.0
COPY src/gui_agent_bench /opt/gui_agent_bench
ENV PYTHONPATH=/opt PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /tmp
USER pwuser
ENTRYPOINT ["python", "-m", "gui_agent_bench"]
