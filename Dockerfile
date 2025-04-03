FROM mcr.microsoft.com/playwright:v1.42.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt
# No need to install playwright browsers as they're already in the image

COPY . .

CMD ["python", "app.py"]  