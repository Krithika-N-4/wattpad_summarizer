FROM mcr.microsoft.com/playwright:v1.42.0-jammy

WORKDIR /app

COPY requirements.txt . 

# Use pip3 instead of pip
RUN apt-get update && apt-get install -y python3-pip
RUN pip3 install --no-cache-dir -r requirements.txt  

COPY . .  

CMD ["python3", "app.py"]  
