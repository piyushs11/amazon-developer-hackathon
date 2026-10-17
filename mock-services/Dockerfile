# One image for the Dev 3 mock services; pick the app with APP=demo-api|oauth.
FROM python:3.12-slim
RUN pip install --no-cache-dir fastapi uvicorn python-multipart
WORKDIR /srv
COPY demo-api ./demo-api
COPY oauth ./oauth
ENV APP=demo-api PORT=9000
CMD ["sh", "-c", "uvicorn --app-dir /srv/$APP main:app --host 0.0.0.0 --port $PORT"]
