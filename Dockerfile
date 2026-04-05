FROM python:3.10

# Install FFmpeg
RUN apt-get update && apt-get install -y ffmpeg && apt-get clean

# Set up a non-root user (Hugging Face Requirement)
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH
WORKDIR $HOME/app

# Install dependencies
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your code
COPY --chown=user . .

# Start the bot
CMD ["python", "main.py"]

FROM python:3.10-slim
RUN apt-get update && apt-get install -y ffmpeg libass-dev && apt-get clean
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt
CMD ["python", "main.py"]
