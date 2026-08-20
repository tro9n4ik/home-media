FROM python:3.11-slim

ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_NO_CACHE_DIR=1

WORKDIR /plugin

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . /plugin

RUN mkdir -p /plugin/data

EXPOSE 8000
CMD ["python", "app/main.py"]
